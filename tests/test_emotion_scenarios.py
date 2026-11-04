"""The scripted emotion scenarios in evals/ must all behave as designed."""

import json

from companion.core.state.scenarios import DEFAULT_PATH, format_outcomes, main, run_all


def test_every_scenario_passes_for_every_personality():
    outcomes = run_all(json.loads(DEFAULT_PATH.read_text(encoding="utf-8")))

    assert outcomes, "no scenarios found"
    assert all(not outcome.failed for outcome in outcomes), format_outcomes(outcomes)


def test_scenarios_cover_the_design():
    data = json.loads(DEFAULT_PATH.read_text(encoding="utf-8"))
    names = " ".join(scenario["name"] for scenario in data["scenarios"])

    for topic in ("jealousy", "apology", "sorry", "good day", "alone", "upset", "fades", "capped", "tsundere"):
        assert topic in names
    assert set(data["presets"]) == {"childhood_friend", "secure_and_candid", "touchy"}


def test_cli_reports_and_exits_zero(capsys):
    assert main([]) == 0
    assert "checks passed" in capsys.readouterr().out
