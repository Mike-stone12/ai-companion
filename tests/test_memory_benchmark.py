import json

import pytest

from eval.memory.benchmark import (
    GROUPS,
    Case,
    DatasetError,
    Fact,
    evaluate_gate,
    load_cases,
    load_results,
    render_report,
    score_extraction,
    simulate_store,
    summaries_from_rows,
    write_results,
)


def make_case(case_id, user="", expected=(), group="identity", lang="zh", scenario=None, turn=0, supersedes=False):
    return Case(
        id=case_id,
        group=group,
        lang=lang,
        user=user or f"{case_id}-text",
        assistant="",
        expected=tuple(expected),
        scenario=scenario,
        turn=turn,
        supersedes=supersedes,
    )


COFFEE = Fact("用户喜欢咖啡", ("咖啡",))
NAME = Fact("用户名叫小林", ("小林",))
HANGZHOU = Fact("用户住在杭州", ("杭州",))
SHANGHAI = Fact("用户住在上海", ("上海|浦东",))


# --- dataset ---


def test_shipped_dataset_is_well_formed():
    cases = load_cases()
    assert 60 <= len(cases) <= 120
    assert len({case.id for case in cases}) == len(cases)
    assert {case.group for case in cases} == set(GROUPS)
    assert sum(1 for case in cases if case.lang == "en") >= 8
    assert sum(1 for case in cases if not case.should_remember) >= 12
    assert all(case.should_remember for case in cases if case.group != "chitchat")
    assert len({case.scenario for case in cases if case.scenario}) >= 8
    assert any(case.supersedes for case in cases)


def test_fact_needs_every_key_and_accepts_alternatives():
    fact = Fact("x", ("咖啡|coffee", "喜欢"))
    assert fact.matches("用户喜欢喝咖啡")
    assert fact.matches("用户 喜欢 Coffee")
    assert not fact.matches("用户喜欢喝茶")
    assert not fact.matches("咖啡很贵")


def write_dataset(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return path


def valid_row(**overrides):
    row = {"id": "identity-01", "group": "identity", "user": "我叫小林"}
    row["expected"] = [{"fact": "名字", "keys": ["小林"]}]
    row.update(overrides)
    return row


def test_load_cases_reads_fields_and_defaults(tmp_path):
    rows = [valid_row(), valid_row(id="chitchat-01", group="chitchat", expected=[])]
    first, second = load_cases(write_dataset(tmp_path / "cases.jsonl", rows))
    assert first.lang == "zh" and first.assistant == "" and first.scenario is None and first.turn == 0
    assert first.expected == (Fact("名字", ("小林",)),)
    assert first.should_remember and not second.should_remember


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([valid_row(), valid_row()], "duplicate id"),
        ([valid_row(group="misc")], "unknown group"),
        ([valid_row(lang="fr")], "unknown lang"),
        ([valid_row(expected=None)], "'expected' must be a list"),
        ([valid_row(expected=[{"fact": "名字"}])], "keys"),
        ([valid_row(user="")], "'user' must be a non-empty string"),
        ([valid_row(supersedes=True)], "'supersedes' only makes sense inside a scenario"),
        ([valid_row(scenario="s", turn=2), valid_row(id="identity-02", scenario="s", turn=1)], "turns must be 1..n"),
    ],
)
def test_load_cases_rejects_malformed_rows(tmp_path, rows, message):
    path = write_dataset(tmp_path / "cases.jsonl", rows)
    with pytest.raises(DatasetError, match=message):
        load_cases(path)


