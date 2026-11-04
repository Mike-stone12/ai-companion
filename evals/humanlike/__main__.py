"""Does the companion sound like a person? Run scripted chats in the real window and judge them.

    python -m evals.humanlike run --label master                 # real model from .env / environment
    python -m evals.humanlike run --label my-change --app-dir ../other-checkout
    python -m evals.humanlike run --fake --no-judge             # dry run against a local fake endpoint
    python -m evals.humanlike compare results/A.json results/B.json
    python -m evals.humanlike report results/A.json             # rewrite the .md with current metrics

``run`` plays every scenario in ``scenarios.json`` through ``CompanionWindow`` (one fresh
process and data directory each), then reports rule-based metrics (metrics.py) and, unless
``--no-judge``, an LLM judge's 1-10 scores (judge.py). ``compare`` asks the judge which of
two saved runs is more human, scenario by scenario, in both orders. Results go to
``evals/humanlike/results/``. A real run sends the scripted chats and transcripts to the
configured endpoint (``JUDGE_MODEL`` picks the judge model; default: the chat model).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from statistics import mean, median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCENARIOS = HERE / "scenarios.json"
RESULTS = HERE / "results"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.humanlike import judge as judging  # noqa: E402
from evals.humanlike.metrics import summarize, transcript_metrics  # noqa: E402

PERSONA_SUMMARY = (
    "the user's childhood friend from next door (青梅竹马), warm and loyal, teases a little, notices when "
    "the user is tired; casual, short spoken sentences with a bit of attitude; has her own daily routine "
    "(class or work, evenings off, sleepy late at night)"
)
METRIC_ROWS = (
    ("messages_per_reply", "Messages per reply", "{:.2f}"),
    ("median_chars", "Median characters per message", "{:g}"),
    ("replies_ending_with_question", "Replies ending with a question", "{}"),
    ("assistant_phrase_hits", "Assistant phrases", "{}"),
    ("markdown", "Markdown messages", "{}"),
    ("exclamations", "Exclamation marks", "{}"),
    ("emoji", "Emoji", "{}"),
    ("repeated_openers", "Replies opening like an earlier one", "{}"),
    ("verbatim_repeats", "Messages repeated word for word", "{}"),
    ("missing_replies", "Turns without a reply", "{}"),
    ("bubbles_before_user_finished", "Her bubbles before the user finished a burst", "{}"),
    ("questions", "Question marks in her messages", "{}"),
    ("either_or", "Either-or guesses (是A还是B)", "{}"),
    ("echo_questions", "Questions echoing the user's words (抱着一只猫？)", "{}"),
    ("stage_directions", "Stage directions （…）", "{}"),
)


def load_scenarios(path: Path = SCENARIOS) -> list[dict]:
    scenarios = json.loads(path.read_text(encoding="utf-8"))["scenarios"]
    seen = set()
    for scenario in scenarios:
        if scenario["id"] in seen:
            raise ValueError(f"duplicate scenario id {scenario['id']!r}")
        seen.add(scenario["id"])
        datetime.fromisoformat(scenario["clock"])
        for turn in scenario["turns"]:
            if not turn["user"] or any(not text.strip() for text in turn["user"]):
                raise ValueError(f"{scenario['id']}: every turn needs nonblank user messages")
            if len(turn.get("gaps", [])) not in (0, len(turn["user"]) - 1):
                raise ValueError(f"{scenario['id']}: gaps must sit between the user messages")
        if not scenario.get("focus", "").strip():
            raise ValueError(f"{scenario['id']}: focus is required")
    return scenarios


def git_commit(path: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def make_judge(model: str | None = None):
    from companion.core.api_key import ApiKeyStore
    from companion.core.config import AppConfig
    from companion.core.llm.client import OpenAICompatibleClient, chat_request_options

    config = AppConfig(api_key=ApiKeyStore().resolve().value)
    if model:
        config = AppConfig(api_key=config.api_key, base_url=config.base_url, model=model)
    if not config.api_key:
        raise SystemExit("No API key: set OPENAI_API_KEY (or use --no-judge).")
    client = OpenAICompatibleClient(config)
    options = chat_request_options(config)
    return config.model, lambda messages: client.complete(messages, temperature=0.2, extra=options)


def play(scenarios: list[dict], app_dir: Path, base_url: str | None) -> list[dict]:
    transcripts = []
    for scenario in scenarios:
        with tempfile.TemporaryDirectory(prefix="companion-humanlike-") as data_dir:
            out = Path(data_dir) / "transcript.json"
            env = {**os.environ, "COMPANION_DATA_DIR": data_dir}
            if base_url:
                env.update(OPENAI_BASE_URL=base_url, OPENAI_API_KEY="fake", OPENAI_MODEL="fake")
            command = [
                sys.executable, str(HERE / "drive.py"), scenario["id"], str(out),
                "--app-dir", str(app_dir), "--scenarios", str(SCENARIOS),
            ]
            # Software WebGL occasionally crashes Chromium at start (see the Package workflow); retry once.
            for _attempt in range(2):
                result = subprocess.run(command, env=env, capture_output=True, text=True, cwd=str(app_dir))
                if result.returncode == 0 and out.exists():
                    break
            if not out.exists():
                print(f"  {scenario['id']}: driver failed\n{result.stderr[-2000:]}", file=sys.stderr)
                transcripts.append({"id": scenario["id"], "turns": [], "error": "driver failed"})
                continue
            transcript = json.loads(out.read_text(encoding="utf-8"))
            print(f"  {scenario['id']}: {sum(len(t['reply']) for t in transcript['turns'])} messages")
            transcripts.append(transcript)
    return transcripts


def run(args: argparse.Namespace) -> Path:
    scenarios = load_scenarios()
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    app_dir = (args.app_dir or ROOT).resolve()
    server = None
    base_url = None
    if args.fake:
        from evals.humanlike import fake_server

        server, base_url = fake_server.start()
    judge_model, judge = (None, None) if args.no_judge else make_judge(os.getenv("JUDGE_MODEL"))
    print(f"Playing {len(scenarios)} scenarios x {args.repeat} in {app_dir} ({git_commit(app_dir)})")
    played = []
    for run_index in range(1, args.repeat + 1):
        played += [(run_index, s, t) for s, t in zip(scenarios, play(scenarios, app_dir, base_url), strict=True)]
    if server is not None:
        server.shutdown()

    results = []
    for run_index, scenario, transcript in played:
        entry = {
            "id": scenario["id"], "run": run_index, "title": scenario["title"], "focus": scenario["focus"],
            "turns": transcript["turns"], "metrics": transcript_metrics(transcript["turns"]),
        }
        if transcript.get("error"):
            entry["error"] = transcript["error"]
        elif judge is not None:
            try:
                entry["judge"] = judging.score(judge, transcript["turns"], persona=PERSONA_SUMMARY,
                                               focus=scenario["focus"])
            except Exception as exc:  # one bad judge reply should not lose the run
                entry["judge_error"] = f"{type(exc).__name__}: {exc}"
        results.append(entry)

    run_data = {
        "label": args.label, "date": datetime.now().isoformat(timespec="seconds"),
        "app_commit": git_commit(app_dir), "chat_model": "fake" if args.fake else os.getenv("OPENAI_MODEL", ""),
        "judge_model": judge_model, "repeat": args.repeat, "scenarios": results,
    }
    RESULTS.mkdir(exist_ok=True)
    stem = f"{datetime.now():%Y-%m-%d}-{args.label}"
    json_path = RESULTS / f"{stem}.json"
    json_path.write_text(json.dumps(run_data, ensure_ascii=False, indent=1), encoding="utf-8")
    (RESULTS / f"{stem}.md").write_text(report(run_data), encoding="utf-8")
    print(report(run_data).split("\n## ")[0])
    print(f"Saved {json_path.relative_to(ROOT)} and the .md report")
    return json_path


def judge_means(scenarios: list[dict]) -> dict:
    judged = [s["judge"] for s in scenarios if "judge" in s]
    keys = (*judging.SCORE_KEYS, "overall")
    return {key: mean(j[key] for j in judged) for key in keys} if judged else {}


def report(run_data: dict) -> str:
    scenarios = run_data["scenarios"]
    total = summarize([s["metrics"] for s in scenarios])
    lines = [
        f"# Human-likeness: {run_data['label']}",
        "",
        f"App {run_data['app_commit']}, chat model `{run_data['chat_model']}`, "
        f"judge `{run_data['judge_model'] or 'none'}`, {run_data['date']}.",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    means = judge_means(scenarios)
    for key in (*judging.SCORE_KEYS, "overall"):
        if key in means:
            lines.append(f"| Judge: {key} (1-10) | {means[key]:.2f} |")
    lines += [f"| {label} | {fmt.format(total[key])} |" for key, label, fmt in METRIC_ROWS]
    waits = [t["first_reply_s"] for s in scenarios for t in s["turns"] if t.get("first_reply_s") is not None]
    if waits:
        lines.append(f"| Median wait for her first bubble after the user's last line (s) | {median(waits):.2f} |")
    lines.append(f"| Bursts she answered halfway | {total['bursts_interrupted']} / {total['burst_turns']} |")
    lines.append(f"| Replies / messages | {total['replies']} / {total['messages']} |")
    if total["phrases"]:
        lines.append(f"| Phrases found | {', '.join(sorted(set(total['phrases'])))} |")
    for s in scenarios:
        lines += ["", f"## {s['id']} (run {s.get('run', 1)}): {s['title']}", ""]
        if "judge" in s:
            j = s["judge"]
            lines.append(
                f"Judge: human {j['human']:g}, character {j['character']:g}, emotion {j['emotion']:g}, "
                f"context {j['context']:g}. {j['comment']}"
            )
            if j.get("flaws"):
                lines.append(f"Flaws: {' / '.join(j['flaws'])}")
            if j["assistant_moments"]:
                lines.append(f"Assistant-like: {' / '.join(j['assistant_moments'])}")
            lines.append("")
        for key in ("error", "judge_error"):
            if key in s:
                lines += [f"**{key}:** {s[key]}", ""]
        lines.append("```")
        lines.append(judging.render_transcript(s["turns"]))
        lines.append("```")
    return "\n".join(lines) + "\n"


def compare(args: argparse.Namespace) -> None:
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    judge_model, judge = make_judge(os.getenv("JUDGE_MODEL"))
    by_id = {(s["id"], s.get("run", 1)): s for s in before["scenarios"]}
    rows, tally = [], {"after": 0, "before": 0, "tie": 0}
    for s in after["scenarios"]:
        key = (s["id"], s.get("run", 1))
        if key not in by_id or not s["turns"] or not by_id[key]["turns"]:
            continue
        verdict = judging.compare(judge, by_id[key]["turns"], s["turns"], persona=PERSONA_SUMMARY, focus=s["focus"])
        tally[verdict["result"]] += 1
        rows.append(f"| {s['id']} #{key[1]} | {verdict['result']} | {' / '.join(verdict['reasons'])} |")
    text = "\n".join([
        f"# {after['label']} vs {before['label']}",
        "",
        f"Judge `{judge_model}`, each scenario judged twice with the order swapped.",
        "",
        f"**More human: after {tally['after']}, before {tally['before']}, tie {tally['tie']}**",
        "",
        "| Scenario | More human | Judge's reasons |",
        "| --- | --- | --- |",
        *rows,
        "",
        "| Judge mean (1-10) | before | after |",
        "| --- | --- | --- |",
        *[
            f"| {key} | {judge_means(before['scenarios']).get(key, float('nan')):.2f} | "
            f"{judge_means(after['scenarios']).get(key, float('nan')):.2f} |"
            for key in (*judging.SCORE_KEYS, "overall")
        ],
    ]) + "\n"
    out = RESULTS / f"{datetime.now():%Y-%m-%d}-compare-{before['label']}-vs-{after['label']}.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"Saved {out.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m evals.humanlike", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="play the scenarios and score them")
    run_parser.add_argument("--label", default="run", help="name for the result files")
    run_parser.add_argument("--app-dir", type=Path, help="checkout whose app code to run (default: this one)")
    run_parser.add_argument("--only", help="comma-separated scenario ids")
    run_parser.add_argument("--fake", action="store_true", help="use a local fake endpoint (dry run)")
    run_parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge")
    run_parser.add_argument("--repeat", type=int, default=2, help="play every scenario this many times (default 2)")
    report_parser = sub.add_parser("report", help="rewrite a saved run's .md (no requests)")
    report_parser.add_argument("results", type=Path)
    compare_parser = sub.add_parser("compare", help="blind A/B of two saved runs")
    compare_parser.add_argument("before")
    compare_parser.add_argument("after")
    args = parser.parse_args(argv)
    if args.command == "run":
        run(args)
    elif args.command == "report":
        run_data = json.loads(args.results.read_text(encoding="utf-8"))
        # Metrics are recomputed from the transcripts, so new metrics apply to old runs.
        for scenario in run_data["scenarios"]:
            scenario["metrics"] = transcript_metrics(scenario["turns"])
        args.results.with_suffix(".md").write_text(report(run_data), encoding="utf-8")
        print(report(run_data).split("\n## ")[0])
    else:
        compare(args)


if __name__ == "__main__":
    main()
