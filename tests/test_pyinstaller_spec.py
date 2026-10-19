"""Check the packaging contract without executing the spec or importing Qt."""

import ast
import runpy
import sys
from pathlib import Path

import pytest

import companion.env

ROOT = Path(__file__).resolve().parents[1]
SPEC_TEXT = (ROOT / "ai-companion.spec").read_text(encoding="utf-8")


@pytest.fixture
def spec_lists():
    tree = ast.parse(SPEC_TEXT)
    values = {
        target.id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id in {"DATAS", "HIDDENIMPORTS", "EXCLUDES"}
    }
    assert set(values) == {"DATAS", "HIDDENIMPORTS", "EXCLUDES"}
    assert all(isinstance(value, list) for value in values.values())
    for entry in values["DATAS"]:
        assert isinstance(entry, tuple) and len(entry) == 2
        assert all(isinstance(part, str) for part in entry)
    for name in ("HIDDENIMPORTS", "EXCLUDES"):
        assert all(isinstance(value, str) for value in values[name])
    return values


def normalized_path(value):
    return Path(value.replace("\\", "/"))


def test_data_sources_exist_and_stay_in_repository(spec_lists):
    for source, destination in spec_lists["DATAS"]:
        source, destination = normalized_path(source), normalized_path(destination)
        for path in (source, destination):
            assert not path.is_absolute()
            assert ".." not in path.parts
        assert (ROOT / source).exists()
        assert (ROOT / source).resolve().is_relative_to(ROOT)


def test_data_destinations_match_frozen_resource_paths(spec_lists, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    monkeypatch.setattr(companion.env, "load_local_env", lambda path: None)
    paths = runpy.run_path(str(ROOT / "companion" / "paths.py"))
    assert paths["APP_DIR"] == tmp_path

    html = paths["HTML_PATH"].relative_to(tmp_path)
    models = paths["MODELS_DIR"].relative_to(tmp_path)
    vendor = paths["VENDOR_DIR"].relative_to(tmp_path)
    # A file is copied into its destination; a directory's contents go there.
    expected = {(html, html.parent), (models, models), (vendor, vendor)}
    actual = {(normalized_path(src), normalized_path(dest)) for src, dest in spec_lists["DATAS"]}
    assert actual == expected


def test_data_does_not_include_secrets_or_user_data(spec_lists):
    forbidden = {
        ".env", "tests", "evals", "memory.json", "history.json", "config.json",
        "reminders.json", "logs", "user_data", "优化计划.md",
    }
    for source, destination in spec_lists["DATAS"]:
        source = normalized_path(source)
        # Check directory contents too, since PyInstaller copies them recursively.
        included = [source, normalized_path(destination)]
        if (ROOT / source).is_dir():
            included.extend(path.relative_to(ROOT) for path in (ROOT / source).rglob("*"))
        for path in included:
            assert not forbidden.intersection(part.casefold() for part in path.parts), path
            assert not any(part.casefold().startswith(".env.") for part in path.parts), path


def test_required_imports_and_exclusions(spec_lists):
    assert {"vosk", "pytest", "ruff"} <= set(spec_lists["EXCLUDES"])
    assert {
        "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebChannel",
        "PyQt6.QtMultimedia", "edge_tts",
    } <= set(spec_lists["HIDDENIMPORTS"])
    assert not set(spec_lists["HIDDENIMPORTS"]).intersection(spec_lists["EXCLUDES"])


def test_macos_microphone_usage_description():
    assert "NSMicrophoneUsageDescription" in SPEC_TEXT
