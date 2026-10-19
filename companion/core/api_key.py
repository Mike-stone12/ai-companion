"""Resolve the chat API key from the OS keychain first, then the environment.

The keychain is reached through the optional ``keyring`` package, imported lazily
so tests and the GUI-free core never need it. Errors from a backend are logged by
exception type only: a backend message could echo the secret back.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

SERVICE = "AICompanion"
ACCOUNT = "OPENAI_API_KEY"
# Fallback variables, also loaded from the local .env by companion.paths.
ENV_NAMES = ("OPENAI_API_KEY", "MOONSHOT_API_KEY")
# Set to 0 to skip the keychain entirely (CI, headless Linux without a secret service).
DISABLE_FLAG = "COMPANION_KEYCHAIN"

KeySource = Literal["keychain", "environment", "none"]
_DEFAULT = object()


class KeychainUnavailable(RuntimeError):
    """The keychain cannot be used; the message never contains the key."""


@dataclass(frozen=True, slots=True)
class ResolvedKey:
    value: str
    source: KeySource

    def __repr__(self) -> str:
        return f"ResolvedKey(value=<{len(self.value)} chars>, source={self.source!r})"


def _import_keyring() -> Any | None:
    try:
        import keyring
    except ImportError:
        return None
    return keyring


def _flag_disabled(environ: Mapping[str, str]) -> bool:
    return environ.get(DISABLE_FLAG, "").strip().lower() in {"0", "false", "no", "off"}


class ApiKeyStore:
    """Read, save, and clear the API key. ``backend`` follows the keyring module API."""

    def __init__(self, backend: Any = _DEFAULT, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        if _flag_disabled(self._environ):
            backend = None
        elif backend is _DEFAULT:
            backend = _import_keyring()
        self._backend = backend if backend is not None and self._usable(backend) else None

    @staticmethod
    def _usable(backend: Any) -> bool:
        # keyring's "fail" and "null" backends report a priority of 0 or less.
        get_keyring = getattr(backend, "get_keyring", None)
        if get_keyring is None:
            return True
        try:
            return getattr(get_keyring(), "priority", 1) > 0
        except Exception as exc:
            logger.warning("Keychain backend unavailable (%s)", type(exc).__name__)
            return False

    @property
    def available(self) -> bool:
        return self._backend is not None

    def _keychain_value(self) -> str:
        if self._backend is None:
            return ""
        try:
            value = self._backend.get_password(SERVICE, ACCOUNT)
        except Exception as exc:
            logger.warning("Could not read the API key from the keychain (%s); using the environment",
                           type(exc).__name__)
            return ""
        return value.strip() if isinstance(value, str) else ""

    def resolve(self) -> ResolvedKey:
        value = self._keychain_value()
        if value:
            return ResolvedKey(value, "keychain")
        for name in ENV_NAMES:
            value = self._environ.get(name, "").strip()
            if value:
                return ResolvedKey(value, "environment")
        return ResolvedKey("", "none")

    def _require_backend(self) -> Any:
        if self._backend is None:
            raise KeychainUnavailable("No system keychain is available; set OPENAI_API_KEY in .env instead")
        return self._backend

    def save(self, key: str) -> None:
        value = key.strip() if isinstance(key, str) else ""
        if not value:
            raise ValueError("The API key is empty")
        if any(char.isspace() or not char.isprintable() for char in value):
            raise ValueError("The API key contains spaces or control characters")
        backend = self._require_backend()
        try:
            backend.set_password(SERVICE, ACCOUNT, value)
        except Exception as exc:
            logger.warning("Could not save the API key to the keychain (%s)", type(exc).__name__)
            raise KeychainUnavailable(f"The keychain refused the API key ({type(exc).__name__})") from None
        logger.info("API key saved to the system keychain")

    def clear(self) -> bool:
        """Delete the keychain entry; return False when there was none."""
        backend = self._require_backend()
        try:
            if backend.get_password(SERVICE, ACCOUNT) is None:
                return False
            backend.delete_password(SERVICE, ACCOUNT)
        except Exception as exc:
            logger.warning("Could not remove the API key from the keychain (%s)", type(exc).__name__)
            raise KeychainUnavailable(f"The keychain refused to remove the API key ({type(exc).__name__})") from None
        logger.info("API key removed from the system keychain")
        return True


def resolve_api_key(store: ApiKeyStore | None = None) -> str:
    return (store or ApiKeyStore()).resolve().value


def describe_status(resolved: ResolvedKey, keychain_available: bool) -> str:
    """Plain-text status for the settings dialog; it names the source, never the key."""
    if resolved.source == "keychain":
        return "Stored in the system keychain"
    if resolved.source == "environment":
        return "Read from .env or the environment"
    return "Not set" if keychain_available else "Not set (no system keychain available; use .env)"
