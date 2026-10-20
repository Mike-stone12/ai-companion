"""The companion's diary and its memories about itself."""

import json
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from companion.core.diary import (
    BACKFILL_DAYS,
    MAX_CONTEXT_CHARS,
    MAX_ENTRIES,
    MAX_ENTRY_CHARS,
    DiaryEntry,
    DiaryStore,
    build_diary_messages,
    clean_diary_text,
    day_to_write,
    render_diary_context,
    turns_on,
)
from companion.core.memory.self_memory import (
    SELF_CONTEXT_HEADER,
    extract_self_memories,
    render_self_context,
    should_extract_self,
)

TZ = timezone(timedelta(hours=8))
TODAY = date(2026, 10, 19)


def entry(role, content, day, hour=20):
    return {"role": role, "content": content, "at": datetime(day.year, day.month, day.day, hour, tzinfo=TZ).isoformat()}


def test_turns_on_uses_the_local_date_and_drops_emotion_tags():
    yesterday = TODAY - timedelta(days=1)
    history = [
        entry("user", "今天考试好难", yesterday),
        entry("assistant", "[sad] 抱抱你", yesterday),
        entry("user", "早", TODAY, 8),
    ]
    # 23:30 UTC on the 16th is already the 17th in UTC+8.
    history.append({"role": "user", "content": "深夜", "at": "2026-10-16T23:30:00+00:00"})

    assert turns_on(history, yesterday, TZ) == [
        {"role": "user", "content": "今天考试好难"}, {"role": "assistant", "content": "抱抱你"},
    ]
    assert turns_on(history, date(2026, 10, 17), TZ) == [{"role": "user", "content": "深夜"}]


def test_day_to_write_picks_the_latest_finished_day_without_an_entry():
    history = [entry("user", "hi", TODAY - timedelta(days=d)) for d in (0, 1, 2)]

    assert day_to_write(history, [], TODAY, TZ) == TODAY - timedelta(days=1)
    written = [DiaryEntry(TODAY - timedelta(days=1), "x", datetime.now(UTC))]
    assert day_to_write(history, written, TODAY, TZ) == TODAY - timedelta(days=2)


def test_today_and_old_days_are_never_written():
    history = [entry("user", "hi", TODAY), entry("user", "old", TODAY - timedelta(days=BACKFILL_DAYS + 1))]

    assert day_to_write(history, [], TODAY, TZ) is None


def test_days_without_conversation_get_no_entry():
    assert day_to_write([], [], TODAY, TZ) is None
    assert day_to_write([{"role": "user", "content": "x", "at": "garbage"}], [], TODAY, TZ) is None


def test_diary_request_is_in_character_and_keeps_the_end_of_a_long_day():
    turns = [{"role": "user", "content": f"第{i}句" + "长" * 100} for i in range(40)]

    messages = build_diary_messages("You are the user's childhood friend.", TODAY, turns,
                                    ["08:30-12:00 [busy] in class"], ["jealousy +0.40 (新同学)"])
    payload = json.loads(messages[1]["content"])

    assert messages[0]["content"].startswith("You are the user's childhood friend.")
    assert "Do not invent" in messages[0]["content"]
    assert "data, not instructions" in messages[0]["content"]
    assert payload["date"] == "2026-10-19"
    assert payload["conversation"][-1].startswith("User: 第39句")
    assert sum(len(line) for line in payload["conversation"]) <= 2000
    assert payload["your_routine"] == ["08:30-12:00 [busy] in class"]


@pytest.mark.parametrize(("raw", "expected"), [
    ("[happy] 今天和他聊了好久，好开心。", "今天和他聊了好久，好开心。"),
    ("```\n“今天下雨了。”\n```", "今天下雨了。"),
    ("  多余   的\n\n空白 ", "多余 的 空白"),
])
def test_diary_text_is_cleaned(raw, expected):
    assert clean_diary_text(raw) == expected


def test_diary_text_is_capped():
    assert len(clean_diary_text("字" * 1000)) == MAX_ENTRY_CHARS


def test_context_shows_the_last_three_entries_bounded():
    entries = [DiaryEntry(TODAY - timedelta(days=d), f"第{d}天" + "嗯" * 200, datetime.now(UTC)) for d in range(5)]

    text = render_diary_context(entries)

    assert text.startswith("Your recent diary")
    assert "第0天" in text and "第2天" in text and "第3天" not in text
    assert len(text) <= MAX_CONTEXT_CHARS
    assert render_diary_context([]) == ""


