import json
from copy import deepcopy

import pytest

from companion.core.memory.extraction_eval import (
    DEFAULT_DATASET_PATH,
    evaluate_extraction,
    format_report,
    load_dataset,
    main,
)


def perfect_extractor(cases):
    summaries = {
        (case["user_message"], case.get("assistant_reply", "")): list(case["expected_keywords"])
        for case in cases
    }
    return lambda user, assistant: summaries[(user, assistant)]


def test_dataset_loads_and_has_required_fields():
    cases = load_dataset(DEFAULT_DATASET_PATH)
    assert 15 <= len(cases) <= 25
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["should_store"] for case in cases} == {True, False}
    for case in cases:
        assert isinstance(case["id"], str) and case["id"].strip()
        assert isinstance(case["user_message"], str) and case["user_message"].strip()
        assert any("\u4e00" <= char <= "\u9fff" for char in case["user_message"])
        assert type(case["should_store"]) is bool
        assert isinstance(case.get("assistant_reply", ""), str)
        assert isinstance(case["expected_keywords"], list)
        assert all(isinstance(word, str) and word.strip() for word in case["expected_keywords"])
        assert bool(case["expected_keywords"]) == case["should_store"]


def test_perfect_fake():
    cases = load_dataset()
    before = deepcopy(cases)
    result = evaluate_extraction(cases, perfect_extractor(cases))
    assert result["accuracy"] == result["keyword_hit_rate"] == 1.0
    assert result["false_store_count"] == result["missed_store_count"] == result["error_count"] == 0
    assert result["keyword_hits"] == result["positive_count"] == sum(case["should_store"] for case in cases)
    assert len(result["results"]) == result["case_count"] == len(cases)
    assert all(case["decision_correct"] and case["error"] is None for case in result["results"])
    assert cases == before


def test_store_everything_fake():
    cases = load_dataset()
    result = evaluate_extraction(cases, lambda user, assistant: [user])
    positives = sum(case["should_store"] for case in cases)
    assert result["false_store_count"] == len(cases) - positives
    assert result["missed_store_count"] == 0
    assert result["accuracy"] == pytest.approx(positives / len(cases))
    assert all(case["predicted"] for case in result["results"])


def test_store_nothing_fake():
    cases = load_dataset()
    result = evaluate_extraction(cases, lambda user, assistant: [])
    positives = sum(case["should_store"] for case in cases)
    assert result["missed_store_count"] == positives
    assert result["false_store_count"] == 0
    assert result["keyword_hit_rate"] == 0.0
    assert result["accuracy"] == pytest.approx((len(cases) - positives) / len(cases))


@pytest.mark.parametrize("positive_error", [True, False])
def test_exception_is_recorded_and_remaining_cases_are_scored(positive_error):
    cases = load_dataset()
    failing = next(case for case in cases if case["should_store"] == positive_error)
    perfect = perfect_extractor(cases)
    calls = []

    def extract(user, assistant):
        calls.append((user, assistant))
        if user == failing["user_message"]:
            raise RuntimeError("fake failure")
        return perfect(user, assistant)

    result = evaluate_extraction(cases, extract)
    assert len(calls) == len(result["results"]) == len(cases)
    assert result["error_count"] == 1
    assert result["accuracy"] == pytest.approx((len(cases) - 1) / len(cases))
    assert result["keyword_hit_rate"] == pytest.approx(
        (result["positive_count"] - positive_error) / result["positive_count"]
    )
    assert result["false_store_count"] == result["missed_store_count"] == 0
    for case in result["results"]:
        if case["id"] == failing["id"]:
            assert case["error"] == "RuntimeError: fake failure"
            assert case["predicted"] is None
            assert not case["decision_correct"]
        else:
            assert case["error"] is None and case["decision_correct"]
    assert f"{failing['id']}: ERROR RuntimeError: fake failure" in format_report(result)


def test_keywords_require_every_substring_but_can_span_summaries():
    cases = [{
        "id": "pet", "user_message": "我的猫叫芝麻。", "should_store": True,
        "expected_keywords": ["猫", "芝麻"],
    }]
    partial = evaluate_extraction(cases, lambda user, assistant: ["养了一只猫"])
    assert partial["accuracy"] == 1.0
    assert partial["keyword_hit_rate"] == 0.0
    assert partial["results"][0]["missing_keywords"] == ["芝麻"]
    complete = evaluate_extraction(cases, lambda user, assistant: ["养猫", "名字是芝麻"])
    assert complete["keyword_hit_rate"] == 1.0
    report = format_report(partial)
    for label in ("accuracy=1.0000", "False stores=0", "Missed stores=0", "Keyword hit rate=0.0000", "Errors=0"):
        assert label in report
    assert "pet:" in report and "芝麻" in report


@pytest.mark.parametrize("cases", [[], [
    {"id": "hello", "user_message": "你好", "should_store": False, "expected_keywords": []},
]])
def test_zero_denominators(cases):
    result = evaluate_extraction(cases, lambda user, assistant: [])
    assert result["keyword_hit_rate"] == 0.0
    assert result["accuracy"] == (1.0 if cases else 0.0)
    assert result["error_count"] == 0


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", 1), ("user_message", " "), ("user_message", None),
    ("should_store", 1), ("should_store", "true"), ("assistant_reply", None),
    ("expected_keywords", []), ("expected_keywords", "关键词"),
    ("expected_keywords", [""]), ("expected_keywords", [1]),
])
def test_loader_rejects_invalid_fields(tmp_path, field, value):
    case = {**load_dataset()[0], field: value}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        load_dataset(path)


@pytest.mark.parametrize("dataset", [[], {}, {"cases": {}}, {"cases": [None]}, {"cases": [{}]}])
def test_loader_rejects_invalid_structure(tmp_path, dataset):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")
    with pytest.raises(ValueError):
        load_dataset(path)


def test_loader_rejects_duplicate_ids(tmp_path):
    case = load_dataset()[0]
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [case, case]}), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(str(path))


@pytest.mark.parametrize("explicit_argv", [False, True])
def test_main_without_args_never_constructs_client(explicit_argv, monkeypatch, capsys):
    from companion.core.llm import client

    def fail_if_called(*args, **kwargs):
        pytest.fail("Offline invocation must not construct an LLM client")

    monkeypatch.setattr(client, "OpenAICompatibleClient", fail_if_called)
    monkeypatch.setattr("sys.argv", ["extraction_eval"])
    assert main([] if explicit_argv else None) is None
    output = capsys.readouterr().out
    assert "usage:" in output
    assert "--live" in output
    assert "API key" in output
