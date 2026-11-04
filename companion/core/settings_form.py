"""A GUI-independent editor for the non-secret settings schema."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from companion.core import settings_file, settings_schema
from companion.core.settings_values import merge_settings


@dataclass(frozen=True, slots=True)
class Field:
    """Schema metadata and the effective configuration input, as text."""

    key: str
    kind: str
    choices: tuple[str, ...]
    minimum: int | float | None
    maximum: int | float | None
    description: str
    value: str
    source: Literal["default", "config.json", "environment"]
    env_overridden: bool


class SettingsForm:
    """Stage edits without writing until apply succeeds.

    Fields describe saved configuration plus environment overrides, using the
    same text conversion as the CLI. Pending edits do not change these effective
    values until apply. Missing stored values are reported as None in diffs;
    setting an absent key to its default is an explicit stored change.
    """

    def __init__(self, config_path: Path, environment: Mapping[str, str] | None = None) -> None:
        self.config_path = Path(config_path)
        self._environment = os.environ if environment is None else environment
        self._pending: dict[str, settings_schema.SettingValue] = {}
        self._errors: dict[str, str] = {}
        self._refresh()

    def _refresh(self) -> None:
        stored = settings_file.load_settings(self.config_path).get("settings", {})
        self._stored = stored if isinstance(stored, dict) else {}
        file_values = merge_settings(stored, {})
        values = merge_settings(file_values, self._environment)
        defaults = merge_settings({entry.name: entry.default for entry in settings_schema.EDITABLE_SETTINGS}, {})
        self._fields = []
        for entry in settings_schema.EDITABLE_SETTINGS:
            overridden = entry.name in self._environment
            source = "environment" if overridden else ("config.json" if entry.name in file_values else "default")
            self._fields.append(Field(
                key=entry.name,
                kind=entry.kind,
                choices=entry.choices,
                minimum=entry.minimum,
                maximum=entry.maximum,
                description=entry.label,
                value=values.get(entry.name, defaults[entry.name]),
                source=source,
                env_overridden=overridden,
            ))

    @property
    def fields(self) -> list[Field]:
        """Return descriptors in schema order."""
        return self._fields.copy()

    @property
    def errors(self) -> dict[str, str]:
        """Return per-key validation messages, without exposing mutable state."""
        return self._errors.copy()

    def set_value(self, key: str, raw: settings_schema.SettingValue) -> bool:
        """Stage validated text or a typed value; return False on invalid input.

        An invalid edit removes any earlier pending value for that key. Unknown
        and secret keys are recorded as errors and never staged.
        """
        try:
            value = settings_schema.parse_value(key, raw)
        except ValueError as exc:
            self._pending.pop(key, None)
            self._errors[key] = str(exc)
            return False
        self._errors.pop(key, None)
        old = self._stored.get(key)
        if key in self._stored and type(old) is type(value) and old == value:
            self._pending.pop(key, None)
        else:
            self._pending[key] = value
        return True

    def pending_changes(self) -> dict[str, tuple[object, settings_schema.SettingValue]]:
        """Return key -> (old stored value, new stored value), excluding no-ops."""
        return {key: (self._stored.get(key), value) for key, value in self._pending.items()}

    def has_errors(self) -> bool:
        return bool(self._errors)

    def reset(self) -> None:
        """Discard edits and errors, and reread the effective configuration."""
        self._pending.clear()
        self._errors.clear()
        self._refresh()

    def apply(self) -> None:
        """Persist atomically through the schema; retain edits if saving fails.

        With no pending changes this is a read-only refresh.
        """
        if self.has_errors():
            raise ValueError("Cannot apply settings while validation errors exist")
        settings_schema.save_settings(self.config_path, self._pending)
        self._pending.clear()
        self._refresh()
