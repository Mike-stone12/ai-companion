"""Daily schedule: parsing the editable text, finding the current block, JSON round trip."""

from datetime import UTC, datetime, time

import pytest

from companion.core.schedule import (
    DEFAULT_SCHEDULE,
    MAX_BLOCKS,
    ScheduleBlock,
    block_at,
    format_schedule,
    parse_schedule,
    presence_label,
    schedule_from_list,
    schedule_to_list,
)


def at(hour, minute=0):
    return datetime(2026, 10, 19, hour, minute, tzinfo=UTC)


def test_parse_lines_with_and_without_a_kind():
    blocks = parse_schedule("""
        # comment
        08:30-12:00 [busy] in class
        19:00-23:30 watching a drama
        00:30-07:30 [asleep] sleeping
    """)

    assert blocks == (
        ScheduleBlock(time(8, 30), time(12, 0), "in class", "busy"),
        ScheduleBlock(time(19, 0), time(23, 30), "watching a drama", "free"),
        ScheduleBlock(time(0, 30), time(7, 30), "sleeping", "asleep"),
    )


@pytest.mark.parametrize(("text", "line"), [
    ("8-12 class", 1),
    ("08:30-12:00 [nap] napping", 1),
    ("08:30-12:00", 1),
    ("08:30-08:30 nothing", 1),
    ("09:00-10:00 ok\n25:00-26:00 bad", 2),
])
def test_invalid_lines_name_the_line(text, line):
    with pytest.raises(ValueError, match=f"line {line}"):
        parse_schedule(text)


def test_too_many_blocks_are_rejected():
    text = "\n".join(f"{hour:02d}:00-{hour:02d}:30 a" for hour in range(MAX_BLOCKS + 1))

    with pytest.raises(ValueError, match="at most"):
        parse_schedule(text)


def test_activity_is_capped_and_cleaned():
    (block,) = parse_schedule("09:00-10:00 " + "x" * 200 + "\x00")

    assert len(block.activity) == 60
    assert "\x00" not in block.activity


def test_format_round_trips():
    assert parse_schedule(format_schedule(DEFAULT_SCHEDULE)) == DEFAULT_SCHEDULE


def test_block_at_handles_blocks_across_midnight():
    blocks = parse_schedule("23:30-00:30 [drowsy] getting ready for bed\n00:30-07:30 [asleep] sleeping")

    assert block_at(blocks, at(23, 45)).kind == "drowsy"
    assert block_at(blocks, at(0, 10)).kind == "drowsy"
    assert block_at(blocks, at(0, 30)).kind == "asleep"
    assert block_at(blocks, at(7, 29)).kind == "asleep"
    assert block_at(blocks, at(7, 30)) is None


def test_default_schedule_is_a_full_childhood_friend_day():
    kinds = {block_at(DEFAULT_SCHEDULE, at(hour)).kind for hour in range(24)}

    assert kinds == {"free", "busy", "drowsy", "asleep"}
    assert block_at(DEFAULT_SCHEDULE, at(3)).kind == "asleep"
    assert block_at(DEFAULT_SCHEDULE, at(10)).kind == "busy"
    assert block_at(DEFAULT_SCHEDULE, at(23, 45)).kind == "drowsy"
    assert all(block_at(DEFAULT_SCHEDULE, at(hour)) is not None for hour in range(24))


def test_json_round_trip_and_validation():
    assert schedule_from_list(schedule_to_list(DEFAULT_SCHEDULE)) == DEFAULT_SCHEDULE
    with pytest.raises(ValueError):
        schedule_from_list([{"start": "09:00", "end": "10:00", "activity": 3}])
    with pytest.raises(ValueError):
        schedule_from_list("not a list")


def test_presence_label():
    assert presence_label(None) == "Online"
    assert presence_label(ScheduleBlock(time(0), time(7), "sleeping", "asleep")) == "Asleep"
    assert presence_label(ScheduleBlock(time(19), time(23), "watching a drama", "free")) == "Watching a drama"
