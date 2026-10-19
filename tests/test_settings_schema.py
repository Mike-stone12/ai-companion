import json
import os
import runpy
from pathlib import Path

import pytest

from companion import paths

CONFIG_FIELDS = {
    "OPENAI_BASE_URL": "base_url",
    "OPENAI_MODEL": "model",
    "CHAT_THINKING": "chat_thinking",
    "CHAT_TOOLS": "chat_tools",
    "VOICE_INPUT": "voice_input",
    "TRANSCRIPTION_MODEL": "transcription_model",
    "WAKE_WORD": "wake_word",
    "WAKE_WORD_MODEL_DIR": "wake_word_model_dir",
    "PROACTIVE_CHAT": "proactive_chat",
    "ACTIVE_APP_MONITOR": "active_app_monitor",
    "EDGE_TTS_VOICE_ZH": "voice_zh",
    "EDGE_TTS_VOICE_EN": "voice_en",
    "TTS_PITCH": "tts_pitch",
    "TTS_RATE": "tts_rate",
    "MEMORY_ENABLED": "memory_enabled",
    "MEMORY_CONSOLIDATION": "memory_consolidation",
    "MEMORY_RELEVANT_RECALL": "memory_relevant_recall",
    "MEMORY_SEMANTIC_RECALL": "memory_semantic_recall",
    "EMBEDDING_MODEL": "embedding_model",
    "CONVERSATION_SUMMARY": "conversation_summary",
    "MEMORY_LIMIT": "memory_limit",
    "COMPANION_STATE": "companion_state",
    "MOOD_HALF_LIFE_MINUTES": "mood_half_life_minutes",
    "DAILY_SCHEDULE": "daily_schedule",
    "EMOTION_APPRAISAL": "emotion_appraisal",
}


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(os, "environ", {})


def build_config():
    module = Path(__file__).resolve().parents[1] / "companion" / "core" / "config.py"
    return runpy.run_path(str(module))["AppConfig"]()


def test_schema_covers_safe_settings_and_builtin_defaults():
    from companion.core.model_profile import DEFAULT_MODEL
    from companion.core.settings_schema import EDITABLE_SETTINGS, validate
    from companion.core.settings_values import SECRET_MARKERS, SETTING_NAMES

    schema = {entry.name: entry for entry in EDITABLE_SETTINGS}
    assert len(schema) == len(EDITABLE_SETTINGS)
    assert schema.keys() >= CONFIG_FIELDS.keys() | {"LOG_LEVEL", "LIVE2D_MODEL", "WAKE_WORD_PHRASES"}
    assert schema.keys() <= SETTING_NAMES
    assert "COMPANION_DATA_DIR" not in schema
    assert "MOONSHOT_BASE_URL" not in schema
    config = build_config()
    for name, entry in schema.items():
        assert not any(marker in name.upper() for marker in SECRET_MARKERS)
        assert entry.label.strip()
        assert entry.kind in {"bool", "int", "float", "choice", "str"}
        assert validate(name, entry.default) == entry.default
        if name in CONFIG_FIELDS:
            assert entry.default == getattr(config, CONFIG_FIELDS[name])
    assert schema["LOG_LEVEL"].default == "INFO"
    assert schema["LOG_LEVEL"].choices == ("DEBUG", "INFO", "WARNING", "ERROR")
    assert schema["MEMORY_LIMIT"].kind == "int"
    assert schema["MEMORY_LIMIT"].minimum == 1
    assert schema["LIVE2D_MODEL"].default == DEFAULT_MODEL
    assert schema["WAKE_WORD"].kind == "bool"
    assert schema["WAKE_WORD_PHRASES"].kind == "str"
    assert schema["WAKE_WORD_PHRASES"].default == ""
    assert schema["WAKE_WORD_MODEL_DIR"].kind == "str"
    assert schema["WAKE_WORD_MODEL_DIR"].choices == ()
    assert config.wake_word_phrases == ()


