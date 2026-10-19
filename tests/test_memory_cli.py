import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from companion.core.memory.store import clip_memory_text
from companion.memory_cli import main


@pytest.fixture
def entries():
    return [
        {"summary": "我喜欢 Coffee 和茶", "updated_at": "2026-10-01T12:00:00+00:00"},
        {"summary": "明天去北京", "updated_at": "2026-10-18T12:00:00+00:00", "custom": {"城市": "北京"}},
        {"summary": "没有日期的记忆"},
    ]


@pytest.fixture
def store(tmp_path, entries):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def run_readonly(tmp_path):
    def run(args):
        files = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in tmp_path.rglob("*") if path.is_file()}
        tree = set(tmp_path.rglob("*"))
        try:
            return main(args)
        finally:
            assert set(tmp_path.rglob("*")) == tree
            for path, (contents, mtime) in files.items():
                assert path.read_bytes() == contents
                assert path.stat().st_mtime_ns == mtime

    return run


def test_list_chinese_and_limit(store, capsys, run_readonly):
    args = ["--data-dir", str(store.parent), "list"]
    assert run_readonly(args) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == [
        "2. [2026-10-18 12:00:00+00:00] 明天去北京",
        "1. [2026-10-01 12:00:00+00:00] 我喜欢 Coffee 和茶",
        "3. 没有日期的记忆",
    ]
    assert run_readonly([*args, "--limit", "1"]) == 0
    assert capsys.readouterr().out.splitlines() == lines[:1]
    assert run_readonly([*args, "--limit", "0"]) == 0
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(("query", "index"), [("cOfFeE", "1."), ("北京", "2."), ("missing", None)])
def test_search(store, query, index, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(store.parent), "search", query]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    if index is None:
        assert output.out == ""
    else:
        assert len(output.out.splitlines()) == 1
        assert output.out.startswith(index)
        assert query.casefold() in output.out.casefold()


def test_show_preserves_full_entry(store, entries, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(store.parent), "show", "2"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output) == entries[1]
    assert '\n  "summary": "明天去北京"' in output
    assert "北京" in output


@pytest.mark.parametrize("index", ["0", "-1", "4"])
def test_show_out_of_range(store, index, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(store.parent), "show", index]) != 0
    output = capsys.readouterr()
    assert output.out == ""
    assert "out of range" in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize("command", [["list"], ["search", "北京"], ["show", "1"]])
def test_missing_file(tmp_path, command, capsys, run_readonly):
    data_dir = tmp_path / "nonexistent"
    assert run_readonly(["--data-dir", str(data_dir), *command]) == 0
    output = capsys.readouterr()
    assert "No memories" in output.out
    assert str(data_dir / "memory.json") in output.out
    assert output.err == ""
    assert not data_dir.exists()


@pytest.mark.parametrize("contents", [b"{broken", b"\xff", b"{}", b'[{"summary": null}]'])
@pytest.mark.parametrize("command", [["list"], ["search", "tea"], ["show", "1"]])
def test_corrupt_file(tmp_path, contents, command, capsys, run_readonly):
    path = tmp_path / "memory.json"
    path.write_bytes(contents)
    assert run_readonly(["--data-dir", str(tmp_path), *command]) != 0
    output = capsys.readouterr()
    assert output.out == ""
    assert "Error reading" in output.err
    assert str(path) in output.err
    assert "Traceback" not in output.err


def test_unreadable_file(store, monkeypatch, capsys, run_readonly):
    original_read = Path.read_text

    def denied(path, *args, **kwargs):
        if path == store:
            raise PermissionError("access denied")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert run_readonly(["--data-dir", str(store.parent), "list"]) != 0
    output = capsys.readouterr()
    assert "access denied" in output.err
    assert "Traceback" not in output.err


def test_environment_override(store, monkeypatch, capsys, run_readonly):
    monkeypatch.setenv("COMPANION_DATA_DIR", str(store.parent))
    assert run_readonly(["list"]) == 0
    assert "明天去北京" in capsys.readouterr().out
    assert run_readonly(["--data-dir", str(store.parent / "other"), "list"]) == 0
    assert "No memories" in capsys.readouterr().out


