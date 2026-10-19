import json
import os
import subprocess
import sys

import pytest

from companion.core import settings_schema
from companion.core.settings_values import SETTING_NAMES
from companion.settings_cli import main


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in SETTING_NAMES | {"COMPANION_DATA_DIR"}:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(
        b'{ "window": {"x": 12, "opacity": 0.7}, "custom": [1], '
        b'"settings": {"MEMORY_LIMIT": 30, "CHAT_TOOLS": true, "custom": {"keep": 1}} }\n'
    )
    return path


@pytest.fixture
def run_readonly(tmp_path):
    def run(args):
        tree = set(tmp_path.rglob("*"))
        files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tree if path.is_file()}
        try:
            return main(args)
        finally:
            assert set(tmp_path.rglob("*")) == tree
            for path, original in files.items():
                assert (path.read_bytes(), path.stat().st_mtime_ns) == original

    return run


def test_list(config, monkeypatch, capsys, run_readonly):
    monkeypatch.setenv("CHAT_TOOLS", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "never-display-this")
    assert run_readonly(["--data-dir", str(config.parent), "list"]) == 0
    output = capsys.readouterr()
    lines = output.out.splitlines()
    assert [line.split(" = ")[0] for line in lines] == [entry.name for entry in settings_schema.EDITABLE_SETTINGS]
    assert 'MEMORY_LIMIT = "30" (source: config.json)' in lines
    assert 'CHAT_TOOLS = "false" (source: environment)' in lines
    assert 'LOG_LEVEL = "INFO" (source: default)' in lines
    assert "never-display-this" not in output.out
    assert "OPENAI_API_KEY" not in output.out
    assert output.err == ""


@pytest.mark.parametrize(("key", "details"), [
    ("LOG_LEVEL", ['LOG_LEVEL = "INFO" (source: default)', "Description: Log level", "Type: choice",
                   "Allowed values: DEBUG, INFO, WARNING, ERROR"]),
    ("MEMORY_LIMIT", ['MEMORY_LIMIT = "30" (source: config.json)', "Type: int", "Minimum: 1"]),
    ("CHAT_TOOLS", ['CHAT_TOOLS = "1" (source: config.json)', "Type: bool", "Allowed values: true, false"]),
])
def test_show(config, key, details, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(config.parent), "show", key]) == 0
    output = capsys.readouterr()
    for detail in details:
        assert detail in output.out
    assert output.err == ""


def test_set_dry_run(config, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(config.parent), "set", "MEMORY_LIMIT", "42"]) == 0
    output = capsys.readouterr()
    assert "Old config.json value: 30" in output.out
    assert "New config.json value: 42" in output.out
    assert "Dry run" in output.out
    assert "--write" in output.out
    assert output.err == ""


@pytest.mark.parametrize(("key", "value", "expected"), [
    ("MEMORY_LIMIT", "42", 42),
    ("CHAT_TOOLS", "false", False),
    ("LOG_LEVEL", " debug ", "DEBUG"),
    ("EDGE_TTS_VOICE_ZH", "自定义语音", "自定义语音"),
    ("EMBEDDING_MODEL", " model ", "model"),
])
def test_set_write_uses_schema_writer_and_preserves_other_keys(config, key, value, expected, monkeypatch, capsys):
    original = json.loads(config.read_text(encoding="utf-8"))
    save = settings_schema.save_settings
    calls = []

    def checked_save(path, updates):
        calls.append((path, updates))
        save(path, updates)

    monkeypatch.setattr(settings_schema, "save_settings", checked_save)
    assert main(["--data-dir", str(config.parent), "set", key, value, "--write"]) == 0
    assert calls == [(config, {key: expected})]
    assert json.loads(config.read_text(encoding="utf-8")) == {
        **original, "settings": {**original["settings"], key: expected},
    }
    assert list(config.parent.iterdir()) == [config]
    assert "Saved" in capsys.readouterr().out


@pytest.mark.parametrize("write", [[], ["--write"]])
def test_environment_override_note(config, monkeypatch, write, capsys):
    monkeypatch.setenv("MEMORY_LIMIT", "99")
    assert main(["--data-dir", str(config.parent), "set", "MEMORY_LIMIT", "42", *write]) == 0
    output = capsys.readouterr().out
    assert "Old config.json value: 30" in output
    assert "New config.json value: 42" in output
    assert "environment variable MEMORY_LIMIT overrides this setting" in output
    assert main(["--data-dir", str(config.parent), "show", "MEMORY_LIMIT"]) == 0
    assert 'MEMORY_LIMIT = "99" (source: environment)' in capsys.readouterr().out