@pytest.mark.parametrize("name, value, expected", [
    ("CHAT_THINKING", True, True),
    ("VOICE_INPUT", True, True),
    ("VOICE_INPUT", False, False),
    ("TRANSCRIPTION_MODEL", " transcription-model ", "transcription-model"),
    ("TRANSCRIPTION_MODEL", " \t ", ""),
    ("WAKE_WORD", True, True),
    ("WAKE_WORD", False, False),
    ("WAKE_WORD_PHRASES", " 小鲸,hey whale ", "小鲸,hey whale"),
    ("WAKE_WORD_PHRASES", "", ""),
    ("WAKE_WORD_PHRASES", " \t ", ""),
    ("WAKE_WORD_MODEL_DIR", " models/vosk model ", "models/vosk model"),
    ("WAKE_WORD_MODEL_DIR", "", ""),
    ("WAKE_WORD_MODEL_DIR", " \t ", ""),
    ("ACTIVE_APP_MONITOR", True, True),
    ("ACTIVE_APP_MONITOR", False, False),
    ("MEMORY_ENABLED", False, False),
    ("MEMORY_LIMIT", 1, 1),
    ("MEMORY_LIMIT", 1000, 1000),
    ("LOG_LEVEL", " debug ", "DEBUG"),
    ("EDGE_TTS_VOICE_ZH", "custom-voice", "custom-voice"),
    ("EDGE_TTS_VOICE_EN", "en-US-AriaNeural", "en-US-AriaNeural"),
    ("EMBEDDING_MODEL", " embedding-model ", "embedding-model"),
    ("EMBEDDING_MODEL", "", ""),
    ("LIVE2D_MODEL", " hiyori ", "hiyori"),
])
def test_validate_normalizes(name, value, expected):
    from companion.core.settings_schema import validate

    actual = validate(name, value)
    assert actual == expected
    assert type(actual) is type(expected)


@pytest.mark.parametrize("name", [
    "UNKNOWN", "OPENAI_API_KEY", "api_key", "MY_SECRET", "ACCESS_TOKEN", "PASSWORD",
    "COMPANION_DATA_DIR", "OPENAI_BASE_URL", "MOONSHOT_BASE_URL", None, [],
])
def test_validate_rejects_uneditable_names(name):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError):
        validate(name, "private-value")


@pytest.mark.parametrize("name, value", [
    ("CHAT_THINKING", "true"), ("CHAT_TOOLS", 1), ("PROACTIVE_CHAT", 0.0),
    ("ACTIVE_APP_MONITOR", "true"),
    ("VOICE_INPUT", "true"), ("VOICE_INPUT", 1), ("TRANSCRIPTION_MODEL", False),
    ("WAKE_WORD", "true"), ("WAKE_WORD", 1), ("WAKE_WORD_PHRASES", False),
    ("WAKE_WORD_MODEL_DIR", False),
    ("MEMORY_ENABLED", None), ("MEMORY_LIMIT", True), ("MEMORY_LIMIT", "24"),
    ("MEMORY_LIMIT", 2.5), ("MEMORY_LIMIT", 0), ("MEMORY_LIMIT", -1),
    ("MEMORY_LIMIT", float("nan")), ("MEMORY_LIMIT", float("inf")),
    ("LOG_LEVEL", "TRACE"), ("LOG_LEVEL", ""), ("LOG_LEVEL", 10),
    ("EDGE_TTS_VOICE_ZH", []), ("EDGE_TTS_VOICE_EN", False),
    ("EMBEDDING_MODEL", {}), ("LIVE2D_MODEL", 42),
])
def test_validate_rejects_types_ranges_and_choices(name, value):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError):
        validate(name, value)


