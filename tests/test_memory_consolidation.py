import json
from dataclasses import FrozenInstanceError

import pytest

from companion.core.memory.consolidator import (
    ConsolidationDecision,
    apply_decision,
    build_consolidation_messages,
    parse_consolidation_response,
)


def test_decision_is_frozen():
    decision = ConsolidationDecision("ADD", None, "喜欢吃鱼")
    with pytest.raises(FrozenInstanceError):
        decision.summary = "喜欢吃肉"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"action": "ADD", "summary": " I enjoy hiking. "}, ConsolidationDecision("ADD", None, "I enjoy hiking.")),
        ({"action": "ADD", "target": None, "summary": "喜欢吃鱼"}, ConsolidationDecision("ADD", None, "喜欢吃鱼")),
        (
            {"action": "UPDATE", "target": 0, "summary": " 喜欢吃鱼，尤其是清蒸鱼 \n"},
            ConsolidationDecision("UPDATE", 0, "喜欢吃鱼，尤其是清蒸鱼"),
        ),
        (
            {"action": "UPDATE", "target": 1, "summary": "用户已从北京搬到上海"},
            ConsolidationDecision("UPDATE", 1, "用户已从北京搬到上海"),
        ),
        ({"action": "DELETE", "target": 0}, ConsolidationDecision("DELETE", 0, None)),
        ({"action": "DELETE", "target": 1, "summary": None}, ConsolidationDecision("DELETE", 1, None)),
        ({"action": "NOOP"}, ConsolidationDecision("NOOP", None, None)),
        (
            {"action": "NOOP", "target": "ignored", "summary": ["喜欢吃鱼"]},
            ConsolidationDecision("NOOP", None, None),
        ),
    ],
)
def test_parse_valid_actions(payload, expected):
    assert parse_consolidation_response(json.dumps(payload, ensure_ascii=False), 2) == expected


@pytest.mark.parametrize("action", ["add", "uPdAtE", "delete", "noop"])
@pytest.mark.parametrize("wrapper", [" \n{}\t ", " \n```json\n{}\n``` \t", "```\n{}\n```"])
def test_case_insensitive_actions_and_fences(action, wrapper):
    payload = {"action": action, "summary": "喜欢吃鱼"}
    if action.upper() in {"UPDATE", "DELETE"}:
        payload["target"] = 0
    decision = parse_consolidation_response(wrapper.format(json.dumps(payload)), 1)
    assert decision is not None
    assert decision.action == action.upper()


@pytest.mark.parametrize("raw", ["", "not JSON", "{", "{} trailing", "[]", "null", '"ADD"', "42", "true"])
def test_invalid_json_or_non_object(raw):
    assert parse_consolidation_response(raw, 2) is None


@pytest.mark.parametrize("action", [None, "MERGE", "", 1, True, [], {}])
def test_invalid_action(action):
    assert parse_consolidation_response(json.dumps({"action": action, "summary": "喜欢吃鱼"}), 2) is None


def test_missing_action():
    assert parse_consolidation_response('{"summary": "喜欢吃鱼"}', 2) is None


@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
@pytest.mark.parametrize("target", [None, -1, 2, 100, 0.0, 1.5, "0", True, False, [], {}])
def test_invalid_target(action, target):
    payload = {"action": action, "target": target, "summary": "用户搬到上海"}
    assert parse_consolidation_response(json.dumps(payload), 2) is None


@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_missing_target_and_empty_existing(action):
    payload = {"action": action, "summary": "用户搬到上海"}
    assert parse_consolidation_response(json.dumps(payload), 2) is None
    payload["target"] = 0
    assert parse_consolidation_response(json.dumps(payload), 0) is None


@pytest.mark.parametrize("action", ["ADD", "UPDATE"])
@pytest.mark.parametrize("summary", [None, "", " \t\n", 123, True, [], {}])
def test_invalid_summary(action, summary):
    payload = {"action": action, "target": 0 if action == "UPDATE" else None, "summary": summary}
    assert parse_consolidation_response(json.dumps(payload), 2) is None


@pytest.mark.parametrize("action", ["ADD", "UPDATE"])
def test_missing_summary(action):
    payload = {"action": action, "target": 0 if action == "UPDATE" else None}
    assert parse_consolidation_response(json.dumps(payload), 2) is None


@pytest.mark.parametrize("target", [0, 1, False, "0", [], {}])
def test_add_rejects_target(target):
    payload = {"action": "ADD", "target": target, "summary": "喜欢吃鱼"}
    assert parse_consolidation_response(json.dumps(payload), 2) is None


def test_prompt_contains_indexed_memories_and_candidate():
    existing = ["喜欢吃鱼", "用户住在北京", "I enjoy hiking."]
    candidate = "我搬到上海了"
    messages = build_consolidation_messages(candidate, existing)
    assert [message["role"] for message in messages] == ["system", "user"]
    for action in ("ADD", "UPDATE", "DELETE", "NOOP"):
        assert action in messages[0]["content"]
    payload = json.loads(messages[1]["content"])
    assert payload == {
        "candidate": candidate,
        "existing": [{"index": index, "summary": summary} for index, summary in enumerate(existing)],
    }
    assert candidate in messages[1]["content"]
    assert "喜欢吃鱼" in messages[1]["content"]
    assert existing == ["喜欢吃鱼", "用户住在北京", "I enjoy hiking."]


def test_prompt_with_no_existing_memories():
    payload = json.loads(build_consolidation_messages("喜欢吃鱼", [])[1]["content"])
    assert payload == {"candidate": "喜欢吃鱼", "existing": []}


@pytest.mark.parametrize(
    ("candidate", "decision", "expected"),
    [
        ("I enjoy hiking.", None, ["喜欢吃鱼", "用户住在北京", "I enjoy hiking."]),
        ("喜欢吃鱼", None, ["喜欢吃鱼", "用户住在北京"]),
        ("爱吃鱼", None, ["喜欢吃鱼", "用户住在北京", "爱吃鱼"]),
        (
            "我喜欢远足",
            ConsolidationDecision("ADD", None, "I enjoy hiking."),
            ["喜欢吃鱼", "用户住在北京", "I enjoy hiking."],
        ),
        (
            "爱吃清蒸鱼",
            ConsolidationDecision("UPDATE", 0, "喜欢吃鱼，尤其是清蒸鱼"),
            ["喜欢吃鱼，尤其是清蒸鱼", "用户住在北京"],
        ),
        (
            "我从北京搬到上海了",
            ConsolidationDecision("UPDATE", 1, "用户住在上海"),
            ["喜欢吃鱼", "用户住在上海"],
        ),
        ("我不再喜欢吃鱼了", ConsolidationDecision("DELETE", 0, None), ["喜欢吃鱼", "用户住在北京"]),
        ("我爱吃鱼", ConsolidationDecision("NOOP", None, None), ["喜欢吃鱼", "用户住在北京"]),
    ],
)
def test_apply_returns_new_list_without_mutating_input(candidate, decision, expected):
    existing = ["喜欢吃鱼", "用户住在北京"]
    result = apply_decision(existing, candidate, decision)
    assert result == expected
    assert result is not existing
    assert existing == ["喜欢吃鱼", "用户住在北京"]


def test_apply_to_empty_list():
    assert apply_decision([], "喜欢吃鱼", None) == ["喜欢吃鱼"]
    assert apply_decision([], "喜欢吃鱼", ConsolidationDecision("ADD", None, "爱吃鱼")) == ["爱吃鱼"]
