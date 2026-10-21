"""Run the window's "chat on hover" callbacks with Qt stand-ins (Qt is unavailable in CI)."""

from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from test_voice_input_qt_adapters import load_class

from companion.core.reveal import RevealPolicy
from companion.core.window_state import WindowState


class FakePart:
    def __init__(self):
        self.visible = True

    def isVisibleTo(self, _parent):
        return self.visible

    def setVisible(self, visible):
        self.visible = visible


class FakeGeometry:
    def __init__(self, window):
        self.window = window

    def contains(self, _point):
        return self.window.pointer_inside


@pytest.fixture
def window():
    clock = SimpleNamespace(now=0.0)
    cls = load_class(
        "companion/ui/main_window.py", "CompanionWindow",
        QWidget=type("QWidget", (), {}), QCursor=SimpleNamespace(pos=lambda: None),
        time=SimpleNamespace(monotonic=lambda: clock.now), deque=deque,
    )
    instance = cls.__new__(cls)
    instance.clock = clock
    instance.pointer_inside = False
    instance.frameGeometry = lambda: FakeGeometry(instance)
    instance.isActiveWindow = lambda: True
    instance.window_state = WindowState(chat_on_hover=True)
    instance.reveal = RevealPolicy(hide_delay=1.5, message_hold=8.0)
    instance.chrome = (FakePart(), FakePart(), FakePart())
    instance.reveal_timer = Mock()
    instance.chat_input = Mock(**{"text.return_value": "", "hasFocus.return_value": False})
    instance.busy = False
    instance.pending_messages = deque()
    instance.message_timer = Mock(**{"isActive.return_value": False})
    instance.pending_image = None
    instance.save_window_state = Mock()
    return instance


def shown(window):
    states = {part.visible for part in window.chrome}
    assert len(states) == 1, "the top bar, chat, and input come and go together"
    return states.pop()


def test_only_the_avatar_until_the_pointer_arrives(window):
    window.apply_chat_on_hover()
    window.reveal_timer.start.assert_called_once()
    assert shown(window) is False

    window.pointer_inside = True
    window.update_reveal()
    assert shown(window) is True

    window.pointer_inside = False
    window.clock.now = 1.0
    window.update_reveal()
    assert shown(window) is True
    window.clock.now = 2.0
    window.update_reveal()
    assert shown(window) is False


@pytest.mark.parametrize("engage", [
    lambda w: w.chat_input.text.configure_mock(return_value="half a sentence"),
    lambda w: w.chat_input.hasFocus.configure_mock(return_value=True),
    lambda w: setattr(w, "busy", True),
    lambda w: w.pending_messages.append("next line"),
    lambda w: w.message_timer.isActive.configure_mock(return_value=True),
    lambda w: setattr(w, "pending_image", "data:image/png;base64,AAAA"),
])
def test_stays_up_while_the_user_is_in_the_middle_of_something(window, engage):
    engage(window)
    window.clock.now = 100.0
    window.update_reveal()
    assert shown(window) is True


def test_an_unfocused_window_with_an_empty_input_is_not_engaged(window):
    window.chat_input.hasFocus.return_value = True
    window.isActiveWindow = lambda: False
    assert window.chat_engaged() is False


def test_turning_it_off_shows_everything_and_saves(window):
    window.apply_chat_on_hover()
    assert shown(window) is False
    window.set_chat_on_hover(False)
    window.reveal_timer.stop.assert_called_once()
    assert shown(window) is True
    assert window.window_state.chat_on_hover is False
    window.save_window_state.assert_called_once()
