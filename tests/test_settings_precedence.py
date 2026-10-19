import json
import logging
import os
import runpy
from dataclasses import asdict
from pathlib import Path

import pytest

from companion import paths
from companion.env import load_local_env


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    # Keep both import-time configuration and all file reads away from user data.
    monkeypatch.setattr(paths, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(os, "environ", {})
    return paths.CONFIG_PATH


def build_config():
    module = Path(__file__).resolve().parents[1] / "companion" / "core" / "config.py"
    return runpy.run_path(str(module))["AppConfig"]()


def write_config(path, settings):
    path.write_text(json.dumps({"settings": settings, "window": {"x": 12}, "extra": [1]}), encoding="utf-8")


def merge(raw, env):
    from companion.core.settings_values import merge_settings

    return merge_settings(raw, env)


def test_defaults_only(config_path):
    config = build_config()
    assert config.memory_limit == 24
    assert config.chat_thinking is False
    assert config.proactive_chat is False
    assert config.voice_zh == "zh-CN-XiaoxiaoNeural"
    assert not config_path.exists()


def test_json_overrides_defaults_without_writing(config_path):
    write_config(config_path, {"MEMORY_LIMIT": 42, "CHAT_THINKING": True, "EDGE_TTS_VOICE_ZH": "custom-voice"})
    before = config_path.read_bytes()
    environment_before = dict(os.environ)
    config = build_config()
    assert config.memory_limit == 42
    assert config.chat_thinking is True
    assert config.voice_zh == "custom-voice"
    assert config_path.read_bytes() == before
    assert list(config_path.parent.iterdir()) == [config_path]
    assert os.environ == environment_before


def test_environment_overrides_json(config_path, monkeypatch):
    write_config(config_path, {"MEMORY_LIMIT": 42, "CHAT_THINKING": True})
    monkeypatch.setenv("MEMORY_LIMIT", "17")
    monkeypatch.setenv("CHAT_THINKING", "0")
    config = build_config()
    assert config.memory_limit == 17
    assert config.chat_thinking is False


def test_dotenv_overrides_json_and_keeps_shell_precedence(config_path, monkeypatch):
    write_config(config_path, {"MEMORY_LIMIT": 42, "CHAT_THINKING": False})
    monkeypatch.setenv("MEMORY_LIMIT", "17")
    env_path = config_path.with_name("test.env")
    env_path.write_text("MEMORY_LIMIT=99\nCHAT_THINKING=1\n", encoding="utf-8")
    load_local_env(env_path)
    config = build_config()
    assert config.memory_limit == 17
    assert config.chat_thinking is True


def test_merge_converts_scalars_and_does_not_mutate_inputs():
    raw = {"MEMORY_LIMIT": 42, "CHAT_THINKING": True, "PROACTIVE_CHAT": False, "OPENAI_TIMEOUT": 1.5}
    env = {"MEMORY_LIMIT": "19", "OTHER_ENV": "untouched"}
    assert merge(raw, env) == {
        "MEMORY_LIMIT": "19", "CHAT_THINKING": "1", "PROACTIVE_CHAT": "0",
        "OPENAI_TIMEOUT": "1.5", "OTHER_ENV": "untouched",
    }
    assert raw["MEMORY_LIMIT"] == 42
    assert raw["CHAT_THINKING"] is True
    assert env == {"MEMORY_LIMIT": "19", "OTHER_ENV": "untouched"}


@pytest.mark.parametrize("value", [True, False, 1, 0, " YES ", "false", "False", "", "  "])
def test_json_flags_parse_exactly_like_environment(config_path, monkeypatch, value):
    keys = ("CHAT_THINKING", "PROACTIVE_CHAT", "MEMORY_ENABLED", "CONVERSATION_SUMMARY")
    write_config(config_path, dict.fromkeys(keys, value))
    from_json = build_config()
    write_config(config_path, {})
    text = str(int(value)) if isinstance(value, bool) else str(value)
    for key in keys:
        monkeypatch.setenv(key, text)
    assert asdict(build_config()) == asdict(from_json)


@pytest.mark.parametrize(
    "key", ["OPENAI_API_KEY", "MOONSHOT_API_KEY", "MY_KEY", "SECRET_X", "X_TOKEN", "PASSWORD", "api_key"],
)
def test_secrets_are_ignored_with_value_free_warnings(key, caplog):
    with caplog.at_level(logging.DEBUG):
        assert merge({key: "private-json-value"}, {}) == {}
    assert any(record.levelno == logging.WARNING and key in record.message for record in caplog.records)
    assert "private-json-value" not in caplog.text
    assert merge({key: "private-json-value"}, {key: "shell-value"}) == {key: "shell-value"}


def test_json_cannot_supply_api_keys(config_path, monkeypatch):
    write_config(config_path, {"OPENAI_API_KEY": "json-key", "MOONSHOT_API_KEY": "json-fallback"})
    assert build_config().api_key == ""
    monkeypatch.setenv("MOONSHOT_API_KEY", "shell-fallback")
    assert build_config().api_key == "shell-fallback"
    monkeypatch.setenv("OPENAI_API_KEY", "shell-key")
    assert build_config().api_key == "shell-key"


def test_data_directory_is_ignored(caplog):
    with caplog.at_level(logging.DEBUG):
        assert merge({"COMPANION_DATA_DIR": "private-path"}, {}) == {}
    assert "private-path" not in caplog.text
    assert merge({"COMPANION_DATA_DIR": "ignored"}, {"COMPANION_DATA_DIR": "shell-path"}) == {
        "COMPANION_DATA_DIR": "shell-path",
    }


def test_unknown_keys_are_debug_only(caplog):
    with caplog.at_level(logging.DEBUG):
        assert merge({"UNKNOWN_SETTING": "unknown-value"}, {}) == {}
    assert any(record.levelno == logging.DEBUG and "UNKNOWN_SETTING" in record.message for record in caplog.records)
    assert "unknown-value" not in caplog.text


@pytest.mark.parametrize("value", [None, [], {}])
def test_non_scalar_values_are_ignored(value):
    assert merge({"MEMORY_LIMIT": value}, {}) == {}


@pytest.mark.parametrize("content", [None, "{broken", "[]", "null", "{}", '{"window": {"x": 2}}',
                                     '{"settings": null}', '{"settings": []}', '{"settings": "text"}'])
def test_unusable_files_fall_back(config_path, content):
    if content is not None:
        config_path.write_text(content, encoding="utf-8")
    config = build_config()
    assert config.memory_limit == 24
    assert config.chat_thinking is False
    if content is not None:
        assert config_path.read_text(encoding="utf-8") == content


def test_unreadable_file_falls_back(config_path, monkeypatch):
    config_path.write_text("{}", encoding="utf-8")
    original = Path.read_text

    def read_text(path, *args, **kwargs):
        if path == config_path:
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert build_config().memory_limit == 24


def test_inaccessible_path_falls_back(config_path, monkeypatch):
    original = Path.exists

    def exists(path):
        if path == config_path:
            raise PermissionError("denied")
        return original(path)

    monkeypatch.setattr(Path, "exists", exists)
    assert build_config().memory_limit == 24


def test_live2d_settings(config_path, tmp_path):
    from companion.core.model_profile import discover_vendor_dir

    vendor = tmp_path / "custom-vendor"
    vendor.mkdir()
    write_config(config_path, {"LIVE2D_MODEL": "hiyori", "LIVE2D_VENDOR_DIR": str(vendor)})
    assert build_config().live2d_model == "hiyori"
    assert discover_vendor_dir() == vendor.resolve()


@pytest.mark.parametrize("env_level, expected", [(None, logging.DEBUG), ("WARNING", logging.WARNING)])
def test_logging_uses_json_with_environment_precedence(config_path, monkeypatch, env_level, expected):
    from companion.app.logging_setup import setup_logging

    write_config(config_path, {"LOG_LEVEL": "DEBUG"})
    if env_level is not None:
        monkeypatch.setenv("LOG_LEVEL", env_level)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    try:
        setup_logging(log_dir=config_path.parent / "logs")
        assert root.level == expected
    finally:
        for handler in root.handlers[:]:
            if handler not in handlers:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(level)
