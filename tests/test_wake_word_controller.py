import logging
from dataclasses import dataclass

import pytest

from companion.core.wake_word_controller import WakeWordController, WakeWordState


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


def test_state_transitions_notify_only_on_changes():
    changes = []

    def on_state_changed(state):
        assert controller.state == state
        changes.append(state)

    controller = WakeWordController(
        ["hey whale"], lambda phrase: None,
        clock=FakeClock(), on_state_changed=on_state_changed,
    )
    assert controller.state == WakeWordState.STOPPED
    controller.stop()
    controller.suspend()
    controller.resume()
    assert changes == []

    controller.start()
    controller.start()
    controller.resume()
    assert changes == [WakeWordState.LISTENING]
    controller.suspend()
    controller.suspend()
    controller.start()
    assert controller.state == WakeWordState.SUSPENDED
    assert changes == [WakeWordState.LISTENING, WakeWordState.SUSPENDED]
    controller.resume()
    controller.resume()
    controller.stop()
    controller.stop()
    assert controller.state == WakeWordState.STOPPED
    assert changes == [
        WakeWordState.LISTENING, WakeWordState.SUSPENDED,
        WakeWordState.LISTENING, WakeWordState.STOPPED,
    ]


@pytest.mark.parametrize("suspended", [False, True])
def test_ignores_text_while_inactive(suspended):
    wakes = []
    controller = WakeWordController(["hey whale"], wakes.append, clock=FakeClock())
    if suspended:
        controller.start()
        controller.suspend()
    assert controller.feed_transcript("hey whale", final=False) is False
    assert controller.feed_transcript("hey whale", final=True) is False
    assert wakes == []
    if suspended:
        controller.resume()
    else:
        controller.start()
    assert controller.feed_transcript("hey whale", final=True) is True
    assert wakes == ["hey whale"]


def test_match_fires_once_with_original_phrase():
    wakes = []
    controller = WakeWordController(["Hey, Whale!"], wakes.append, clock=FakeClock())
    controller.start()
    assert controller.feed_transcript("hello there", final=True) is False
    assert controller.feed_transcript("hey", final=False) is False
    assert controller.feed_transcript("well hey whale please listen", final=True) is True
    assert wakes == ["Hey, Whale!"]
    assert controller.state == WakeWordState.LISTENING


@pytest.mark.parametrize("cooldown", [None, 7.5])
def test_cooldown_expires_at_boundary_and_suppressed_matches_do_not_extend_it(cooldown):
    clock = FakeClock()
    wakes = []
    kwargs = {} if cooldown is None else {"cooldown_seconds": cooldown}
    controller = WakeWordController(["hey whale"], wakes.append, clock=clock, **kwargs)
    controller.start()
    assert controller.feed_transcript("hey whale", final=True) is True
    clock.now = (3.0 if cooldown is None else cooldown) - 0.01
    assert controller.feed_transcript("hey whale", final=False) is False
    assert controller.feed_transcript("hey whale", final=True) is False
    assert wakes == ["hey whale"]
    clock.now += 0.01
    assert controller.feed_transcript("hey whale", final=True) is True
    assert wakes == ["hey whale", "hey whale"]


@pytest.mark.parametrize("final_text", ["hey whale", "", "unrelated"])
def test_partial_hit_suppresses_partials_and_final_even_after_cooldown(final_text):
    clock = FakeClock()
    wakes = []
    controller = WakeWordController(["hey whale", "hello whale"], wakes.append, clock=clock)
    controller.start()
    assert controller.feed_transcript("hey whale", final=False) is True
    clock.now = 10.0
    assert controller.feed_transcript("hey whale please", final=False) is False
    assert controller.feed_transcript("hello whale", final=False) is False
    assert controller.feed_transcript(final_text, final=True) is False
    assert wakes == ["hey whale"]
    assert controller.feed_transcript("hello whale", final=False) is True
    assert wakes == ["hey whale", "hello whale"]


def test_final_hit_rearms_next_utterance_with_zero_cooldown():
    wakes = []
    controller = WakeWordController(
        ["hey whale"], wakes.append, cooldown_seconds=0, clock=FakeClock(),
    )
    controller.start()
    assert controller.feed_transcript("hey whale", final=True) is True
    assert controller.feed_transcript("hey whale", final=True) is True
    assert wakes == ["hey whale", "hey whale"]


def test_suspend_preserves_utterance_and_ignores_final():
    clock = FakeClock()
    wakes = []
    controller = WakeWordController(["hey whale"], wakes.append, clock=clock)
    controller.start()
    assert controller.feed_transcript("hey whale", final=False) is True
    controller.suspend()
    assert controller.feed_transcript("", final=True) is False
    clock.now = 10.0
    controller.resume()
    assert controller.feed_transcript("hey whale", final=False) is False
    assert controller.feed_transcript("", final=True) is False
    assert controller.feed_transcript("hey whale", final=True) is True
    assert wakes == ["hey whale", "hey whale"]


def test_resume_after_stop_stays_stopped_and_restart_is_fresh():
    changes = []
    wakes = []
    controller = WakeWordController(
        ["hey whale"], wakes.append, clock=FakeClock(), on_state_changed=changes.append,
    )
    controller.start()
    assert controller.feed_transcript("hey whale", final=False) is True
    controller.suspend()
    controller.stop()
    controller.resume()
    assert controller.state == WakeWordState.STOPPED
    assert changes == [WakeWordState.LISTENING, WakeWordState.SUSPENDED, WakeWordState.STOPPED]
    assert controller.feed_transcript("hey whale", final=True) is False
    controller.start()
    assert controller.feed_transcript("hey whale", final=False) is True
    assert wakes == ["hey whale", "hey whale"]


def test_callback_exception_is_logged_without_changing_state_or_bypassing_cooldown(caplog):
    clock = FakeClock()
    wakes = []
    changes = []

    def fail(phrase):
        wakes.append(phrase)
        raise RuntimeError("callback failed")

    controller = WakeWordController(
        ["hey whale"], fail, clock=clock, on_state_changed=changes.append,
    )
    controller.start()
    with caplog.at_level(logging.ERROR, logger="companion.core.wake_word_controller"):
        assert controller.feed_transcript("hey whale", final=False) is True
    assert controller.state == WakeWordState.LISTENING
    assert changes == [WakeWordState.LISTENING]
    assert len(caplog.records) == 1
    assert caplog.records[0].exc_info[0] is RuntimeError
    assert "callback failed" in caplog.text
    assert controller.feed_transcript("hey whale", final=True) is False
    assert controller.feed_transcript("hey whale", final=True) is False
    assert wakes == ["hey whale"]
    clock.now = 3.0
    assert controller.feed_transcript("hey whale", final=True) is True
    assert wakes == ["hey whale", "hey whale"]
