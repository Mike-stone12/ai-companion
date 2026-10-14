import json
import logging
from pathlib import Path

import pytest

from companion.core.legacy_data import migrate_legacy_file
from companion.core.memory.store import MemoryStore
from companion.paths import user_data_dir

HOME = Path("/home/tester")


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("darwin", {}, HOME / "Library" / "Application Support" / "AICompanion"),
        ("win32", {"APPDATA": "C:/Users/me/AppData/Roaming"}, Path("C:/Users/me/AppData/Roaming") / "AICompanion"),
        ("win32", {}, HOME / "AppData" / "Roaming" / "AICompanion"),
        ("linux", {"XDG_DATA_HOME": "/data/xdg"}, Path("/data/xdg") / "ai-companion"),
        ("linux", {}, HOME / ".local" / "share" / "ai-companion"),
    ],
)
def test_user_data_dir_follows_platform_conventions(platform, env, expected):
    assert user_data_dir(platform=platform, env=env, home=HOME) == expected


def test_user_data_dir_can_be_overridden():
    env = {"COMPANION_DATA_DIR": "~/portable-companion", "APPDATA": "ignored"}
    assert user_data_dir(platform="win32", env=env, home=HOME) == Path("~/portable-companion").expanduser()


def test_legacy_file_is_moved_when_target_missing(tmp_path):
    legacy = tmp_path / "project" / "memory.json"
    legacy.parent.mkdir()
    legacy.write_text('[{"summary": "喜欢吃鱼"}]', encoding="utf-8")
    target = tmp_path / "data" / "memory.json"

    assert migrate_legacy_file(legacy, target) is True
    assert not legacy.exists()
    assert json.loads(target.read_text(encoding="utf-8"))[0]["summary"] == "喜欢吃鱼"


def test_existing_target_is_never_overwritten(tmp_path, caplog):
    legacy = tmp_path / "legacy.json"
    legacy.write_text("old", encoding="utf-8")
    target = tmp_path / "target.json"
    target.write_text("new", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert migrate_legacy_file(legacy, target) is False
    assert legacy.read_text(encoding="utf-8") == "old"
    assert target.read_text(encoding="utf-8") == "new"
    assert "not migrated" in caplog.text


def test_nothing_to_migrate(tmp_path):
    assert migrate_legacy_file(tmp_path / "missing.json", tmp_path / "target.json") is False
    assert not (tmp_path / "target.json").exists()


def test_memory_store_creates_its_directory_on_save(tmp_path):
    store = MemoryStore(tmp_path / "nested" / "dir" / "memory.json")
    store.upsert_many([{"summary": "用户叫小林", "category": "identity"}])
    assert (tmp_path / "nested" / "dir" / "memory.json").exists()
