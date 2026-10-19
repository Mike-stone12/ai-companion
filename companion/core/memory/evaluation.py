"""Offline evaluation of the extraction gate and lexical memory recall.

Run with ``python -m companion.core.memory.evaluation [dataset.json]``.
Labels describe desired selections, including known limitations of the current
heuristics. Recall hit rate is micro-averaged over distinct expected summaries
within each scenario; selection order and extra selections do not affect it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from companion.core.memory.gate import should_extract_memory
from companion.core.memory.recall import select_memories

DEFAULT_DATASET_PATH = Path(__file__).resolve().parents[3] / "evals" / "memory_cases.json"


def load_dataset(path: str | Path) -> dict:
    """Load a UTF-8 JSON dataset with ``gate`` and ``recall`` sections."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_gate(cases: list[dict]) -> dict:
    """Return confusion counts, metrics, and the misclassified messages."""
    counts = dict.fromkeys(("tp", "fp", "tn", "fn"), 0)
    misclassified = []
    for case in cases:
        predicted = should_extract_memory(case["message"])
        expected = case["expected"]
        key = ("t" if predicted == expected else "f") + ("p" if predicted else "n")
        counts[key] += 1
        if predicted != expected:
            misclassified.append({**case, "predicted": predicted})
    return {
        **counts,
        "precision": _ratio(counts["tp"], counts["tp"] + counts["fp"]),
        "recall": _ratio(counts["tp"], counts["tp"] + counts["fn"]),
        "accuracy": _ratio(counts["tp"] + counts["tn"], len(cases)),
        "misclassified": misclassified,
    }


def evaluate_recall(cases: list[dict]) -> dict:
    """Return summary hit rate, complete-scenario count, and failure details.

    A scenario with no expected summaries is complete, but contributes zero to
    both the hit count and its denominator. An empty denominator yields 0.0.
    """
    hits = expected_count = complete_scenarios = 0
    failed_scenarios = []
    for index, case in enumerate(cases, start=1):
        selected = select_memories(case["memories"], case["query"], limit=case["limit"])
        selected_summaries = [item["summary"] for item in selected]
        expected = set(case["expected"])
        missing = expected - set(selected_summaries)
        hits += len(expected) - len(missing)
        expected_count += len(expected)
        if not missing:
            complete_scenarios += 1
        else:
            failed_scenarios.append({
                "name": case.get("name", f"Scenario {index}"),
                "query": case["query"],
                "expected": case["expected"],
                "selected": selected_summaries,
                "missing": sorted(missing),
            })
    return {
        "hits": hits,
        "expected_count": expected_count,
        "hit_rate": _ratio(hits, expected_count),
        "complete_scenarios": complete_scenarios,
        "scenario_count": len(cases),
        "failed_scenarios": failed_scenarios,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path, default=DEFAULT_DATASET_PATH)
    args = parser.parse_args(argv)
    dataset = load_dataset(args.path)
    gate = evaluate_gate(dataset["gate"])
    recall = evaluate_recall(dataset["recall"])
    print(f"Memory evaluation: {args.path}")
    print(f"Gate: TP={gate['tp']} FP={gate['fp']} TN={gate['tn']} FN={gate['fn']}")
    print(
        f"  Precision={gate['precision']:.4f} Recall={gate['recall']:.4f} "
        f"Accuracy={gate['accuracy']:.4f}"
    )
    print(f"Misclassified gate messages: {len(gate['misclassified'])}")
    for case in gate["misclassified"]:
        print(f"  expected={case['expected']} predicted={case['predicted']}: {case['message']}")
    print(
        f"Recall: hit rate={recall['hit_rate']:.4f} ({recall['hits']}/{recall['expected_count']}); "
        f"complete scenarios={recall['complete_scenarios']}/{recall['scenario_count']}"
    )
    print(f"Failed recall scenarios: {len(recall['failed_scenarios'])}")
    for case in recall["failed_scenarios"]:
        print(f"  {case['name']}: {case['query']}")
        print(f"    Missing: {case['missing']}")
        print(f"    Selected: {case['selected']}")


if __name__ == "__main__":
    main()
