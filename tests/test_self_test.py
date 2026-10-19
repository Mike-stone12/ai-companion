"""The offline self-test entry point, without Qt (the GUI half is injected)."""

import ast
import sys
import types
from pathlib import Path

import pytest

from companion import self_test
from companion.self_test import FLAG, Check, format_report, passed, prepare

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _temp_dirs_under_tmp_path(monkeypatch, tmp_path):
    monkeypatch.setattr(self_test.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / f"{prefix}x"))
    (tmp_path / "ai-companion-selftest-x").mkdir()


def test_prepare_ignores_normal_starts():
    environ = {}

    assert prepare(["main.py"], environ) is None
    assert environ == {}


def test_prepare_uses_a_throwaway_data_dir_and_disables_the_keychain():
    environ = {"COMPANION_DATA_DIR": "/real/user/data"}

    request = prepare(["main.py", FLAG], environ)

    assert request.report_path is None
    assert request.data_dir.is_dir()
    assert environ["COMPANION_DATA_DIR"] == str(request.data_dir)
    assert environ["COMPANION_KEYCHAIN"] == "0"
    assert "selftest" in request.data_dir.name


def test_prepare_reads_an_optional_report_path(tmp_path):
    report = tmp_path / "report.txt"

    assert prepare(["main.py", FLAG, str(report)], {}).report_path == report
    assert prepare(["main.py", FLAG, "--other"], {}).report_path is None


def test_optional_failures_do_not_fail_the_run():
    checks = [Check("a", True), Check("b", False, "missing", required=False)]

    assert passed(checks)
    assert "WARN  b: missing" in format_report(checks)
    assert format_report(checks).endswith("Self-test passed")


def test_required_failures_fail_the_run():
    checks = [Check("a", True, "fine"), Check("b", False, "boom")]

    assert not passed(checks)
    report = format_report(checks)
    assert "PASS  a: fine" in report
    assert "FAIL  b: boom" in report
    assert report.endswith("failed (1 required check(s))")


def fake_keyring(monkeypatch, priority):
    module = types.SimpleNamespace(get_keyring=lambda: type("Backend", (), {"priority": priority})())
    monkeypatch.setitem(sys.modules, "keyring", module)


@pytest.mark.parametrize(("platform", "required"), [("darwin", True), ("win32", True), ("linux", False)])
def test_static_checks_cover_resources_and_mark_linux_keychain_optional(monkeypatch, tmp_path, platform, required):
    from companion import paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    fake_keyring(monkeypatch, 5)
    monkeypatch.setitem(sys.modules, "edge_tts", types.ModuleType("edge_tts"))
    checks = {check.name: check for check in self_test.static_checks(platform)}

    for name in ("bundled resources", "Live2D model", "renderer vendor files", "user data directory",
                 "default persona", "keyring package", "text-to-speech package"):
        assert checks[name].ok, checks[name]
    assert checks["keychain backend"].required is required


def test_fail_backend_is_reported(monkeypatch, tmp_path):
    from companion import paths

    monkeypatch.setattr(paths, "DATA_DIR", tmp_path)
    fake_keyring(monkeypatch, 0)

    check = next(check for check in self_test.static_checks("darwin") if check.name == "keychain backend")

    assert not check.ok
    assert "no usable backend" in check.detail


def test_run_writes_the_report_and_returns_the_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(self_test, "static_checks", lambda: [Check("static", True)])
    request = self_test.SelfTestRequest(tmp_path / "data", tmp_path / "report.txt")

    assert self_test.run(request, gui=lambda: [Check("window", True)]) == 0
    assert "PASS  window" in (tmp_path / "report.txt").read_text(encoding="utf-8")
    assert "Self-test passed" in capsys.readouterr().out

    assert self_test.run(request, gui=lambda: [Check("window", False, "no model")]) == 1
    assert "FAIL  window: no model" in (tmp_path / "report.txt").read_text(encoding="utf-8")


def test_run_removes_its_throwaway_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(self_test, "static_checks", lambda: [])
    data_dir = tmp_path / "data"
    (data_dir / "logs").mkdir(parents=True)

    self_test.run(self_test.SelfTestRequest(data_dir, None), gui=lambda: [])

    assert not data_dir.exists()


def test_main_prepares_the_self_test_before_other_companion_imports():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    statements = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign))]
    prepare_index = next(
        index for index, node in enumerate(statements)
        if isinstance(node, ast.Assign) and "prepare" in ast.unparse(node.value)
    )
    later_companion_imports = [
        node for node in statements[:prepare_index]
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("companion.")
    ]
    assert later_companion_imports == []


def test_run_reports_a_crashing_window_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(self_test, "static_checks", lambda: [])
    request = self_test.SelfTestRequest(tmp_path / "data", tmp_path / "report.txt")

    def boom():
        raise RuntimeError("no display")

    assert self_test.run(request, gui=boom) == 1
    assert "FAIL  main window: RuntimeError: no display" in (tmp_path / "report.txt").read_text(encoding="utf-8")
