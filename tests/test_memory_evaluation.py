from copy import deepcopy
from datetime import datetime

import pytest

from companion.core.memory.evaluation import (
    DEFAULT_DATASET_PATH,
    evaluate_gate,
    evaluate_recall,
    load_dataset,
    main,
)

# Measured on the checked-in fictional dataset; rates rounded DOWN to two decimals.
# Gate: TP=17, FP=4, TN=12, FN=3. Recall: 23/25 hits, 10/12 complete scenarios.
BASELINE_GATE_PRECISION = 0.80
BASELINE_GATE_RECALL = 0.85
BASELINE_GATE_ACCURACY = 0.80
BASELINE_RECALL_HIT_RATE = 0.92
BASELINE_COMPLETE_SCENARIOS = 10


def memory(summary, day):
    return {
        "summary": summary,
        "category": "preference",
        "source": "chat",
        "updated_at": f"2026-01-{day:02d}T12:00:00+00:00",
    }


def test_gate_metrics_and_failure_details():
    cases = [
        {"message": "我喜欢折纸。", "expected": True},
        {"message": "我准备学习陶艺。", "expected": True},
        {"message": "明天天气怎么样？", "expected": False},
        {"message": "你好呀。", "expected": False},
        {"message": "每周二都去练书法。", "expected": True},
    ]
    before = deepcopy(cases)
    result = evaluate_gate(cases)
    assert {key: result[key] for key in ("tp", "fp", "tn", "fn")} == {"tp": 2, "fp": 1, "tn": 1, "fn": 1}
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == pytest.approx(2 / 3)
    assert result["accuracy"] == pytest.approx(3 / 5)
    assert result["misclassified"] == [
        {**cases[2], "predicted": True},
        {**cases[4], "predicted": False},
    ]
    assert cases == before


@pytest.mark.parametrize(
    "cases,counts,accuracy",
    [
        ([], (0, 0, 0, 0), 0.0),
        ([{"message": "你好", "expected": False}], (0, 0, 1, 0), 1.0),
        ([{"message": "每周二都去练书法。", "expected": True}], (0, 0, 0, 1), 0.0),
        ([{"message": "明天天气怎么样？", "expected": False}], (0, 1, 0, 0), 0.0),
    ],
)
def test_gate_empty_and_zero_denominators(cases, counts, accuracy):
    result = evaluate_gate(cases)
    assert tuple(result[key] for key in ("tp", "fp", "tn", "fn")) == counts
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["accuracy"] == accuracy


def test_recall_metrics_are_micro_averaged_and_report_failures():
    cases = [
        {
            "name": "partial",
            "memories": [memory("偏爱绿茶", 1), memory("喜欢折纸", 2)],
            "query": "", "limit": 1, "expected": ["偏爱绿茶", "喜欢折纸"],
        },
        {
            "name": "complete",
            "memories": [memory("练习游泳", 1), memory("学习陶艺", 2)],
            "query": "", "limit": 2, "expected": ["练习游泳"],
        },
    ]
    before = deepcopy(cases)
    result = evaluate_recall(cases)
    assert result["hits"] == 2
    assert result["expected_count"] == 3
    assert result["hit_rate"] == pytest.approx(2 / 3)
    assert result["complete_scenarios"] == 1
    assert result["scenario_count"] == 2
    assert result["failed_scenarios"] == [{
        "name": "partial", "query": "", "expected": ["偏爱绿茶", "喜欢折纸"],
        "selected": ["喜欢折纸"], "missing": ["偏爱绿茶"],
    }]
    assert cases == before


@pytest.mark.parametrize(
    "cases,complete,expected_count",
    [
        ([], 0, 0),
        ([{"memories": [], "query": "茶", "limit": 2, "expected": []}], 1, 0),
        ([{"memories": [memory("绿茶", 1)], "query": "茶", "limit": 2, "expected": []}], 1, 0),
        ([{"memories": [], "query": "茶", "limit": 2, "expected": ["绿茶"]}], 0, 1),
        ([{"memories": [memory("绿茶", 1)], "query": "茶", "limit": 0, "expected": ["绿茶"]}], 0, 1),
    ],
)
def test_recall_empty_and_zero_denominators(cases, complete, expected_count):
    result = evaluate_recall(cases)
    assert result["hit_rate"] == 0.0
    assert result["hits"] == 0
    assert result["expected_count"] == expected_count
    assert result["complete_scenarios"] == complete
    assert result["scenario_count"] == len(cases)
    assert len(result["failed_scenarios"]) == len(cases) - complete


