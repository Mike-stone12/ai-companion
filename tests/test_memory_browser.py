import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from companion.core.memory.browser import MemoryBrowserModel
from companion.core.memory.store import MemoryStore, clip_memory_text

NOW = "2026-10-19T12:00:00+00:00"


@pytest.fixture
def entries():
    return [
        {"summary": "Likes Coffee", "updated_at": "2026-10-01T12:00:00+00:00", "custom": {"keep": True}},
        {"summary": "Visits Paris", "updated_at": "2026-10-18T12:00:00+00:00"},
        {"summary": "Undated memory"},
    ]


@pytest.fixture
def path(tmp_path, entries):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


@pytest.fixture
def model(path):
    return MemoryBrowserModel(path.parent, now=lambda: NOW)


def snapshot(directory):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}


def test_rows_keep_stored_indices_and_display_timestamps(model):
    rows = model.rows
    assert [row.index for row in rows] == [2, 1, 3]
    assert [row.summary for row in rows] == ["Visits Paris", "Likes Coffee", "Undated memory"]
    assert rows[0].timestamp == "2026-10-18 12:00:00+00:00"
    assert rows[2].timestamp == ""
    rows.clear()
    assert len(model.rows) == 3
    with pytest.raises(FrozenInstanceError):
        model.rows[0].summary = "Changed"


@pytest.mark.parametrize(("query", "indices"), [("cOfFeE", [1]), ("MEMORY", [3]), ("", [2, 1, 3]), ("absent", [])])
def test_filter(model, query, indices):
    assert [row.index for row in model.filter(query)] == indices


@pytest.mark.parametrize("text", ["  Corrected\n\ttext  ", "A long corrected memory " * 8])
def test_stage_returns_normalized_preview_without_writing(model, path, text):
    before = snapshot(path.parent)
    preview = model.stage_edit(1, text)
    assert preview.index == 1
    assert preview.old_summary == "Likes Coffee"
    assert preview.new_summary == clip_memory_text(text)
    assert model.has_pending_changes
    assert model.rows[1].summary == "Likes Coffee"
    assert snapshot(path.parent) == before


@pytest.mark.parametrize(("index", "text", "message"), [
    (1, " \n\t ", "empty"),
    (0, "New", "index"),
    (-1, "New", "index"),
    (4, "New", "index"),
    (True, "New", "index"),
    (1.0, "New", "index"),
    (None, "New", "index"),
    ("1", "New", "index"),
    (1, "  Visits\nParis ", "already has"),
])
def test_invalid_stage_blocks_save_without_writing(model, path, index, text, message):
    before = snapshot(path.parent)
    with pytest.raises(ValueError, match=message):
        model.stage_edit(index, text)
    assert not model.has_pending_changes
    assert model.errors
    with pytest.raises(ValueError, match="validation"):
        model.save()
    assert snapshot(path.parent) == before


def test_duplicates_include_other_pending_edits(model, path):
    before = snapshot(path.parent)
    model.stage_edit(1, "Shared summary")
    with pytest.raises(ValueError, match="already has"):
        model.stage_edit(2, "Shared summary")
    with pytest.raises(ValueError, match="validation"):
        model.save()
    assert snapshot(path.parent) == before
    model.stage_edit(2, "Different summary")
    assert model.errors == {}
    model.save()
    assert [row.summary for row in model.rows][:2] == ["Shared summary", "Different summary"]


def test_duplicate_matching_is_exact(model):
    assert model.stage_edit(1, "visits paris").new_summary == "visits paris"


def test_duplicate_after_shortening_is_rejected(path):
    text = "Long memory " * 10
    path.write_text(json.dumps([{"summary": "Edit me"}, {"summary": clip_memory_text(text)}]), encoding="utf-8")
    model = MemoryBrowserModel(path.parent)
    before = snapshot(path.parent)
    with pytest.raises(ValueError, match="already has"):
        model.stage_edit(1, text)
    assert snapshot(path.parent) == before


def test_batch_can_reuse_vacated_summary_after_revising_earlier_edit(model, path):
    model.stage_edit(1, "Temporary")
    model.stage_edit(2, "Different")
    model.stage_edit(1, "Visits Paris")
    model.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["summary"] for entry in saved] == ["Visits Paris", "Different", "Undated memory"]


def test_clock_is_used_only_when_saving_changed_entries(path):
    calls = []

    def clock():
        calls.append(True)
        return NOW

    model = MemoryBrowserModel(path.parent, now=clock)
    model.stage_edit(1, " Likes Coffee ")
    model.stage_edit(2, "Changed")
    assert calls == []
    model.save()
    assert calls == [True]


def test_discard_clears_edits_and_errors_without_writing(model, path):
    before = snapshot(path.parent)
    model.stage_edit(1, "Changed")
    with pytest.raises(ValueError):
        model.stage_edit(2, "")
    model.discard()
    assert not model.has_pending_changes
    assert model.errors == {}
    assert model.rows[1].summary == "Likes Coffee"
    assert model.save() == "No changes to save."
    assert snapshot(path.parent) == before


