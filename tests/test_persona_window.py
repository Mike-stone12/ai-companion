"""Run the window's persona callbacks with Qt stand-ins (Qt is unavailable in CI)."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import load_class

from companion.core.chat.emotion import EMOTION_INSTRUCTION
from companion.core.persona import CHILDHOOD_FRIEND, BuiltinPersonas, Persona, PersonaStore, effective_system_prompt


class FakeDialog:
    DialogCode = SimpleNamespace(Accepted=1, Rejected=0)
    result = 0
    edited: Persona | None = None
    instances: list = []

    def __init__(self, provider, current, parent=None, *, first_run=False):
        self.provider, self.current, self.first_run = provider, current, first_run
        FakeDialog.instances.append(self)
        self.deleteLater = Mock()

    def exec(self):
        return FakeDialog.result

    def persona(self):
        return FakeDialog.edited


@pytest.fixture
def window(tmp_path):
    FakeDialog.instances = []
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), PersonaDialog=FakeDialog, EMOTION_INSTRUCTION=EMOTION_INSTRUCTION,
        effective_system_prompt=effective_system_prompt,
    )
    instance = cls.__new__(cls)
    instance.config = SimpleNamespace(system_prompt="")
    instance.personas = BuiltinPersonas()
    instance.persona_store = PersonaStore(tmp_path / "persona.json")
    instance.persona = CHILDHOOD_FRIEND
    instance.messages = [{"role": "system", "content": "old"}, {"role": "user", "content": "hi"}]
    instance.chat_panel = Mock()
    return instance


CUSTOM = Persona.from_dict({"id": "custom", "title": "Custom", "name": "Mio", "personality": "Shy."})


def test_system_message_combines_persona_and_emotion_instruction(window):
    message = window.system_message()

    assert message.startswith(CHILDHOOD_FRIEND.system_prompt())
    assert message.endswith(EMOTION_INSTRUCTION)


def test_apply_persona_saves_it_and_swaps_the_live_system_prompt(window):
    window.apply_persona(CUSTOM)

    assert window.persona == CUSTOM
    assert window.persona_store.load() == CUSTOM
    assert "Your name is Mio." in window.messages[0]["content"]
    assert window.messages[1] == {"role": "user", "content": "hi"}


def test_explicit_system_prompt_override_is_kept_and_reported(window):
    window.config.system_prompt = "Be a pirate."

    window.apply_persona(CUSTOM)

    assert window.messages[0]["content"].startswith("Be a pirate.")
    assert "COMPANION_SYSTEM_PROMPT" in window.chat_panel.add_notice.call_args.args[0]


def test_accepting_the_dialog_applies_the_edited_persona(window):
    FakeDialog.result, FakeDialog.edited = 1, CUSTOM

    window.show_persona_dialog()

    assert window.persona_store.load() == CUSTOM
    assert FakeDialog.instances[0].first_run is False
    assert FakeDialog.instances[0].current == CHILDHOOD_FRIEND


def test_cancelling_an_edit_changes_nothing(window):
    FakeDialog.result = 0

    window.show_persona_dialog()

    assert not window.persona_store.exists()
    assert window.messages[0]["content"] == "old"


def test_first_run_keep_default_saves_the_default_so_it_is_not_asked_again(window):
    FakeDialog.result = 0

    window.show_persona_dialog(first_run=True)

    assert window.persona_store.load() == CHILDHOOD_FRIEND
    assert FakeDialog.instances[0].first_run is True


def test_needs_first_run_setup_only_without_a_saved_persona_or_override(window):
    assert window.needs_persona_setup()
    window.persona_store.save(CHILDHOOD_FRIEND)
    assert not window.needs_persona_setup()


def test_override_skips_first_run_setup(window):
    window.config.system_prompt = "Be a pirate."

    assert not window.needs_persona_setup()