@pytest.mark.parametrize("key", [
    "UNKNOWN", "OPENAI_API_KEY", "api_key", "MY_SECRET", "ACCESS_TOKEN", "PASSWORD",
    "COMPANION_DATA_DIR", "OPENAI_BASE_URL", "PYTHONPATH",
])
@pytest.mark.parametrize("command", [["show"], ["set"], ["set", "--write"]])
def test_uneditable_keys_rejected(config, key, command, capsys, run_readonly):
    args = [*command, key]
    if command[0] == "set":
        args.append("never-display-this")
    assert run_readonly(["--data-dir", str(config.parent), *args]) != 0
    output = capsys.readouterr()
    assert "not editable" in output.err
    assert "never-display-this" not in output.out + output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize(("key", "value"), [
    ("MEMORY_LIMIT", "0"), ("MEMORY_LIMIT", "-1"), ("MEMORY_LIMIT", "1.5"),
    ("MEMORY_LIMIT", "true"), ("MEMORY_LIMIT", "oops"), ("MEMORY_LIMIT", "null"),
    ("CHAT_TOOLS", "yes"), ("CHAT_TOOLS", "1"), ("CHAT_TOOLS", "[]"),
    ("LOG_LEVEL", "TRACE"),
])
@pytest.mark.parametrize("write", [[], ["--write"]])
def test_invalid_values_rejected(config, key, value, write, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(config.parent), "set", key, value, *write]) != 0
    output = capsys.readouterr()
    assert "Error:" in output.err
    assert key in output.err
    assert output.out == ""
    assert "Traceback" not in output.err


def test_missing_file(tmp_path, capsys, run_readonly):
    data_dir = tmp_path / "new"
    args = ["--data-dir", str(data_dir)]
    assert run_readonly([*args, "list"]) == 0
    assert 'MEMORY_LIMIT = "24" (source: default)' in capsys.readouterr().out
    assert run_readonly([*args, "set", "MEMORY_LIMIT", "42"]) == 0
    assert "Old config.json value: <not set>" in capsys.readouterr().out
    assert main([*args, "set", "MEMORY_LIMIT", "42", "--write"]) == 0
    assert json.loads((data_dir / "config.json").read_text(encoding="utf-8")) == {"settings": {"MEMORY_LIMIT": 42}}


def test_data_directory_resolution(config, monkeypatch, capsys, run_readonly):
    from companion import paths

    monkeypatch.setenv("COMPANION_DATA_DIR", str(config.parent))
    assert run_readonly(["show", "MEMORY_LIMIT"]) == 0
    assert '"30" (source: config.json)' in capsys.readouterr().out
    assert run_readonly(["--data-dir", str(config.parent / "other"), "show", "MEMORY_LIMIT"]) == 0
    assert '"24" (source: default)' in capsys.readouterr().out
    monkeypatch.delenv("COMPANION_DATA_DIR")
    monkeypatch.setattr(paths, "user_data_dir", lambda: config.parent)
    assert run_readonly(["show", "MEMORY_LIMIT"]) == 0
    assert '"30" (source: config.json)' in capsys.readouterr().out


@pytest.mark.parametrize("section", [None, [], "invalid"])
@pytest.mark.parametrize("write", [[], ["--write"]])
def test_non_object_settings_rejected(config, section, write, capsys, run_readonly):
    config.write_text(json.dumps({"settings": section, "window": {"x": 12}}), encoding="utf-8")
    assert run_readonly(["--data-dir", str(config.parent), "set", "CHAT_TOOLS", "true", *write]) != 0
    assert "Existing settings must be an object" in capsys.readouterr().err


def test_non_scalar_config_value_uses_default(config, capsys, run_readonly):
    config.write_text(json.dumps({"settings": {"MEMORY_LIMIT": []}}), encoding="utf-8")
    assert run_readonly(["--data-dir", str(config.parent), "show", "MEMORY_LIMIT"]) == 0
    assert '"24" (source: default)' in capsys.readouterr().out


def test_write_error(config, monkeypatch, capsys, run_readonly):
    def denied(path, updates):
        raise PermissionError("access denied")

    monkeypatch.setattr(settings_schema, "save_settings", denied)
    assert run_readonly(["--data-dir", str(config.parent), "set", "CHAT_TOOLS", "true", "--write"]) != 0
    output = capsys.readouterr()
    assert "access denied" in output.err
    assert "Saved" not in output.out
    assert "Traceback" not in output.err


def test_module_entry_point_without_gui(config):
    before = (config.read_bytes(), config.stat().st_mtime_ns)
    # Fail even if GUI dependencies happen to be installed on the test machine.
    script = """
import runpy
import sys
sys.modules['PyQt6'] = None
sys.modules['edge_tts'] = None
runpy.run_module('companion.settings_cli', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, "--data-dir", str(config.parent), "set",
         "EDGE_TTS_VOICE_ZH", "自定义语音"],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "自定义语音" in result.stdout.decode("utf-8")
    assert result.stderr == b""
    assert (config.read_bytes(), config.stat().st_mtime_ns) == before