@pytest.mark.parametrize("existing_backup", [False, True])
def test_save_all_edits_with_backup_and_only_changed_timestamps(model, path, entries, existing_backup):
    backup = path.with_name("memory.json.bak")
    if existing_backup:
        backup.write_bytes(b"previous backup")
    before = path.read_bytes()
    model.stage_edit(1, "  Likes\nCoffee  ")
    model.stage_edit(2, "Visits Rome")
    model.stage_edit(3, "Now dated")
    assert model.save() == f"Saved 2 memories. Backup: {backup}"
    assert backup.read_bytes() == before
    assert json.loads(path.read_text(encoding="utf-8")) == [
        entries[0],
        {**entries[1], "summary": "Visits Rome", "updated_at": NOW},
        {**entries[2], "summary": "Now dated", "updated_at": NOW},
    ]
    assert not model.has_pending_changes
    assert [row.index for row in model.rows] == [2, 3, 1]
    before = snapshot(path.parent)
    assert model.save() == "No changes to save."
    assert snapshot(path.parent) == before


def test_no_pending_changes_or_reverted_edit_does_not_write(model, path):
    before = snapshot(path.parent)
    assert model.save() == "No changes to save."
    model.stage_edit(1, "Changed")
    model.stage_edit(1, " Likes\nCoffee ")
    assert not model.has_pending_changes
    assert model.save() == "No changes to save."
    assert snapshot(path.parent) == before


def test_invalid_replacement_removes_previous_pending_value(model, path):
    before = snapshot(path.parent)
    model.stage_edit(1, "Changed")
    with pytest.raises(ValueError):
        model.stage_edit(1, "")
    assert not model.has_pending_changes
    with pytest.raises(ValueError):
        model.save()
    assert snapshot(path.parent) == before


def test_load_and_save_preserve_all_raw_entries(path):
    entries = [{"summary": f"Original {i} " * 10, "custom": {"index": i}} for i in range(30)]
    path.write_text(json.dumps(entries), encoding="utf-8")
    model = MemoryBrowserModel(path.parent, now=lambda: NOW)
    assert len(model.rows) == 30
    assert model.rows[0].summary == entries[0]["summary"]
    model.stage_edit(30, "Last corrected")
    model.save()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved[:-1] == entries[:-1]
    assert saved[-1] == {**entries[-1], "summary": "Last corrected", "updated_at": NOW}


def test_injected_store_is_not_mutated_until_save(path):
    store = MemoryStore(path)
    model = MemoryBrowserModel(store=store, now=lambda: NOW)
    model.stage_edit(1, "Changed")
    assert store.items[0]["summary"] == "Likes Coffee"
    model.save()
    assert store.items[0]["summary"] == "Changed"
    assert store.items[0]["updated_at"] == NOW


def test_missing_file_is_empty_and_readonly(tmp_path):
    data_dir = tmp_path / "absent"
    model = MemoryBrowserModel(data_dir)
    assert model.rows == []
    assert model.save() == "No changes to save."
    assert not data_dir.exists()


@pytest.mark.parametrize("contents", ["{broken", "{}", '[{"summary": null}]'])
def test_invalid_file_is_reported(tmp_path, contents):
    (tmp_path / "memory.json").write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError):
        MemoryBrowserModel(tmp_path)


def test_failed_atomic_write_preserves_file_and_pending_edits(model, path, monkeypatch):
    before = path.read_bytes()
    model.stage_edit(1, "Changed")

    def fail_replace(*args, **kwargs):
        raise OSError("replacement failed")

    monkeypatch.setattr("os.replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        model.save()
    assert path.read_bytes() == before
    assert path.with_name("memory.json.bak").read_bytes() == before
    assert model.has_pending_changes
    assert model.rows[1].summary == "Likes Coffee"
    assert {p.name for p in path.parent.iterdir()} == {"memory.json", "memory.json.bak"}


def test_backup_precedes_write_and_store_failure_preserves_state(path, monkeypatch):
    original = path.read_bytes()
    store = MemoryStore(path)
    old_items = store.items
    old_limit = store.limit
    model = MemoryBrowserModel(store=store)
    model.stage_edit(1, "Changed")

    def fail_save():
        assert path.with_name("memory.json.bak").read_bytes() == original
        raise OSError("write failed")

    with monkeypatch.context() as patch:
        patch.setattr(store, "save", fail_save)
        with pytest.raises(OSError, match="write failed"):
            model.save()
    assert path.read_bytes() == original
    assert store.items is old_items
    assert store.limit == old_limit
    assert model.has_pending_changes
    model.save()
    assert not model.has_pending_changes


def test_browser_import_has_no_gui_or_tts_dependencies():
    script = """
import importlib.abc
import sys

class BlockOptionalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PyQt6', 'PyQt5', 'edge_tts'}:
            raise AssertionError(f'Unexpected optional dependency: {fullname}')

sys.meta_path.insert(0, BlockOptionalDependencies())
from companion.core.memory.browser import MemoryBrowserModel
"""
    result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
