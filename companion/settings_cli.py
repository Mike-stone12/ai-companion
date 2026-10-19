"""Inspect and edit non-secret app settings, without GUI dependencies."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from companion.core import settings_file, settings_schema
from companion.core.settings_values import SECRET_MARKERS, SETTING_NAMES, merge_settings


def _setting(name: str) -> settings_schema.Setting:
    if name in SETTING_NAMES and not any(marker in name.upper() for marker in SECRET_MARKERS):
        for setting in settings_schema.EDITABLE_SETTINGS:
            if setting.name == name:
                return setting
    raise ValueError(f"Setting is not editable: {name}")


def _parse_value(setting: settings_schema.Setting, text: str) -> settings_schema.SettingValue:
    value = text
    if setting.kind in {"bool", "int", "float"}:
        try:
            value = json.loads(text)
        except ValueError:
            # Let the schema report the required type, without echoing the input.
            pass
    return settings_schema.validate(setting.name, value)


def _print_setting(setting: settings_schema.Setting, file_values: dict[str, str], values: dict[str, str]) -> None:
    # Use the same scalar conversion and environment overlay as the app. These
    # are configuration inputs; consumer-specific runtime fallbacks stay in core.
    defaults = merge_settings({setting.name: setting.default}, {})
    source = "environment" if setting.name in os.environ else (
        "config.json" if setting.name in file_values else "default"
    )
    value = values.get(setting.name, defaults[setting.name])
    print(f"{setting.name} = {json.dumps(value, ensure_ascii=False)} (source: {source})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="override the app's user data directory")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list editable settings, effective values, and sources")
    show = commands.add_parser("show", help="show a setting's value, source, and schema details")
    show.add_argument("key", metavar="KEY")
    edit = commands.add_parser("set", help="preview a setting change, or save it with --write")
    edit.add_argument("key", metavar="KEY")
    edit.add_argument("value", metavar="VALUE", help="text, or JSON true/false or a number for typed settings")
    edit.add_argument("--write", action="store_true", help="save the validated value to config.json atomically")
    args = parser.parse_args(argv)

    try:
        from companion.paths import user_data_dir

        data_dir = args.data_dir.expanduser() if args.data_dir is not None else user_data_dir()
        path = data_dir / "config.json"
        setting = _setting(args.key) if args.command != "list" else None
        stored = settings_file.load_settings(path).get("settings", {})
        if args.command in {"list", "show"}:
            file_values = merge_settings(stored, {})
            values = merge_settings(file_values, os.environ)

        if args.command == "list":
            for entry in settings_schema.EDITABLE_SETTINGS:
                _print_setting(_setting(entry.name), file_values, values)
        elif args.command == "show":
            _print_setting(setting, file_values, values)
            print(f"Description: {setting.label}")
            print(f"Type: {setting.kind}")
            if setting.kind == "bool":
                print("Allowed values: true, false")
            if setting.choices:
                print(f"Allowed values: {', '.join(setting.choices)}")
            if setting.minimum is not None:
                print(f"Minimum: {setting.minimum}")
            if setting.maximum is not None:
                print(f"Maximum: {setting.maximum}")
        else:
            value = _parse_value(setting, args.value)
            if not isinstance(stored, dict):
                raise ValueError("Existing settings must be an object")
            old = json.dumps(stored[setting.name], ensure_ascii=False) if setting.name in stored else "<not set>"
            print(f"{setting.name}")
            print(f"Old config.json value: {old}")
            print(f"New config.json value: {json.dumps(value, ensure_ascii=False)}")
            if setting.name in os.environ:
                print(f"Note: environment variable {setting.name} overrides this setting.")
            if args.write:
                settings_schema.save_settings(path, {setting.name: value})
                print(f"Saved {setting.name} to {path}.")
            else:
                print("Dry run: nothing was saved. Use --write to save.")
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    # Windows redirected streams may otherwise use a legacy code page.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
