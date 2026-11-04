"""API key storage: OS keychain first, environment fallback, never the key in logs."""

import logging

import pytest

from companion.core.api_key import (
    ACCOUNT,
    SERVICE,
    ApiKeyStore,
    KeychainUnavailable,
    ResolvedKey,
    resolve_api_key,
)

SECRET = "sk-test-0123456789abcdef"


class FakeKeyring:
    """Mimics the keyring module's get/set/delete_password API in memory."""

    def __init__(self, fail: Exception | None = None):
        self.items: dict[tuple[str, str], str] = {}
        self.fail = fail

    def get_password(self, service, account):
        if self.fail:
            raise self.fail
        return self.items.get((service, account))

    def set_password(self, service, account, password):
        if self.fail:
            raise self.fail
        self.items[(service, account)] = password

    def delete_password(self, service, account):
        if self.fail:
            raise self.fail
        if (service, account) not in self.items:
            raise KeyError("not found")
        del self.items[(service, account)]


def test_keychain_value_wins_over_environment():
    backend = FakeKeyring()
    backend.items[(SERVICE, ACCOUNT)] = SECRET
    store = ApiKeyStore(backend=backend, environ={"OPENAI_API_KEY": "sk-env"})

    resolved = store.resolve()

    assert resolved.value == SECRET
    assert resolved.source == "keychain"


def test_environment_is_the_fallback_when_keychain_is_empty():
    store = ApiKeyStore(backend=FakeKeyring(), environ={"OPENAI_API_KEY": " sk-env "})

    resolved = store.resolve()

    assert resolved.value == "sk-env"
    assert resolved.source == "environment"


def test_legacy_moonshot_variable_is_still_accepted():
    store = ApiKeyStore(backend=FakeKeyring(), environ={"MOONSHOT_API_KEY": "sk-moon"})

    assert store.resolve().value == "sk-moon"


def test_no_key_anywhere_resolves_empty():
    resolved = ApiKeyStore(backend=FakeKeyring(), environ={}).resolve()

    assert resolved.value == ""
    assert resolved.source == "none"


def test_missing_keyring_package_falls_back_to_environment():
    store = ApiKeyStore(backend=None, environ={"OPENAI_API_KEY": "sk-env"})

    assert not store.available
    assert store.resolve().source == "environment"


def test_broken_backend_falls_back_without_logging_the_key(caplog):
    backend = FakeKeyring(fail=RuntimeError(f"locked: {SECRET}"))
    store = ApiKeyStore(backend=backend, environ={"OPENAI_API_KEY": "sk-env"})

    with caplog.at_level(logging.DEBUG):
        resolved = store.resolve()

    assert resolved.source == "environment"
    assert SECRET not in caplog.text
    assert "RuntimeError" in caplog.text


def test_save_strips_and_writes_to_keychain():
    backend = FakeKeyring()
    store = ApiKeyStore(backend=backend, environ={})

    store.save(f"  {SECRET}\n")

    assert backend.items[(SERVICE, ACCOUNT)] == SECRET
    assert store.resolve().source == "keychain"


@pytest.mark.parametrize("value", ["", "   ", "sk-a b", "sk-\x00"])
def test_save_rejects_blank_or_malformed_keys(value):
    backend = FakeKeyring()

    with pytest.raises(ValueError) as excinfo:
        ApiKeyStore(backend=backend, environ={}).save(value)

    assert backend.items == {}
    if value.strip():
        assert value.strip() not in str(excinfo.value)


def test_save_without_keychain_raises_unavailable():
    with pytest.raises(KeychainUnavailable):
        ApiKeyStore(backend=None, environ={}).save(SECRET)


def test_save_backend_error_is_wrapped_without_the_key(caplog):
    store = ApiKeyStore(backend=FakeKeyring(fail=RuntimeError(f"denied {SECRET}")), environ={})

    with caplog.at_level(logging.DEBUG), pytest.raises(KeychainUnavailable) as excinfo:
        store.save(SECRET)

    assert SECRET not in str(excinfo.value)
    assert SECRET not in caplog.text