def test_save_merges_and_uses_atomic_writer(tmp_path, monkeypatch):
    from companion.core import settings_file
    from companion.core.settings_schema import save_settings

    path = tmp_path / "config.json"
    original = {"window": {"x": 12, "opacity": 0.7}, "extra": [1],
                "settings": {"UNKNOWN": {"nested": True}, "MEMORY_LIMIT": 24, "CHAT_TOOLS": True}}
    path.write_text(json.dumps(original), encoding="utf-8")
    updates = {"MEMORY_LIMIT": 42, "LOG_LEVEL": " debug "}
    expected = {**original, "settings": {**original["settings"], "MEMORY_LIMIT": 42, "LOG_LEVEL": "DEBUG"}}
    replace = settings_file.os.replace
    calls = []

    def checked_replace(source, destination):
        assert json.loads(path.read_text(encoding="utf-8")) == original
        assert json.loads(source.read_text(encoding="utf-8")) == expected
        calls.append(destination)
        replace(source, destination)

    monkeypatch.setattr(settings_file.os, "replace", checked_replace)
    save_settings(path, updates)
    assert calls == [path]
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert updates == {"MEMORY_LIMIT": 42, "LOG_LEVEL": " debug "}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("existing", [None, {"window": {"x": 5}}])
def test_save_creates_file_or_settings(tmp_path, existing):
    from companion.core.settings_schema import save_settings

    path = tmp_path / "nested" / "config.json"
    if existing is not None:
        path.parent.mkdir()
        path.write_text(json.dumps(existing), encoding="utf-8")
    save_settings(path, {"CHAT_TOOLS": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {**(existing or {}), "settings": {"CHAT_TOOLS": True}}


@pytest.mark.parametrize("exists", [False, True])
def test_invalid_batch_writes_nothing(tmp_path, exists):
    from companion.core.settings_schema import save_settings

    path = tmp_path / "config.json"
    content = b'{ "window": {"x": 12}, "settings": {"MEMORY_LIMIT": 24} }\n'
    if exists:
        path.write_bytes(content)
    with pytest.raises(ValueError):
        save_settings(path, {"MEMORY_LIMIT": 42, "CHAT_TOOLS": "invalid"})
    assert path.exists() is exists
    if exists:
        assert path.read_bytes() == content
    assert list(tmp_path.iterdir()) == ([path] if exists else [])


@pytest.mark.parametrize("section", [None, [], "text", 12])
def test_save_refuses_to_replace_non_object_settings(tmp_path, section):
    from companion.core.settings_schema import save_settings

    path = tmp_path / "config.json"
    content = json.dumps({"settings": section, "window": {"x": 12}})
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        save_settings(path, {"CHAT_TOOLS": True})
    assert path.read_text(encoding="utf-8") == content


def test_saved_settings_round_trip_through_existing_loader(tmp_path):
    from companion.core.settings_schema import save_settings, validate
    from companion.core.settings_values import load_setting_values

    updates = {
        "CHAT_THINKING": True, "CHAT_TOOLS": True, "PROACTIVE_CHAT": True,
        "VOICE_INPUT": True, "TRANSCRIPTION_MODEL": " transcription-model ",
        "WAKE_WORD": True, "WAKE_WORD_PHRASES": " 小鲸，hey whale,小鲸 ",
        "WAKE_WORD_MODEL_DIR": " models/vosk model ",
        "ACTIVE_APP_MONITOR": True,
        "LOG_LEVEL": " warning ", "EDGE_TTS_VOICE_ZH": "custom-zh", "EDGE_TTS_VOICE_EN": "custom-en",
        "MEMORY_ENABLED": False, "MEMORY_CONSOLIDATION": False, "MEMORY_RELEVANT_RECALL": False,
        "MEMORY_SEMANTIC_RECALL": True, "EMBEDDING_MODEL": " embedding-model ",
        "CONVERSATION_SUMMARY": False, "MEMORY_LIMIT": 42, "LIVE2D_MODEL": " hiyori ",
    }
    save_settings(tmp_path / "config.json", updates)
    values = load_setting_values()
    config = build_config()
    for name, value in updates.items():
        normalized = validate(name, value)
        assert values[name] == (str(int(normalized)) if isinstance(normalized, bool) else str(normalized))
        if name in CONFIG_FIELDS:
            assert getattr(config, CONFIG_FIELDS[name]) == normalized
    assert config.live2d_model == "hiyori"
    assert config.wake_word_phrases == ("小鲸", "hey whale")
    assert config.wake_word_usable is True
    assert values["LOG_LEVEL"] == "WARNING"


@pytest.mark.parametrize("value, expected", [
    (" https://api.deepseek.com/v1 ", "https://api.deepseek.com/v1"),
    ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1"),
    ("http://localhost:11434/v1", "http://localhost:11434/v1"),
])
def test_chat_base_url_is_normalized(value, expected):
    from companion.core.settings_schema import validate

    assert validate("OPENAI_BASE_URL", value) == expected


@pytest.mark.parametrize("value", ["", "api.deepseek.com", "ftp://x.example/v1", "https://", "https://a b/v1"])
def test_chat_base_url_must_be_an_http_url(value):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        validate("OPENAI_BASE_URL", value)


@pytest.mark.parametrize("value", [
    "http://localhost:11434/v1",
    "http://LOCALHOST:1234/v1",
    "http://127.0.0.1:1234/v1",
    "http://127.8.9.10/v1",
    "http://[::1]:8080/v1",
    "https://api.deepseek.com/v1",
    "https://192.168.1.5:8443/v1",
])
def test_chat_base_url_allows_https_and_loopback_http(value):
    from companion.core.settings_schema import validate

    assert validate("OPENAI_BASE_URL", value) == value


@pytest.mark.parametrize("value", [
    "http://api.deepseek.com/v1",
    "HTTP://api.deepseek.com/v1",
    "http://192.168.1.5:11434/v1",
    "http://0.0.0.0:11434/v1",
    "http://localhost.example.com/v1",
    "http://127.0.0.1.nip.io/v1",
    "http://localhost@api.example.com/v1",
    "http://[fe80::1]/v1",
])
def test_chat_base_url_rejects_plain_http_to_remote_hosts(value):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError, match="OPENAI_BASE_URL") as excinfo:
        validate("OPENAI_BASE_URL", value)
    assert "https" in str(excinfo.value)
    assert value not in str(excinfo.value)


@pytest.mark.parametrize("value", ["http://[::1/v1", "http://[not-an-ip]/v1"])
def test_chat_base_url_with_malformed_host_is_rejected_by_name(value):
    from companion.core.settings_schema import validate

    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        validate("OPENAI_BASE_URL", value)


@pytest.mark.parametrize("base_url, warned", [
    ("http://api.example.com/v1", True),
    ("http://user:pass@api.example.com/v1", True),
    ("http://localhost:11434/v1", False),
    ("https://api.example.com/v1", False),
])
def test_client_warns_once_for_plain_http_remote_base_url(base_url, warned, monkeypatch, caplog):
    from companion.core.config import AppConfig
    from companion.core.llm import client as llm_client

    monkeypatch.setattr(llm_client, "_warned_plaintext_urls", set())
    config = AppConfig(base_url=base_url, api_key="key")
    with caplog.at_level("WARNING", logger=llm_client.__name__):
        llm_client.OpenAICompatibleClient(config)
        llm_client.OpenAICompatibleClient(config)
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == (1 if warned else 0)
    if warned:
        message = warnings[0].getMessage()
        assert "api.example.com" in message
        assert "pass" not in message
        assert "key" not in message.replace("API key", "")


def test_chat_model_is_stripped_and_required():
    from companion.core.settings_schema import validate

    assert validate("OPENAI_MODEL", " deepseek-chat ") == "deepseek-chat"
    with pytest.raises(ValueError, match="OPENAI_MODEL"):
        validate("OPENAI_MODEL", "  ")
