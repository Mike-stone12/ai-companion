"""The human-likeness judge: prompts, parsing, and order-swapped comparisons (fake judge)."""

import json

import pytest

from evals.humanlike.judge import compare, parse_json, render_transcript, score

TURNS = [
    {"user": ["在吗"], "reply": ["干嘛", "又有事求我？"]},
    {"user": ["我跟你说，", "今天被老板骂了"], "reply": []},
]


def test_transcript_has_one_line_per_message_and_marks_a_missing_reply():
    assert render_transcript(TURNS).splitlines() == [
        "用户：在吗", "她：干嘛", "她：又有事求我？", "用户：我跟你说，", "用户：今天被老板骂了", "她：（没有回复）",
    ]


def test_json_is_found_inside_a_code_fence():
    assert parse_json('```json\n{"winner": "A"}\n```') == {"winner": "A"}
    with pytest.raises(ValueError):
        parse_json("I think A is better")


def test_score_returns_the_rubric_and_an_overall_mean():
    seen = []

    def judge(messages):
        seen.append(messages)
        return json.dumps({
            "human": 8, "character": 7, "emotion": 6, "context": 9,
            "assistant_moments": ["又有事求我？"], "best_line": "干嘛", "comment": "还行",
        })

    result = score(judge, TURNS, persona="青梅竹马", focus="等她说完")

    assert result["overall"] == pytest.approx(7.5)
    assert result["assistant_moments"] == ["又有事求我？"]
    assert "青梅竹马" in seen[0][0]["content"] and "等她说完" in seen[0][0]["content"]
    assert seen[0][1]["content"] == render_transcript(TURNS)


@pytest.mark.parametrize("bad", [{"human": 11, "character": 5, "emotion": 5, "context": 5}, {"human": 5}])
def test_out_of_range_or_missing_scores_are_errors(bad):
    with pytest.raises(ValueError):
        score(lambda messages: json.dumps(bad), TURNS, persona="p", focus="f")


def scripted(*winners):
    replies = iter(winners)
    return lambda messages: json.dumps({"winner": next(replies), "reason": "r"})


def test_compare_runs_both_orders_and_maps_them_back():
    # First call shows (before, after) as (A, B); the second swaps them.
    assert compare(scripted("B", "A"), TURNS, TURNS, persona="p", focus="f")["result"] == "after"
    assert compare(scripted("A", "B"), TURNS, TURNS, persona="p", focus="f")["result"] == "before"


def test_a_split_decision_is_a_tie_and_one_tie_defers_to_the_other_vote():
    assert compare(scripted("A", "A"), TURNS, TURNS, persona="p", focus="f")["result"] == "tie"
    assert compare(scripted("tie", "A"), TURNS, TURNS, persona="p", focus="f")["result"] == "after"
