import pytest


@pytest.fixture(autouse=True)
def _no_real_keychain(monkeypatch):
    # Tests inject fake backends; never read or write the developer's real keychain.
    monkeypatch.setenv("COMPANION_KEYCHAIN", "0")
