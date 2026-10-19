"""Persona data, presets, persistence, and the system prompt built from them."""

import json

import pytest

from companion.core.persona import (
    CHILDHOOD_FRIEND,
    DEFAULT_PERSONA_ID,
    FIELD_LIMITS,
    SCHEMA_VERSION,
    BuiltinPersonas,
    Persona,
    PersonaStore,
    effective_system_prompt,
)


def test_default_persona_is_the_childhood_friend():
    assert DEFAULT_PERSONA_ID == CHILDHOOD_FRIEND.id == "childhood_friend"
    prompt = CHILDHOOD_FRIEND.system_prompt()
    assert "childhood friend" in prompt.lower()
    # Talks to the person at the computer, in character, without inventing shared history.
    assert "directly to the user" in prompt
    assert "Do not invent" in prompt


def test_builtin_provider_lists_presets_and_finds_by_id():
    provider = BuiltinPersonas()

    assert provider.presets()[0] == CHILDHOOD_FRIEND
    assert provider.get("childhood_friend") == CHILDHOOD_FRIEND
    assert provider.get("missing") is None
    assert provider.default() == CHILDHOOD_FRIEND


def test_prompt_includes_only_filled_fields():
    persona = Persona(
        id="custom", title="Custom", name="Mio", user_name="Ken",
        relationship="Your older sister.", personality="Calm.", speaking_style="", background="",
    )

    prompt = persona.system_prompt()

    assert "Your name is Mio." in prompt
    assert 'Call the user "Ken".' in prompt
    assert "Relationship to the user: Your older sister." in prompt
    assert "Personality: Calm." in prompt
    assert "Speaking style:" not in prompt
    assert "Background:" not in prompt


def test_unnamed_persona_lets_the_user_choose_a_name():
    assert "no fixed name" in CHILDHOOD_FRIEND.system_prompt()


def test_round_trip_through_dict():
    assert Persona.from_dict(CHILDHOOD_FRIEND.to_dict()) == CHILDHOOD_FRIEND


def test_from_dict_strips_caps_and_drops_control_characters():
    data = {
        "id": "custom", "title": "  Mine  ", "name": "Mi\x00o\n", "relationship": "x" * 5000,
        "personality": "kind\r\nand calm", "unknown": "ignored",
    }

    persona = Persona.from_dict(data)

    assert persona.title == "Mine"
    assert persona.name == "Mio"
    assert len(persona.relationship) == FIELD_LIMITS["relationship"]
    # Newlines are kept inside long fields, carriage returns normalized.
    assert persona.personality == "kind\nand calm"


def test_from_dict_rejects_non_objects_and_non_string_fields():
    with pytest.raises(ValueError):
        Persona.from_dict(["not", "an", "object"])
    with pytest.raises(ValueError):
        Persona.from_dict({"id": "custom", "title": "x", "name": 3})


def test_from_dict_fills_missing_fields_from_defaults():
    persona = Persona.from_dict({"id": "custom", "title": "Bare"})

    assert persona.name == ""
    assert persona.relationship == ""
    assert persona.id == "custom"


def test_from_dict_requires_some_identity():
    persona = Persona.from_dict({})

    assert persona.id == "custom"
    assert persona.title == "Custom"


def test_store_reports_first_run_until_saved(tmp_path):
    store = PersonaStore(tmp_path / "persona.json")

    assert not store.exists()
    assert store.load() is None

    store.save(CHILDHOOD_FRIEND)

    assert store.exists()
    assert store.load() == CHILDHOOD_FRIEND
    saved = json.loads((tmp_path / "persona.json").read_text(encoding="utf-8"))
    assert saved["version"] == SCHEMA_VERSION
    assert saved["persona"]["id"] == "childhood_friend"


def test_store_keeps_non_ascii_text_readable(tmp_path):
    path = tmp_path / "persona.json"
    PersonaStore(path).save(Persona.from_dict({"id": "custom", "title": "自定义", "name": "小雨"}))

    assert "小雨" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("content", ["{not json", "[]", '{"version": 1, "persona": 5}'])
def test_corrupt_store_falls_back_to_none_without_raising(tmp_path, content):
    path = tmp_path / "persona.json"
    path.write_text(content, encoding="utf-8")

    store = PersonaStore(path)

    assert store.load() is None
    # The file exists, so the first-run dialog is not shown again over a broken file.
    assert store.exists()


def test_active_persona_prefers_saved_then_default(tmp_path):
    store = PersonaStore(tmp_path / "persona.json")
    provider = BuiltinPersonas()

    assert store.active(provider) == CHILDHOOD_FRIEND
    custom = Persona.from_dict({"id": "custom", "title": "Custom", "name": "Mio"})
    store.save(custom)
    assert store.active(provider) == custom


def test_explicit_system_prompt_override_wins_over_persona():
    assert effective_system_prompt("Be a pirate.", CHILDHOOD_FRIEND) == "Be a pirate."
    assert effective_system_prompt("   ", CHILDHOOD_FRIEND) == CHILDHOOD_FRIEND.system_prompt()


def test_with_fields_returns_a_validated_copy():
    edited = CHILDHOOD_FRIEND.with_fields(name="  Aoi ", personality="Shy.")

    assert edited.name == "Aoi"
    assert edited.personality == "Shy."
    assert edited.relationship == CHILDHOOD_FRIEND.relationship
    assert edited.id == "custom"
    with pytest.raises(ValueError):
        CHILDHOOD_FRIEND.with_fields(colour="red")


def test_with_fields_keeps_preset_id_when_nothing_changes():
    assert CHILDHOOD_FRIEND.with_fields(name=CHILDHOOD_FRIEND.name) == CHILDHOOD_FRIEND
