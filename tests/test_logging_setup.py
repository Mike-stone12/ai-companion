import logging
from types import SimpleNamespace

import pytest

from companion.app.logging_setup import LOG_FILE_NAME, setup_logging
from companion.core.memory.extractor import extract_memories_with_llm
from companion.core.model_profile import discover_model_profile


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for handler in root.handlers[:]:
        if handler not in handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


def test_logs_go_to_rotating_file(tmp_path):
    log_file = setup_logging(log_dir=tmp_path)
    logging.getLogger("companion.test").info("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_file == tmp_path / LOG_FILE_NAME
    assert "hello from the test" in log_file.read_text(encoding="utf-8")


def test_level_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "debug")
    setup_logging(log_dir=tmp_path)
    assert logging.getLogger().level == logging.DEBUG


def test_invalid_level_falls_back_to_info(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "LOUD")
    setup_logging(log_dir=tmp_path)
    assert logging.getLogger().level == logging.INFO


def test_repeated_setup_does_not_duplicate_handlers(tmp_path):
    setup_logging(log_dir=tmp_path)
    count = len(logging.getLogger().handlers)
    setup_logging(log_dir=tmp_path)
    assert len(logging.getLogger().handlers) == count


def test_missing_configured_model_is_a_warning(tmp_path, caplog):
    (tmp_path / "whale-girl").mkdir()
    (tmp_path / "whale-girl" / "a.model3.json").write_text("{}", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        discover_model_profile("missing", tmp_path)
    assert any(r.levelno == logging.WARNING and "missing" in r.getMessage() for r in caplog.records)


def test_unparseable_extraction_does_not_log_model_output_at_warning(caplog):
    client = SimpleNamespace(
        config=SimpleNamespace(api_key="key", base_url="https://api.deepseek.com/v1"),
        complete=lambda messages, **kwargs: "我的银行卡密码是 123456",
    )
    with caplog.at_level(logging.WARNING):
        extract_memories_with_llm(client, "我叫小林", "你好")
    assert "falling back" in caplog.text
    assert "123456" not in caplog.text
