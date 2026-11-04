"""Play one scenario through the real CompanionWindow (offscreen) and save the transcript.

Run by ``python -m evals.humanlike run``, one process per scenario so every scenario
starts from empty user data (``COMPANION_DATA_DIR`` is set by the parent). The app
code is imported from ``--app-dir`` so the same driver can measure another checkout
(a baseline). Nothing here is part of the app; it needs PyQt6 and PyQt6-WebEngine.

    python evals/humanlike/drive.py SCENARIO_ID OUT.json --app-dir PATH [--scenarios FILE]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

TURN_TIMEOUT_S = 120
RENDER_TIMEOUT_S = 30
# Software rendering, as in the Package workflow's Linux self-test (no GPU, root, no sandbox).
QT_ENV = {
    "QT_QPA_PLATFORM": "offscreen",
    "QTWEBENGINE_DISABLE_SANDBOX": "1",
    "QTWEBENGINE_CHROMIUM_FLAGS": (
        "--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader --disable-gpu-compositing"
    ),
    "QT_QUICK_BACKEND": "software",
    "COMPANION_KEYCHAIN": "0",
}


def strip_tag(line: str) -> str:
    line = line.strip()
    if line.startswith("[") and "]" in line[:16]:
        return line[line.index("]") + 1:].strip()
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario")
    parser.add_argument("out", type=Path)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--scenarios", type=Path, required=True)
    args = parser.parse_args(argv)

    for key, value in QT_ENV.items():
        os.environ.setdefault(key, value)
    sys.path.insert(0, str(args.app_dir.resolve()))
    scenario = next(
        s for s in json.loads(args.scenarios.read_text(encoding="utf-8"))["scenarios"] if s["id"] == args.scenario
    )

    from PyQt6 import QtWebEngineWidgets  # noqa: F401  (must be imported before QApplication)
    from PyQt6.QtCore import QEventLoop
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    import companion.ui.main_window as mw
    from companion.core.api_key import ApiKeyStore
    from companion.core.config import AppConfig

    # The scenario's wall clock, running forward in real time (routine, mood, late night).
    start_clock = datetime.fromisoformat(scenario["clock"])
    started = time.monotonic()
    mw.local_now = lambda: start_clock + timedelta(seconds=time.monotonic() - started)
    # Text only: speech needs the network and changes nothing the judge sees.
    mw.tts_edge.is_available = lambda: False

    config = AppConfig(api_key=ApiKeyStore().resolve().value)
    overrides = dict(
        proactive_chat=False, active_app_monitor=False, voice_input=False, wake_word=False, chat_tools=False,
    )
    config = replace(config, **{key: value for key, value in overrides.items() if hasattr(config, key)})
    window = mw.CompanionWindow(config)
    window.show()
    shown: list[tuple[float, str]] = []
    original_add = window.chat_panel.add_reply_message

    def record(text: str) -> None:
        shown.append((time.monotonic(), text))
        original_add(text)

    window.chat_panel.add_reply_message = record

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)

    def idle() -> bool:
        waiting = getattr(window, "merge_waiting", lambda: False)()
        return not (
            window.busy or waiting or getattr(window, "pending_messages", None)
            or (hasattr(window, "message_timer") and window.message_timer.isActive())
        )

    deadline = time.monotonic() + RENDER_TIMEOUT_S
    while not window.renderer_ready and time.monotonic() < deadline:
        pump(0.1)

    turns = []
    for turn in scenario["turns"]:
        gaps = turn.get("gaps", [])
        before = len(window.messages)
        shown_before = len(shown)
        last_sent = 0.0
        waited = []
        sends: list[tuple[float, str]] = []
        for index, text in enumerate(turn["user"]):
            if index:
                pump(gaps[index - 1] if index - 1 < len(gaps) else 1.0)
            # Like a real user, wait while the app will not take input (before message merging,
            # the input is disabled while she replies), then send.
            blocked_at = time.monotonic()
            while not window.chat_input.isEnabled() and time.monotonic() - blocked_at < TURN_TIMEOUT_S:
                pump(0.05)
            waited.append(round(time.monotonic() - blocked_at, 2))
            # "quote": [turn, message] quotes her message from an earlier turn of this run (apps
            # without quote replies just send the text).
            seen_as = text
            if index == 0 and turn.get("quote") and hasattr(window, "set_quote"):
                at_turn, at_message = turn["quote"]
                earlier = turns[at_turn]["reply"]
                if at_message < len(earlier):
                    window.set_quote(earlier[at_message], False)
                    seen_as = f"（引用她说的「{earlier[at_message]}」）{text}"
            window.chat_input.setText(text)
            window.send_message()
            last_sent = time.monotonic()
            sends.append((last_sent, seen_as))
        pump(0.2)
        end = time.monotonic() + TURN_TIMEOUT_S
        while not idle() and time.monotonic() < end:
            pump(0.05)
        replies = [m["content"] for m in window.messages[before:] if m["role"] == "assistant"]
        lines = [strip_tag(line) for content in replies for line in content.splitlines()]
        new_shown = shown[shown_before:]
        # What the user saw, in order, with seconds since the turn's first message: bubbles from
        # both sides, so a reply to half a sentence or a line sent mid-reply is visible.
        origin = sends[0][0]
        timeline = sorted(
            [(t, "user", text) for t, text in sends] + [(t, "her", text) for t, text in new_shown]
        )
        turns.append({
            "user": turn["user"],
            "reply": [line for line in lines if line],
            "timeline": [[round(t - origin, 1), who, text] for t, who, text in timeline],
            "waited_s": waited,
            # Her first bubble after the user's last line: how long the user waited for an answer.
            "first_reply_s": next((round(t - last_sent, 2) for t, _ in new_shown if t >= last_sent), None),
            "timed_out": not idle(),
        })
        pump(1.0)

    args.out.write_text(json.dumps({"id": scenario["id"], "turns": turns}, ensure_ascii=False, indent=1))
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
