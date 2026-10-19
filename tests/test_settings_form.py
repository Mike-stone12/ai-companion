import json
import os
from pathlib import Path

import pytest

from companion.core import settings_file, settings_schema
from companion.core.settings_form import SettingsForm
from companion.core.settings_values import SECRET_MARKERS


def fields_by_key(form):
    return {field.key: field for field in form.fields}


def test_fields_follow_editable_schema_and_exclude_secrets(tmp_path):
    environment = {"OPENAI_API_KEY": "private", "COMPANION_DATA_DIR": "ignored"}
    form = SettingsForm(tmp_path / "config.json", environment)
    assert [field.key for field in form.fields] == [entry.name for entry in settings_schema.EDITABLE_SETTINGS]
    for field, entry in zip(form.fields, settings_schema.EDITABLE_SETTINGS, strict=True):
        assert not any(marker in field.key for marker in SECRET_MARKERS)
        assert field.key != "COMPANION_DATA_DIR"
        assert field.kind == entry.kind
        assert field.choices == entry.choices
        assert field.minimum == entry.minimum
        assert field.maximum == entry.maximum
        assert field.description == entry.label
        assert isinstance(field.value, str)
        assert field.source == "default"
        assert not field.env_overridden
    fields = fields_by_key(form)
    assert fields["CHAT_TOOLS"].value == "0"
    assert fields["VOICE_INPUT"].value == "0"
    assert fields["VOICE_INPUT"].kind == "bool"
    assert fields["TRANSCRIPTION_MODEL"].value == ""
    assert fields["TRANSCRIPTION_MODEL"].kind == "str"
    assert fields["MEMORY_LIMIT"].value == "24"
    assert fields["MEMORY_LIMIT"].minimum == 1
    assert fields["LOG_LEVEL"].choices == ("DEBUG", "INFO", "WARNING", "ERROR")


def test_sources_and_environment_overrides(tmp_path):
    path = tmp_path / "config.json"
    stored = {"MEMORY_LIMIT": 42, "CHAT_TOOLS": True, "LOG_LEVEL": "DEBUG", "LIVE2D_MODEL": []}
    path.write_text(json.dumps({"settings": stored}), encoding="utf-8")
    environment = {"MEMORY_LIMIT": "17", "LOG_LEVEL": "", "EMBEDDING_MODEL": "env-model"}
    form = SettingsForm(path, environment)
    fields = fields_by_key(form)
    for key, value in environment.items():
        assert fields[key].value == value
        assert fields[key].source == "environment"
        assert fields[key].env_overridden
    assert fields["CHAT_TOOLS"].value == "1"
    assert fields["CHAT_TOOLS"].source == "config.json"
    assert not fields["CHAT_TOOLS"].env_overridden
    assert fields["LIVE2D_MODEL"].source == "default"
    assert fields["PROACTIVE_CHAT"].source == "default"
    assert not fields["PROACTIVE_CHAT"].env_overridden
    assert environment == {"MEMORY_LIMIT": "17", "LOG_LEVEL": "", "EMBEDDING_MODEL": "env-model"}


def test_only_none_defaults_to_process_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", {"MEMORY_LIMIT": "77"})
    path = tmp_path / "config.json"
    assert fields_by_key(SettingsForm(path))["MEMORY_LIMIT"].value == "77"
    assert fields_by_key(SettingsForm(path, {}))["MEMORY_LIMIT"].value == "24"


@pytest.mark.parametrize("key, raw, expected", [
    ("CHAT_TOOLS", "true", True),
    ("VOICE_INPUT", "true", True),
    ("VOICE_INPUT", "false", False),
    ("TRANSCRIPTION_MODEL", " transcription-model ", "transcription-model"),
    ("TRANSCRIPTION_MODEL", "  ", ""),
    ("CHAT_TOOLS", False, False),
    ("MEMORY_LIMIT", "42", 42),
    ("MEMORY_LIMIT", 12, 12),
    ("LOG_LEVEL", " debug ", "DEBUG"),
    ("EMBEDDING_MODEL", " model ", "model"),
    ("EDGE_TTS_VOICE_EN", " voice ", " voice "),
])
def test_valid_edits_are_normalized_and_staged(tmp_path, key, raw, expected):
    path = tmp_path / "config.json"
    form = SettingsForm(path, {})
    assert form.set_value(key, raw)
    assert form.pending_changes() == {key: (None, expected)}
    assert type(form.pending_changes()[key][1]) is type(expected)
    assert not form.has_errors()
    assert not path.exists()


@pytest.mark.parametrize("key, raw", [
    ("CHAT_TOOLS", "yes"), ("CHAT_TOOLS", "1"), ("MEMORY_LIMIT", "0"),
    ("MEMORY_LIMIT", "1.5"), ("MEMORY_LIMIT", True), ("LOG_LEVEL", "TRACE"),
    ("UNKNOWN", "value"), ("OPENAI_API_KEY", "private-value"),
    ("COMPANION_DATA_DIR", "path"), ("OPENAI_BASE_URL", "url"),
])
def test_invalid_edits_are_errors_and_not_staged(tmp_path, key, raw):
    form = SettingsForm(tmp_path / "config.json", {})
    assert not form.set_value(key, raw)
    assert form.has_errors()
    assert form.errors[key]
    assert "private-value" not in form.errors[key]
    assert form.pending_changes() == {}


