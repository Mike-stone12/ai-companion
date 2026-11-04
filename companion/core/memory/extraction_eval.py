"""Evaluate memory extraction with injected callables or an opt-in live LLM.

Run ``python -m companion.core.memory.extraction_eval --live [dataset.json]``.
The default invocation only prints help; it does not construct an LLM client.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "evals" / "extraction_cases.json"


def load_dataset(path: str | Path = DEFAULT_DATASET_PATH) -> list[dict]:
    """Load and validate a UTF-8 JSON object containing a ``cases`` list.

    IDs must be unique nonblank strings. Positive cases need nonblank expected
    keywords; negative cases use an empty list. Assistant replies are optional.
    """
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(dataset, dict) or not isinstance(dataset.get("cases"), list):
        raise ValueError("Dataset must be an object with a cases list")
    seen = set()
    for index, case in enumerate(dataset["cases"], start=1):
        prefix = f"Case {index}"
        if not isinstance(case, dict):
            raise ValueError(f"{prefix} must be an object")
        for field in ("id", "user_message"):
            if not isinstance(case.get(field), str) or not case[field].strip():
                raise ValueError(f"{prefix}: {field} must be a nonblank string")
        if case["id"] in seen:
            raise ValueError(f"{prefix}: duplicate id {case['id']!r}")
        seen.add(case["id"])
        if type(case.get("should_store")) is not bool:
            raise ValueError(f"{prefix}: should_store must be a boolean")
        if not isinstance(case.get("assistant_reply", ""), str):
            raise ValueError(f"{prefix}: assistant_reply must be a string")
        keywords = case.get("expected_keywords")
        if not isinstance(keywords, list) or any(
            not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
        ):
            raise ValueError(f"{prefix}: expected_keywords must be a list of nonblank strings")
        if bool(keywords) != case["should_store"]:
            raise ValueError(f"{prefix}: expected_keywords must be nonempty exactly when should_store is true")
    return dataset["cases"]


def evaluate_extraction(cases: list[dict], extractor: Callable[[str, str], list[str]]) -> dict:
    """Score a callable taking (user_message, assistant_reply), without labels.

    A nonempty summary list predicts storage. A positive case is a keyword hit
    only if every expected substring appears in at least one summary (literal,
    case-sensitive matching). Accuracy uses all cases; keyword hit rate uses all
    positive cases. Errors fail both metrics, but have no store decision and are
    counted separately from false/missed stores. Empty denominators yield 0.0.
    """
    results = []
    correct = false_stores = missed_stores = keyword_hits = positive_count = error_count = 0
    for case in cases:
        expected = case["should_store"]
        positive_count += expected
        summaries = []
        error = None
        predicted = None
        try:
            summaries = extractor(case["user_message"], case.get("assistant_reply", ""))
            if not isinstance(summaries, list) or any(
                not isinstance(summary, str) or not summary.strip() for summary in summaries
            ):
                raise ValueError("Extractor must return a list of nonblank summary strings")
            predicted = bool(summaries)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            summaries = []
            error_count += 1
        decision_correct = error is None and predicted == expected
        correct += decision_correct
        false_stores += predicted is True and not expected
        missed_stores += predicted is False and expected
        missing = [
            keyword for keyword in case["expected_keywords"]
            if not any(keyword in summary for summary in summaries)
        ]
        keyword_hit = expected and error is None and not missing
        keyword_hits += keyword_hit
        results.append({
            **case,
            "summaries": summaries,
            "predicted": predicted,
            "decision_correct": decision_correct,
            "keyword_hit": keyword_hit,
            "missing_keywords": missing,
            "error": error,
        })
    return {
        "case_count": len(cases),
        "accuracy": correct / len(cases) if cases else 0.0,
        "false_store_count": false_stores,
        "missed_store_count": missed_stores,
        "keyword_hits": keyword_hits,
        "positive_count": positive_count,
        "keyword_hit_rate": keyword_hits / positive_count if positive_count else 0.0,
        "error_count": error_count,
        "results": results,
    }


def format_report(result: dict) -> str:
    """Return aggregate metrics and details for failed or errored cases."""
    lines = [
        f"Extraction evaluation: {result['case_count']} cases",
        f"Store-decision accuracy={result['accuracy']:.4f}",
        f"False stores={result['false_store_count']} Missed stores={result['missed_store_count']}",
        f"Keyword hit rate={result['keyword_hit_rate']:.4f} "
        f"({result['keyword_hits']}/{result['positive_count']})",
        f"Errors={result['error_count']} (fail accuracy/keyword metrics; excluded from store counts)",
    ]
    for case in result["results"]:
        if case["error"]:
            lines.append(f"  {case['id']}: ERROR {case['error']}")
        elif not case["decision_correct"] or case["missing_keywords"]:
            lines.append(
                f"  {case['id']}: expected={case['should_store']} predicted={case['predicted']} "
                f"missing={case['missing_keywords']} summaries={case['summaries']}"
            )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--live", action="store_true", help="Send case messages to the configured LLM endpoint")
    args = parser.parse_args(argv)
    if not args.live:
        parser.print_help()
        print("A live run requires --live and an API key (OPENAI_API_KEY or MOONSHOT_API_KEY).")
        return

    from companion.core.api_key import resolve_api_key
    from companion.core.config import AppConfig
    from companion.core.llm.client import OpenAICompatibleClient
    from companion.core.memory.extractor import extract_memories_with_llm

    config = AppConfig(api_key=resolve_api_key())
    if not config.api_key.strip():
        parser.error("--live requires an API key (system keychain, OPENAI_API_KEY, or MOONSHOT_API_KEY)")
    cases = load_dataset(args.path)
    client = OpenAICompatibleClient(config)

    def extract(user_message: str, assistant_reply: str) -> list[str]:
        return [item["summary"] for item in extract_memories_with_llm(client, user_message, assistant_reply)]

    print(f"Dataset: {args.path}")
    print("Live extraction uses the existing extractor, including its heuristic fallback on LLM/parse failures.")
    print(format_report(evaluate_extraction(cases, extract)))


if __name__ == "__main__":
    main()