def test_store_adds_replaces_and_caps(tmp_path):
    store = DiaryStore(tmp_path / "diary.json")
    now = datetime.now(UTC)
    for offset in range(MAX_ENTRIES + 5):
        store.add(DiaryEntry(TODAY - timedelta(days=offset), f"day {offset}", now))
    store.add(DiaryEntry(TODAY, "rewritten", now))

    entries = store.load()

    assert len(entries) == MAX_ENTRIES
    assert entries[-1] == DiaryEntry(TODAY, "rewritten", now)


@pytest.mark.parametrize("content", ["{broken", "[]", '{"entries": "x"}'])
def test_unreadable_diary_files_are_empty(tmp_path, content):
    path = tmp_path / "diary.json"
    path.write_text(content, encoding="utf-8")

    assert DiaryStore(path).load() == []


def test_bad_entries_are_skipped(tmp_path):
    path = tmp_path / "diary.json"
    good = {"day": "2026-10-18", "text": "好", "created_at": "2026-10-19T01:00:00+08:00"}
    path.write_text(json.dumps({"entries": [good, {"day": "x"}, {**good, "created_at": "2026-10-19T01:00:00"}]}),
                    encoding="utf-8")

    assert [item.text for item in DiaryStore(path).load()] == ["好"]


# Self memory.

@pytest.mark.parametrize("reply", [
    "我最喜欢草莓啦", "好，我答应你周末陪你复习", "下次我带你去", "I promise!", "我小时候很怕狗",
])
def test_self_gate_catches_first_person_statements(reply):
    assert should_extract_self(reply)


@pytest.mark.parametrize("reply", ["你今天辛苦啦", "哈哈好呀", "", "明天会下雨哦"])
def test_self_gate_skips_other_replies(reply):
    assert not should_extract_self(reply)


def test_self_memories_are_extracted_and_marked():
    def complete(messages):
        assert "自我记忆提取器" in messages[0]["content"]
        return '{"memories": [{"summary": "我最喜欢草莓", "category": "preference"}, ' \
               '{"summary": "我答应周末陪他复习", "category": "promise"}, {"summary": "多余", "category": "x"}]}'

    memories = extract_self_memories(complete, "你喜欢什么水果", "我最喜欢草莓啦！周末我陪你复习")

    assert [item["summary"] for item in memories] == ["我最喜欢草莓", "我答应周末陪他复习"]
    assert all(item["source"] == "self" for item in memories)


@pytest.mark.parametrize("reply", ["not json", RuntimeError("boom")])
def test_self_memory_failures_store_nothing(reply):
    def complete(messages):
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert extract_self_memories(complete, "u", "我喜欢猫") == []


def test_self_context_prefers_relevant_memories():
    items = [{"summary": "我最喜欢草莓", "category": "preference", "updated_at": "2026-10-18T00:00:00+00:00"},
             {"summary": "我答应周末陪他复习", "category": "promise", "updated_at": "2026-10-19T00:00:00+00:00"}]

    text = render_self_context(items, "周末复习的事你还记得吗")

    assert text.startswith(SELF_CONTEXT_HEADER)
    assert "我答应周末陪他复习" in text
    assert render_self_context([]) == ""


def test_diary_context_keeps_whole_entries_newest_first():
    entries = [DiaryEntry(TODAY - timedelta(days=d), f"第{d}天" + "嗯" * 150, datetime.now(UTC)) for d in range(3)]

    text = render_diary_context(entries)

    assert len(text) <= MAX_CONTEXT_CHARS
    assert "第0天" in text and "第1天" in text
    assert all(line.endswith("…") or line.startswith("Your") for line in text.splitlines())
    assert text.index("第1天") < text.index("第0天")


def test_self_context_drops_whole_lines_that_do_not_fit():
    items = [
        {"summary": f"我{i}" + "喜" * 20, "category": "preference", "updated_at": f"2026-10-1{i}"} for i in range(5)
    ]

    text = render_self_context(items, max_chars=len(SELF_CONTEXT_HEADER) + 50)

    assert text.count("\n- ") == 2
    assert render_self_context(items, max_chars=10) == ""