def test_no_truncation_or_store_limit(store, capsys, run_readonly):
    summary = "很长的记忆" * 30
    entries = [{"summary": summary, "custom": index} for index in range(30)]
    store.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    assert run_readonly(["--data-dir", str(store.parent), "list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 30
    assert lines[-1] == f"30. {summary}"
    assert run_readonly(["--data-dir", str(store.parent), "show", "30"]) == 0
    assert json.loads(capsys.readouterr().out) == entries[-1]


def test_module_entry_point_utf8(store):
    before = (store.read_bytes(), store.stat().st_mtime_ns)
    result = subprocess.run(
        [sys.executable, "-B", "-m", "companion.memory_cli", "--data-dir", str(store.parent), "list"],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "明天去北京" in result.stdout.decode("utf-8")
    assert result.stderr == b""
    assert (store.read_bytes(), store.stat().st_mtime_ns) == before


@pytest.mark.parametrize("summary", ["  Corrected\n\ttext  ", "A long corrected memory " * 8])
def test_edit_dry_run(store, entries, summary, capsys, run_readonly):
    assert run_readonly(["--data-dir", str(store.parent), "edit", "2", summary]) == 0
    output = capsys.readouterr()
    assert f"Old: {entries[1]['summary']}" in output.out
    assert f"New: {clip_memory_text(summary)}" in output.out
    assert "nothing was saved" in output.out.lower()
    assert output.err == ""


@pytest.mark.parametrize("existing_backup", [False, True])
def test_edit_write_preserves_entries_and_backs_up_original(store, existing_backup, capsys):
    # More than the store's usual limit, with fields and summaries load() would normalize.
    entries = [{"summary": f"  Original {index} " * 8, "custom": {"index": index}} for index in range(30)]
    store.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    original = store.read_bytes()
    backup = store.with_name("memory.json.bak")
    if existing_backup:
        backup.write_bytes(b"previous backup")
    assert main(["--data-dir", str(store.parent), "edit", "2", "  Corrected\ntext  ", "--write"]) == 0
    output = capsys.readouterr()
    assert "Saved" in output.out
    assert str(backup) in output.out
    assert output.err == ""
    assert backup.read_bytes() == original
    saved = json.loads(store.read_text(encoding="utf-8"))
    assert len(saved) == len(entries)
    assert saved[:1] == entries[:1]
    assert saved[2:] == entries[2:]
    assert saved[1] == {**entries[1], "summary": "Corrected text", "updated_at": saved[1]["updated_at"]}
    assert saved[1]["updated_at"]
    assert store.read_text(encoding="utf-8") == json.dumps(saved, ensure_ascii=False, indent=2)


@pytest.mark.parametrize("write", [[], ["--write"]])
@pytest.mark.parametrize(("index", "summary", "error"), [
    ("0", "New", "index"),
    ("-1", "New", "index"),
    ("4", "New", "out of range"),
    ("1", "", "empty"),
    ("1", " \n\t ", "empty"),
    ("1", "  Duplicate\ntext  ", "already has"),
    ("1", "Long memory " * 10, "already has"),
])
def test_edit_rejected_without_file_changes(store, index, summary, error, write, capsys, run_readonly):
    entries = [{"summary": "Edit me"}, {"summary": "Duplicate text"},
               {"summary": clip_memory_text("Long memory " * 10)}]
    store.write_text(json.dumps(entries), encoding="utf-8")
    store.with_name("memory.json.bak").write_bytes(b"keep existing backup")
    assert run_readonly(["--data-dir", str(store.parent), "edit", index, summary, *write]) != 0
    output = capsys.readouterr()
    assert error in output.err
    assert "Traceback" not in output.err


@pytest.mark.parametrize("index", ["abc", "1.5"])
def test_edit_noninteger_index(store, index, capsys, run_readonly):
    with pytest.raises(SystemExit) as exc:
        run_readonly(["--data-dir", str(store.parent), "edit", index, "New", "--write"])
    assert exc.value.code != 0
    assert "invalid int value" in capsys.readouterr().err


@pytest.mark.parametrize("write", [[], ["--write"]])
def test_edit_missing_file(tmp_path, write, capsys, run_readonly):
    data_dir = tmp_path / "nonexistent"
    assert run_readonly(["--data-dir", str(data_dir), "edit", "1", "New", *write]) != 0
    output = capsys.readouterr()
    assert str(data_dir / "memory.json") in output.err
    assert "not exist" in output.err
    assert output.out == ""


def test_edit_default_directory(store, monkeypatch, capsys, run_readonly):
    from companion import paths

    monkeypatch.setattr(paths, "user_data_dir", lambda: store.parent)
    assert run_readonly(["edit", "1", "New"]) == 0
    assert "New: New" in capsys.readouterr().out


def test_edit_environment_and_explicit_override(store, monkeypatch, capsys, run_readonly):
    monkeypatch.setenv("COMPANION_DATA_DIR", str(store.parent))
    assert run_readonly(["edit", "1", "New"]) == 0
    assert "New: New" in capsys.readouterr().out
    assert run_readonly(["--data-dir", str(store.parent / "other"), "edit", "1", "New", "--write"]) != 0
    assert "not exist" in capsys.readouterr().err