def test_clear_removes_the_keychain_entry_and_reports_whether_one_existed():
    backend = FakeKeyring()
    backend.items[(SERVICE, ACCOUNT)] = SECRET
    store = ApiKeyStore(backend=backend, environ={"OPENAI_API_KEY": "sk-env"})

    assert store.clear() is True
    assert store.clear() is False
    assert store.resolve().source == "environment"


def test_clear_without_keychain_raises_unavailable():
    with pytest.raises(KeychainUnavailable):
        ApiKeyStore(backend=None, environ={}).clear()


def test_keychain_disabled_by_environment_flag():
    backend = FakeKeyring()
    backend.items[(SERVICE, ACCOUNT)] = SECRET
    store = ApiKeyStore(backend=backend, environ={"COMPANION_KEYCHAIN": "0", "OPENAI_API_KEY": "sk-env"})

    assert not store.available
    assert store.resolve().source == "environment"


def test_resolve_api_key_helper_uses_the_given_store():
    backend = FakeKeyring()
    backend.items[(SERVICE, ACCOUNT)] = SECRET

    assert resolve_api_key(ApiKeyStore(backend=backend, environ={})) == SECRET


def test_fail_backend_counts_as_unavailable():
    class FailKeyring(FakeKeyring):
        priority = 0

    class Module(FakeKeyring):
        def get_keyring(self):
            return FailKeyring()

    store = ApiKeyStore(backend=Module(), environ={"OPENAI_API_KEY": "sk-env"})

    assert not store.available
    assert store.resolve().source == "environment"


@pytest.mark.parametrize(("source", "available", "expected"), [
    ("keychain", True, "Stored in the system keychain"),
    ("environment", True, "Read from .env or the environment"),
    ("none", True, "Not set"),
    ("none", False, "Not set (no system keychain available; use .env)"),
])
def test_status_text_names_the_source_but_never_the_key(source, available, expected):
    from companion.core.api_key import describe_status

    assert describe_status(ResolvedKey(SECRET if source != "none" else "", source), available) == expected


def test_resolved_key_repr_hides_the_value():
    assert SECRET not in repr(ResolvedKey(SECRET, "keychain"))


def test_settings_dialog_never_prefills_or_logs_the_key():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "companion/ui/settings_dialog.py").read_text(encoding="utf-8")

    assert "EchoMode.Password" in source
    assert "setText(resolved.value" not in source
    assert "logger" not in source


def test_window_reads_the_key_through_the_store():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "companion/ui/main_window.py").read_text(encoding="utf-8")

    assert "AppConfig(api_key=resolved.value)" in source
    assert '"API key source: %s", resolved.source' in source


def test_separate_accounts_keep_separate_keys():
    from companion.core.api_key import VISION_ACCOUNT

    backend = FakeKeyring()
    chat = ApiKeyStore(backend=backend, environ={})
    vision = ApiKeyStore(backend=backend, environ={"OPENAI_API_KEY": "sk-chat"}, account=VISION_ACCOUNT)
    vision.save("sk-vision")

    assert backend.items == {(SERVICE, VISION_ACCOUNT): "sk-vision"}
    assert chat.resolve().source == "none"
    assert vision.resolve().value == "sk-vision"
    from_env = ApiKeyStore(backend=FakeKeyring(), environ={"VISION_API_KEY": "sk-env"}, account=VISION_ACCOUNT)
    assert from_env.resolve().value == "sk-env"
    # The chat key in the environment is not a vision key.
    chat_env = ApiKeyStore(backend=FakeKeyring(), environ={"OPENAI_API_KEY": "x"}, account=VISION_ACCOUNT)
    assert chat_env.resolve().value == ""


@pytest.mark.parametrize(("service", "own", "expected"), [
    ("https://api.deepseek.com/v1", "", "sk-chat"),
    ("https://API.deepseek.com", "", "sk-chat"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "", None),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "sk-own", "sk-own"),
    ("http://localhost:11434/v1", "", ""),
    ("http://127.0.0.1:8000/v1", "sk-own", "sk-own"),
    ("https://api.deepseek.com.evil.example/v1", "", None),
])
def test_service_key_never_leaks_the_chat_key_to_another_host(service, own, expected):
    from companion.core.api_key import service_api_key

    assert service_api_key(service, "https://api.deepseek.com/v1", own, "sk-chat") == expected