def test_invalid_edit_clears_stale_pending_and_valid_edit_clears_error(tmp_path):
    form = SettingsForm(tmp_path / "config.json", {})
    assert form.set_value("MEMORY_LIMIT", "42")
    assert not form.set_value("MEMORY_LIMIT", "0")
    assert form.pending_changes() == {}
    assert form.set_value("MEMORY_LIMIT", "12")
    assert form.errors == {}
    assert not form.has_errors()
    assert form.pending_changes() == {"MEMORY_LIMIT": (None, 12)}


def test_pending_diff_uses_stored_values_and_revert_is_noop(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"settings": {"MEMORY_LIMIT": 42}}', encoding="utf-8")
    form = SettingsForm(path, {"MEMORY_LIMIT": "17"})
    form.set_value("MEMORY_LIMIT", "12")
    assert form.pending_changes() == {"MEMORY_LIMIT": (42, 12)}
    assert fields_by_key(form)["MEMORY_LIMIT"].value == "17"
    form.set_value("MEMORY_LIMIT", "42")
    assert form.pending_changes() == {}


def test_reset_discards_pending_and_errors(tmp_path):
    path = tmp_path / "config.json"
    form = SettingsForm(path, {})
    original = form.fields
    form.set_value("MEMORY_LIMIT", "42")
    form.set_value("CHAT_TOOLS", "invalid")
    form.reset()
    assert form.pending_changes() == {}
    assert form.errors == {}
    assert not form.has_errors()
    assert form.fields == original
    assert not path.exists()


def test_apply_merges_latest_file_atomically_and_refreshes(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    original = {"window": {"x": 12, "opacity": 0.7}, "extra": [1],
                "settings": {"UNKNOWN": {"nested": True}, "MEMORY_LIMIT": 24, "CHAT_TOOLS": True}}
    path.write_text(json.dumps(original), encoding="utf-8")
    form = SettingsForm(path, {"MEMORY_LIMIT": "17"})
    form.set_value("MEMORY_LIMIT", "42")
    form.set_value("LOG_LEVEL", " debug ")
    # A different writer may update unrelated values while the form is open.
    original["window"]["x"] = 99
    path.write_text(json.dumps(original), encoding="utf-8")
    expected = {**original, "settings": {**original["settings"], "MEMORY_LIMIT": 42, "LOG_LEVEL": "DEBUG"}}
    replace = settings_file.os.replace
    calls = []

    def checked_replace(source, destination):
        assert json.loads(path.read_text(encoding="utf-8")) == original
        assert json.loads(source.read_text(encoding="utf-8")) == expected
        calls.append(destination)
        replace(source, destination)

    monkeypatch.setattr(settings_file.os, "replace", checked_replace)
    form.apply()
    assert calls == [path]
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert form.pending_changes() == {}
    assert not form.has_errors()
    fields = fields_by_key(form)
    assert fields["LOG_LEVEL"].value == "DEBUG"
    assert fields["LOG_LEVEL"].source == "config.json"
    assert fields["MEMORY_LIMIT"].value == "17"
    assert fields["MEMORY_LIMIT"].env_overridden
    form.set_value("MEMORY_LIMIT", "50")
    assert form.pending_changes() == {"MEMORY_LIMIT": (42, 50)}


def test_apply_creates_missing_file(tmp_path):
    path = tmp_path / "nested" / "config.json"
    form = SettingsForm(path, {})
    form.set_value("CHAT_TOOLS", "true")
    form.apply()
    assert json.loads(path.read_text(encoding="utf-8")) == {"settings": {"CHAT_TOOLS": True}}
    assert fields_by_key(form)["CHAT_TOOLS"].value == "1"
    assert fields_by_key(form)["CHAT_TOOLS"].source == "config.json"
    assert form.pending_changes() == {}


@pytest.mark.parametrize("exists", [False, True])
def test_apply_refuses_errors_without_writing(tmp_path, exists):
    path = tmp_path / "config.json"
    content = b'{ "window": {"x": 12} }\n'
    if exists:
        path.write_bytes(content)
    form = SettingsForm(path, {})
    form.set_value("MEMORY_LIMIT", "42")
    form.set_value("CHAT_TOOLS", "invalid")
    with pytest.raises(ValueError, match="validation errors"):
        form.apply()
    assert form.pending_changes() == {"MEMORY_LIMIT": (None, 42)}
    assert form.has_errors()
    assert path.exists() is exists
    if exists:
        assert path.read_bytes() == content
    assert list(tmp_path.iterdir()) == ([path] if exists else [])


def test_failed_save_retains_pending(tmp_path):
    path = tmp_path / "config.json"
    content = '{"window": {"x": 12}, "settings": []}'
    path.write_text(content, encoding="utf-8")
    form = SettingsForm(path, {})
    form.set_value("MEMORY_LIMIT", "42")
    with pytest.raises(ValueError, match="Existing settings must be an object"):
        form.apply()
    assert form.pending_changes() == {"MEMORY_LIMIT": (None, 42)}
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("exists", [False, True])
def test_construction_and_noop_apply_do_not_write(tmp_path, monkeypatch, exists):
    path = tmp_path / "config.json"
    content = b'{ "window": {"x": 12}, "settings": {"MEMORY_LIMIT": 42} }\n'
    if exists:
        path.write_bytes(content)

    def unexpected_write(*args, **kwargs):
        pytest.fail("Constructing or applying an unchanged form must not write")

    monkeypatch.setattr(Path, "write_text", unexpected_write)
    monkeypatch.setattr(settings_file.os, "replace", unexpected_write)
    form = SettingsForm(path, {})
    form.apply()
    assert path.exists() is exists
    if exists:
        assert path.read_bytes() == content
    assert list(tmp_path.iterdir()) == ([path] if exists else [])
