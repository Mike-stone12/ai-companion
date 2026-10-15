"""Run the memory benchmark against the current gate and extractor.

From the repository root:

    python -m eval.memory.run_benchmark                      # gate + heuristic fallback, no API calls
    python -m eval.memory.run_benchmark --extractor llm      # gate + the real LLM extractor (needs .env)
    python -m eval.memory.run_benchmark --rescore eval/memory/results/<file>.jsonl

The gate is always evaluated. The extractor then runs on every message, including the ones the gate
rejects, so the report can score the extractor on its own as well as the real pipeline; pass
``--gated-only`` to save requests. Raw extractor output is written to ``eval/memory/results/`` so a
run can be re-scored later without new requests. ``--rpm`` paces LLM calls for rate-limited
accounts (Moonshot's free tier allows 3 requests per minute).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from companion.core.memory.gate import heuristic_memory_candidates, should_extract_memory  # noqa: E402
from eval.memory.benchmark import (  # noqa: E402
    CASES_PATH,
    Case,
    GateResult,
    evaluate_gate,
    load_cases,
    load_results,
    render_report,
    score_extraction,
    simulate_store,
    summaries_from_rows,
    write_results,
)

RESULTS_DIR = Path(__file__).with_name("results")
Extractor = Callable[[Case], list[dict[str, str]]]


class WarningCapture(logging.Handler):
    """Collect extractor warnings (request failures, unparseable replies) for the results file."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def heuristic_extractor(case: Case) -> list[dict[str, str]]:
    return heuristic_memory_candidates(case.user)


def build_llm_extractor(model: str | None, base_url: str | None) -> tuple[Extractor, dict[str, str]]:
    # Importing config loads the project .env, so the key only has to be in the file.
    from companion.core.config import AppConfig
    from companion.core.llm.client import OpenAICompatibleClient
    from companion.core.memory.extractor import extract_memories_with_llm

    config = AppConfig()
    if model:
        config.model = model
    if base_url:
        config.base_url = base_url
    if not config.api_key:
        sys.exit("No API key: copy .env.example to .env and set OPENAI_API_KEY (or export it) before --extractor llm.")
    client = OpenAICompatibleClient(config)

    def extract(case: Case) -> list[dict[str, str]]:
        return extract_memories_with_llm(client, case.user, case.assistant)

    return extract, {"model": config.model, "base_url": config.base_url}


def run_extractor(
    cases: list[Case], gate: GateResult, extract: Extractor, *, gated_only: bool, rpm: float, log: Callable[[str], None]
) -> list[dict[str, object]]:
    capture = WarningCapture()
    logging.getLogger("companion.core.memory.extractor").addHandler(capture)
    interval = 60 / rpm if rpm > 0 else 0.0
    rows: list[dict[str, object]] = []
    last_start = -interval
    try:
        for index, case in enumerate(cases, 1):
            passed = gate.decisions[case.id]
            if gated_only and not passed:
                rows.append(
                    {"id": case.id, "gate": passed, "skipped": True, "memories": [], "errors": [], "elapsed_s": 0}
                )
                log(f"[{index}/{len(cases)}] {case.id} gate=n skipped")
                continue
            wait = last_start + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            capture.messages.clear()
            last_start = time.monotonic()
            memories = extract(case)
            elapsed = round(time.monotonic() - last_start, 2)
            rows.append(
                {
                    "id": case.id,
                    "gate": passed,
                    "skipped": False,
                    "memories": memories,
                    "errors": list(capture.messages),
                    "elapsed_s": elapsed,
                }
            )
            summaries = "; ".join(item["summary"] for item in memories) or "(nothing)"
            flag = " !" if capture.messages else ""
            log(f"[{index}/{len(cases)}] {case.id} gate={'y' if passed else 'n'} {elapsed:.1f}s -> {summaries}{flag}")
    finally:
        logging.getLogger("companion.core.memory.extractor").removeHandler(capture)
    return rows


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", type=Path, default=CASES_PATH, help="dataset (default: eval/memory/cases.jsonl)")
    parser.add_argument("--extractor", choices=("heuristic", "llm"), default="heuristic")
    parser.add_argument("--gated-only", action="store_true", help="only run the extractor on messages the gate passes")
    parser.add_argument("--rpm", type=float, default=0, help="pace extractor calls to this many requests per minute")
    parser.add_argument("--limit", type=int, default=0, help="only use the first N cases (smoke test)")
    parser.add_argument("--model", help="override OPENAI_MODEL for --extractor llm")
    parser.add_argument("--base-url", help="override OPENAI_BASE_URL for --extractor llm")
    parser.add_argument(
        "--output", type=Path, help="results jsonl (default: eval/memory/results/<date>-<extractor>.jsonl)"
    )
    parser.add_argument("--rescore", type=Path, help="score an earlier results file instead of running the extractor")
    parser.add_argument("--report", type=Path, help="also write the markdown report to this file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the report is mostly Chinese; Windows consoles default to GBK

    def log(message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    cases = load_cases(args.cases)
    if args.limit:
        cases = cases[: args.limit]
    gate = evaluate_gate(cases, should_extract_memory)

    if args.rescore:
        meta, rows_by_id = load_results(args.rescore)
        meta["rescored_from"] = args.rescore.as_posix()
        rows = [rows_by_id[case.id] for case in cases if case.id in rows_by_id]
        missing = [case.id for case in cases if case.id not in rows_by_id]
        if missing:
            log(f"{len(missing)} cases are not in the results file and count as extracting nothing")
    else:
        meta = {
            "extractor": args.extractor,
            "started": datetime.now().replace(microsecond=0).isoformat(),
            "cases": f"{args.cases.name} ({len(cases)} cases)",
            "gated_only": args.gated_only,
        }
        if args.extractor == "llm":
            extract, provider = build_llm_extractor(args.model, args.base_url)
            meta.update(provider)
            if args.rpm:
                meta["rpm"] = args.rpm
        else:
            extract = heuristic_extractor
        output = args.output or RESULTS_DIR / f"{datetime.now():%Y-%m-%d}-{args.extractor}.jsonl"
        rows = run_extractor(cases, gate, extract, gated_only=args.gated_only, rpm=args.rpm, log=log)
        write_results(output, meta, rows)
        log(f"results written to {output}")
        failures = sum(1 for row in rows if row.get("errors"))
        if failures:
            log(f"{failures} cases fell back to heuristics after a request failure (see 'errors' in the results file)")

    rows_by_id = {str(row["id"]): row for row in rows}
    summaries_all = summaries_from_rows(rows_by_id)
    summaries_pipeline = {case_id: items for case_id, items in summaries_all.items() if gate.decisions.get(case_id)}
    skipped = any(row.get("skipped") for row in rows)
    pipeline = score_extraction(cases, summaries_pipeline)
    extractor_only = None if skipped else score_extraction(cases, summaries_all)
    store = simulate_store(cases, summaries_pipeline)
    store_all = None if skipped else simulate_store(cases, summaries_all)

    report = render_report(cases, gate, pipeline, extractor_only, store, meta, store_all)
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        log(f"report written to {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
