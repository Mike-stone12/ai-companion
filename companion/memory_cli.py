"""Read-only inspection of stored memories, without GUI dependencies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from companion.core.memory.edit import memory_rows


def _nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="override the app's user data directory")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="list memories newest first, with stable file indices")
    listing.add_argument("--limit", type=_nonnegative_int, help="show only the newest N memories")
    search = commands.add_parser("search", help="match summaries by case-insensitive substring")
    search.add_argument("query")
    show = commands.add_parser("show", help="show the full stored entry as JSON")
    show.add_argument("index", type=int, help="1-based index displayed by list or search")
    args = parser.parse_args(argv)

    try:
        # This loads the same .env settings as the app, without initializing it.
        from companion.paths import user_data_dir

        data_dir = args.data_dir.expanduser() if args.data_dir is not None else user_data_dir()
        path = data_dir / "memory.json"
    except (OSError, ValueError) as exc:
        print(f"Error resolving data directory: {exc}", file=sys.stderr)
        return 1

    try:
        # MemoryStore.load normalizes, clips and limits entries and swallows read
        # errors. Inspection needs the complete stored JSON and explicit errors.
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or not isinstance(entry.get("summary"), str) for entry in entries
        ):
            raise ValueError("expected a JSON list of memory objects with string summaries")
    except FileNotFoundError:
        print(f"No memories found (checked {path}).")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Error reading {path}: {exc}", file=sys.stderr)
        return 1

    if args.command == "show":
        if not 1 <= args.index <= len(entries):
            print(f"Error: memory index {args.index} is out of range ({len(entries)} memories).", file=sys.stderr)
            return 1
        print(json.dumps(entries[args.index - 1], ensure_ascii=False, indent=2))
        return 0

    if not entries:
        print(f"No memories found (checked {path}).")
        return 0

    rows = memory_rows(entries)
    if args.command == "list" and args.limit is not None:
        rows = rows[: args.limit]
    elif args.command == "search":
        rows = [row for row in rows if args.query.casefold() in row.summary.casefold()]
    for row in rows:
        timestamp = f" [{row.timestamp}]" if row.timestamp else ""
        # Keep each memory on one line, even for manually authored summaries.
        summary = " ".join(row.summary.splitlines())
        print(f"{row.index + 1}.{timestamp} {summary}")
    return 0


if __name__ == "__main__":
    # Windows redirected streams may otherwise use a legacy code page.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
