"""The windowed half of the self-test: open the real window and wait for the model to render."""

from __future__ import annotations

import sys
import time

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from companion.core.config import AppConfig
from companion.self_test import Check

RENDER_TIMEOUT_S = 45
POLL_MS = 250
# Motion groups exist only after pixi-live2d-display has loaded the model into WebGL.
# The status line carries the renderer's own error message (e.g. no WebGL) for the report.
MODEL_PROBE = """({
    groups: window.Live2DController ? window.Live2DController.getMotionGroups().length : -1,
    message: (document.getElementById("message") || {}).textContent || "",
})"""


def gui_checks(timeout_s: float = RENDER_TIMEOUT_S) -> list[Check]:
    # No Python Qt message handler here: WebEngine threads logging through a Python callback
    # need the GIL and could deadlock against the main thread. The renderer's own status
    # line (MODEL_PROBE) carries its error message into the report instead.
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from companion.ui.main_window import CompanionWindow

    # No key and every opt-in feature off: nothing reaches the network or a device.
    config = AppConfig(
        api_key="", proactive_chat=False, active_app_monitor=False, chat_tools=False,
        voice_input=False, wake_word=False, memory_semantic_recall=False,
    )
    window = CompanionWindow(config)
    window.show()
    state = {"loaded": None, "groups": -1, "message": ""}
    window.web_view.loadFinished.connect(lambda ok: state.update(loaded=ok))

    loop = QEventLoop()
    deadline = time.monotonic() + timeout_s

    def record(value: object) -> None:
        if isinstance(value, dict):
            state.update(groups=int(value.get("groups") or -1), message=str(value.get("message") or ""))

    def poll() -> None:
        rendered = state["groups"] > 0 and window.renderer_ready
        # The renderer reports start-up failures on its status line; stop waiting then.
        if rendered or "failed" in state["message"].lower() or time.monotonic() > deadline:
            loop.quit()
            return
        if state["loaded"]:
            window.web_view.page().runJavaScript(MODEL_PROBE, record)

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(POLL_MS)
    loop.exec()
    timer.stop()

    checks = [
        Check("main window", True, f"{window.width()}x{window.height()}"),
        Check("renderer page", bool(state["loaded"]), "" if state["loaded"] else "page did not finish loading"),
        Check("renderer bridge", window.renderer_ready, "" if window.renderer_ready else "QWebChannel never connected"),
        Check(
            "Live2D model rendered", state["groups"] > 0,
            f"{state['groups']} motion groups" if state["groups"] > 0
            else f"not loaded (renderer status: {state['message'] or 'none'})",
        ),
    ]
    window.close()
    app.processEvents()
    return checks
