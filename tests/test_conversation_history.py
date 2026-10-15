import json

from companion.core.chat.history import ConversationHistory, display_text


def test_entries_round_trip_through_the_file(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "你好呀")
    history.append("assistant", "[happy] 你好！今天想聊点什么？")

    reloaded = ConversationHistory(path)
    assert [(e["role"], e["content"]) for e in reloaded.entries] == [
        ("user", "你好呀"),
        ("assistant", "[happy] 你好！今天想聊点什么？"),
    ]
    assert all(e["at"] for e in reloaded.entries)


def test_history_is_capped_to_the_most_recent_entries(tmp_path):
    history = ConversationHistory(tmp_path / "history.json", max_entries=3)
    for i in range(5):
        history.append("user", f"消息{i}")
    assert [e["content"] for e in ConversationHistory(tmp_path / "history.json").entries] == ["消息2", "消息3", "消息4"]


def test_missing_or_corrupt_file_starts_empty(tmp_path):
    assert ConversationHistory(tmp_path / "missing.json").entries == []
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert ConversationHistory(broken).entries == []


def test_invalid_entries_are_skipped(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps([{"role": "user", "content": "ok"}, {"role": "system", "content": "no"}, "junk", {"role": "user"}]),
        encoding="utf-8",
    )
    assert [e["content"] for e in ConversationHistory(path).entries] == ["ok"]


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    history = ConversationHistory(tmp_path / "nested" / "history.json")
    history.append("user", "hi")
    assert sorted(p.name for p in (tmp_path / "nested").iterdir()) == ["history.json"]


def test_clear_empties_the_file(tmp_path):
    path = tmp_path / "history.json"
    history = ConversationHistory(path)
    history.append("user", "hi")
    history.clear()
    assert ConversationHistory(path).entries == []


def test_messages_for_the_model_keep_role_and_content_only(tmp_path):
    history = ConversationHistory(tmp_path / "history.json")
    history.append("user", "hi")
    history.append("assistant", "[shy] 诶嘿")
    assert history.messages() == [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "[shy] 诶嘿"}]


def test_display_text_strips_the_emotion_tag_from_replies_only():
    assert display_text({"role": "assistant", "content": "[happy] 你好！"}) == "你好！"
    assert display_text({"role": "assistant", "content": "没有标签的回复"}) == "没有标签的回复"
    assert display_text({"role": "user", "content": "[happy] 用户自己写的方括号"}) == "[happy] 用户自己写的方括号"