def test_load_cases_reports_invalid_json_line(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps(valid_row()) + "\n{not json\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="cases.jsonl:2: invalid JSON"):
        load_cases(path)


# --- gate ---


def test_gate_metrics_separate_misses_from_false_alarms():
    cases = [
        make_case("hit", "我叫小林", [NAME]),
        make_case("miss", "我拿到 offer 了", [Fact("offer", ("offer",))]),
        make_case("alarm", "明天再说吧", []),
        make_case("reject", "哈哈好的", []),
    ]
    result = evaluate_gate(cases, lambda text: text in {"我叫小林", "明天再说吧"})
    assert result.hits == ["hit"]
    assert result.misses == ["miss"]
    assert result.false_alarms == ["alarm"]
    assert result.correct_rejects == ["reject"]
    assert result.recall == 0.5
    assert result.precision == 0.5
    assert result.decisions == {"hit": True, "miss": False, "alarm": True, "reject": False}


# --- extraction ---


def test_extraction_precision_and_recall():
    cases = [
        make_case("a", expected=[COFFEE, NAME]),
        make_case("b", expected=[], group="chitchat"),
        make_case("c", expected=[HANGZHOU]),
    ]
    extracted = {
        "a": ["用户喜欢咖啡", "用户爱喝咖啡", "用户今天很累"],
        "b": ["用户很累"],
        # "c" was rejected by the gate and never reached the extractor
    }
    score = score_extraction(cases, extracted)
    total = score.total
    assert (total.expected, total.recalled) == (3, 1)
    assert (total.extracted, total.correct, total.noise) == (4, 2, 2)
    assert total.precision == 0.5
    assert total.recall == pytest.approx(1 / 3)
    assert total.f1 == pytest.approx(0.4)
    assert score.chitchat_noise == 1

    by_group = score.by(lambda case: case.group)
    assert by_group["identity"].recalled == 1 and by_group["identity"].expected == 3
    assert by_group["chitchat"].extracted == 1 and by_group["chitchat"].expected == 0

    scored_a = score.cases[0]
    assert scored_a.recalled == (COFFEE,) and scored_a.missed == (NAME,)
    assert (scored_a.correct_items, scored_a.noise_items) == (2, 1)


def test_blank_summaries_are_ignored():
    score = score_extraction([make_case("a", expected=[NAME])], {"a": ["", "  "]})
    assert score.total.extracted == 0 and score.total.recall == 0


# --- store simulation ---


def test_store_counts_paraphrase_duplicates_and_stale_facts():
    cases = [
        make_case("d1", expected=[COFFEE], group="paraphrase", scenario="dup", turn=1),
        make_case("d2", expected=[COFFEE], group="paraphrase", scenario="dup", turn=2),
        make_case("d3", expected=[COFFEE], group="paraphrase", scenario="dup", turn=3),
        make_case("u1", expected=[HANGZHOU], group="conflict", scenario="upd", turn=1),
        make_case("u2", expected=[SHANGHAI], group="conflict", scenario="upd", turn=2, supersedes=True),
    ]
    extracted = {
        "d1": ["用户喜欢咖啡"],
        "d2": ["用户喜欢咖啡"],  # exact repeat: the store already collapses this one
        "d3": ["用户爱喝咖啡"],  # paraphrase: exact-text dedup keeps it
        "u1": ["用户住在杭州"],
        "u2": ["用户住在上海浦东"],
    }
    result = simulate_store(cases, extracted)
    by_name = {scenario.name: scenario for scenario in result.scenarios}
    assert sorted(by_name["dup"].stored) == ["用户喜欢咖啡", "用户爱喝咖啡"]
    assert by_name["dup"].duplicates == ["用户爱喝咖啡"]
    assert by_name["dup"].missing == [] and by_name["dup"].current == 1
    assert by_name["upd"].stale == ["用户住在杭州"]
    assert by_name["upd"].duplicates == [] and by_name["upd"].missing == []
    assert result.stored_total == 4
    assert result.duplicate_rate == 0.25
    assert result.stale_rate == 0.25
    assert result.missing_total == 0


def test_store_entry_carrying_old_and_new_fact_is_current_not_stale():
    old = Fact("男朋友阿凯", ("阿凯",))
    new = Fact("和阿凯分手", ("分手|单身",))
    cases = [
        make_case("r1", expected=[old], group="conflict", scenario="rel", turn=1),
        make_case("r2", expected=[new], group="conflict", scenario="rel", turn=2, supersedes=True),
    ]
    result = simulate_store(cases, {"r1": ["用户男朋友叫阿凯"], "r2": ["用户和阿凯分手了"]})
    scenario = result.scenarios[0]
    assert scenario.stale == ["用户男朋友叫阿凯"]
    assert scenario.duplicates == [] and scenario.missing == []


def test_store_reports_missing_current_facts_and_ignores_noise():
    cases = [
        make_case("m1", expected=[COFFEE], group="paraphrase", scenario="s", turn=1),
        make_case("m2", expected=[COFFEE], group="paraphrase", scenario="s", turn=2),
    ]
    result = simulate_store(cases, {"m1": ["用户今天很累"], "m2": []})
    scenario = result.scenarios[0]
    assert scenario.stored == ["用户今天很累"]
    assert scenario.missing == [COFFEE]
    assert scenario.duplicates == [] and scenario.stale == []


def test_store_without_scenarios_is_empty():
    result = simulate_store([make_case("a", expected=[NAME])], {"a": ["用户名叫小林"]})
    assert result.scenarios == [] and result.duplicate_rate == 0 and result.stored_total == 0


# --- results files and report ---


def test_results_round_trip(tmp_path):
    path = tmp_path / "run.jsonl"
    rows = [
        {"id": "a", "gate": True, "skipped": False, "memories": [{"summary": "用户名叫小林", "category": "identity"}]},
        {"id": "b", "gate": False, "skipped": True, "memories": []},
    ]
    write_results(path, {"extractor": "llm", "model": "m"}, rows)
    meta, loaded = load_results(path)
    assert meta == {"extractor": "llm", "model": "m"}
    assert loaded["a"]["memories"][0]["summary"] == "用户名叫小林"
    assert summaries_from_rows(loaded) == {"a": ["用户名叫小林"], "b": []}


def test_render_report_contains_every_section():
    cases = [
        make_case("a", "我叫小林", [NAME]),
        make_case("b", "哈哈好的", [], group="chitchat"),
        make_case("d1", "我喜欢咖啡", [COFFEE], group="paraphrase", scenario="dup", turn=1),
        make_case("d2", "我爱咖啡", [COFFEE], group="paraphrase", scenario="dup", turn=2),
    ]
    gate = evaluate_gate(cases, lambda text: text != "哈哈好的")
    extracted = {"a": ["用户名叫小林"], "d1": ["用户喜欢咖啡"], "d2": ["用户爱咖啡"]}
    pipeline = score_extraction(cases, extracted)
    store = simulate_store(cases, extracted)
    report = render_report(cases, gate, pipeline, None, store, {"extractor": "heuristic"})
    assert "# Memory benchmark: heuristic" in report
    assert "## Gate" in report and "## Pipeline" in report and "## Store" in report
    assert "| Precision (extracted summaries that match an expected fact) | 3/3 (100%) |" in report
    assert "| Recall (expected facts found in some summary) | 3/3 (100%) |" in report
    assert "| Duplicate rate (entries that repeat a fact already stored) | 1/2 (50%) |" in report
    assert "Extractor alone" not in report
    assert "every case was extracted exactly as expected" in report