def test_recall_counts_distinct_summaries_per_scenario():
    result = evaluate_recall([{
        "memories": [memory("绿茶", 1), memory("绿茶", 2)],
        "query": "绿茶", "limit": 2, "expected": ["绿茶", "绿茶"],
    }])
    assert result["hits"] == result["expected_count"] == 1
    assert result["hit_rate"] == 1.0
    assert result["complete_scenarios"] == 1


def test_dataset_loads_and_has_required_fields():
    dataset = load_dataset(DEFAULT_DATASET_PATH)
    assert isinstance(dataset["gate"], list)
    assert 30 <= len(dataset["gate"]) <= 40
    assert len({case["message"] for case in dataset["gate"]}) == len(dataset["gate"])
    for case in dataset["gate"]:
        assert isinstance(case["message"], str) and case["message"].strip()
        assert any("\u4e00" <= char <= "\u9fff" for char in case["message"])
        assert type(case["expected"]) is bool
    assert {case["expected"] for case in dataset["gate"]} == {True, False}

    assert isinstance(dataset["recall"], list)
    assert 10 <= len(dataset["recall"]) <= 15
    assert len({case["name"] for case in dataset["recall"]}) == len(dataset["recall"])
    for case in dataset["recall"]:
        assert isinstance(case["name"], str) and case["name"].strip()
        assert isinstance(case["query"], str)
        assert type(case["limit"]) is int and case["limit"] > 0
        assert isinstance(case["memories"], list) and case["memories"]
        for entry in case["memories"]:
            for field in ("summary", "category", "source", "updated_at"):
                assert isinstance(entry[field], str) and entry[field].strip()
            assert datetime.fromisoformat(entry["updated_at"]).tzinfo is not None
        assert isinstance(case["expected"], list) and case["expected"]
        assert all(isinstance(summary, str) and summary.strip() for summary in case["expected"])
        assert len(set(case["expected"])) == len(case["expected"]) <= case["limit"]
        assert set(case["expected"]) <= {entry["summary"] for entry in case["memories"]}


def test_dataset_baseline_regression():
    dataset = load_dataset(DEFAULT_DATASET_PATH)
    gate = evaluate_gate(dataset["gate"])
    recall = evaluate_recall(dataset["recall"])
    assert gate["precision"] >= BASELINE_GATE_PRECISION
    assert gate["recall"] >= BASELINE_GATE_RECALL
    assert gate["accuracy"] >= BASELINE_GATE_ACCURACY
    assert recall["hit_rate"] >= BASELINE_RECALL_HIT_RATE
    assert recall["complete_scenarios"] >= BASELINE_COMPLETE_SCENARIOS


@pytest.mark.parametrize("explicit_path", [False, True])
def test_main_reports_metrics_and_failures_from_any_directory(explicit_path, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    main([str(DEFAULT_DATASET_PATH)] if explicit_path else [])
    output = capsys.readouterr().out
    for label in ("Precision=", "Recall=", "Accuracy=", "hit rate=", "complete scenarios="):
        assert label in output
    dataset = load_dataset(DEFAULT_DATASET_PATH)
    for case in evaluate_gate(dataset["gate"])["misclassified"]:
        assert case["message"] in output
    for case in evaluate_recall(dataset["recall"])["failed_scenarios"]:
        assert case["name"] in output
        assert case["query"] in output
        assert all(summary in output for summary in case["missing"])


def test_main_accepts_custom_dataset(tmp_path, capsys):
    path = tmp_path / "empty.json"
    path.write_text('{"gate": [], "recall": []}', encoding="utf-8")
    assert load_dataset(str(path)) == {"gate": [], "recall": []}
    main([str(path)])
    output = capsys.readouterr().out
    assert "Precision=0.0000 Recall=0.0000 Accuracy=0.0000" in output
    assert "hit rate=0.0000 (0/0); complete scenarios=0/0" in output
    assert "Misclassified gate messages: 0" in output
    assert "Failed recall scenarios: 0" in output
