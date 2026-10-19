from dataclasses import FrozenInstanceError, dataclass

import pytest

from companion.core.wake_word import WakeWordHit, WakeWordMatcher, normalize_wake_text


@dataclass
class FakeClock:
    now: float = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("text,expected", [
    ("Hey, Whale!", "heywhale"),
    ("hey whale", "heywhale"),
    ("ＨＥＹ，　Ｗｈａｌｅ！", "heywhale"),
    ("\tHey\n\u00a0Whale\r", "heywhale"),
    ("小鲸，小鲸", "小鲸小鲸"),
    ("小鲸小鲸", "小鲸小鲸"),
    ("「小鲸」 。！？、\u3000小鲸…—", "小鲸小鲸"),
    ("", ""),
    (" ，。！？、 \t\n", ""),
])
def test_normalize_wake_text(text, expected):
    assert normalize_wake_text(text) == expected


@pytest.mark.parametrize("phrases", [[], (), [""], [" \t\n"], ["，。！？、"], ["hey whale", "！"]])
def test_invalid_phrases(phrases):
    with pytest.raises(ValueError):
        WakeWordMatcher(phrases)


def test_negative_cooldown():
    with pytest.raises(ValueError):
        WakeWordMatcher(["hey whale"], cooldown_seconds=-0.1)


@pytest.mark.parametrize("phrase,text", [
    ("Hey, Whale!", "well ＨＥＹ　ＷＨＡＬＥ！ please listen"),
    ("小鲸，小鲸", "你好，小鲸小鲸！听我说"),
])
def test_partial_hit_preserves_original_phrase_and_timestamp(phrase, text):
    clock = FakeClock(12.5)
    matcher = WakeWordMatcher([phrase], clock=clock)
    assert matcher.feed(text, final=False) == WakeWordHit(phrase=phrase, at=12.5)


def test_hit_is_frozen():
    hit = WakeWordHit(phrase="hey whale", at=0.0)
    with pytest.raises(FrozenInstanceError):
        hit.phrase = "other"
    with pytest.raises(FrozenInstanceError):
        hit.at = 1.0


def test_utterance_stays_latched_until_final_even_after_cooldown():
    clock = FakeClock()
    matcher = WakeWordMatcher(["hey whale", "小鲸"], clock=clock)
    assert matcher.feed("hey whale", final=False) == WakeWordHit("hey whale", 0.0)
    clock.now = 10.0
    assert matcher.feed("小鲸", final=False) is None
    assert matcher.feed("unrelated text", final=False) is None
    assert matcher.feed("hey whale 小鲸", final=True) is None
    assert matcher.feed("小鲸", final=False) == WakeWordHit("小鲸", 10.0)


def test_final_can_trigger_and_immediately_rearm_with_zero_cooldown():
    matcher = WakeWordMatcher(("hey whale",), cooldown_seconds=0, clock=FakeClock())
    assert matcher.feed("hey whale", final=True) == WakeWordHit("hey whale", 0.0)
    assert matcher.feed("hey whale", final=True) == WakeWordHit("hey whale", 0.0)


@pytest.mark.parametrize("cooldown", [3.0, 7.5])
def test_cooldown_blocks_across_utterances_and_expires_at_boundary(cooldown):
    clock = FakeClock()
    matcher = WakeWordMatcher(["hey whale"], cooldown_seconds=cooldown, clock=clock)
    assert matcher.feed("hey whale", final=True) == WakeWordHit("hey whale", 0.0)
    clock.now = cooldown - 0.01
    assert matcher.feed("hey whale", final=False) is None
    assert matcher.feed("hey whale", final=True) is None
    clock.now = cooldown
    assert matcher.feed("hey whale", final=False) == WakeWordHit("hey whale", cooldown)


def test_cooldown_blocked_partial_does_not_latch_utterance():
    clock = FakeClock()
    matcher = WakeWordMatcher(["hey whale"], clock=clock)
    assert matcher.feed("hey whale", final=True) is not None
    clock.now = 2.0
    assert matcher.feed("hey whale", final=False) is None
    clock.now = 3.0
    assert matcher.feed("hey whale", final=True) == WakeWordHit("hey whale", 3.0)


@pytest.mark.parametrize("phrases,text,expected", [
    (["hey whale", "小鲸"], "先说小鲸，再说 hey whale", "小鲸"),
    (["whale", "hey whale"], "Hey, whale!", "hey whale"),
    (["hey", "hey whale"], "hey whale", "hey"),
    (["hey whale", "hey"], "hey whale", "hey whale"),
    (["Hey, Whale!", "hey whale"], "hey whale", "Hey, Whale!"),
])
def test_choose_earliest_match_then_configuration_order(phrases, text, expected):
    matcher = WakeWordMatcher(phrases, clock=FakeClock())
    assert matcher.feed(text, final=True) == WakeWordHit(expected, 0.0)


@pytest.mark.parametrize("text", ["", " \t\n\u3000", "，。！？"])
def test_empty_partial_preserves_latch_and_empty_final_rearms(text):
    matcher = WakeWordMatcher(["hey whale"], cooldown_seconds=0, clock=FakeClock())
    assert matcher.feed(text, final=False) is None
    assert matcher.feed("hey whale", final=False) is not None
    assert matcher.feed(text, final=False) is None
    assert matcher.feed("hey whale", final=False) is None
    assert matcher.feed(text, final=True) is None
    assert matcher.feed("hey whale", final=False) is not None


def test_empty_final_preserves_cooldown():
    clock = FakeClock()
    matcher = WakeWordMatcher(["hey whale"], clock=clock)
    assert matcher.feed("hey whale", final=False) is not None
    assert matcher.feed("", final=True) is None
    assert matcher.feed("hey whale", final=False) is None
    clock.now = 3.0
    assert matcher.feed("hey whale", final=False) is not None


def test_nonmatching_input_does_not_prevent_later_hit():
    matcher = WakeWordMatcher(["hey whale"], clock=FakeClock())
    assert matcher.feed("hello there", final=True) is None
    assert matcher.feed("hey", final=False) is None
    assert matcher.feed("hey whale", final=True) == WakeWordHit("hey whale", 0.0)


def test_reset_clears_latch_and_cooldown():
    matcher = WakeWordMatcher(["hey whale"], clock=FakeClock())
    matcher.reset()
    assert matcher.feed("hey whale", final=False) == WakeWordHit("hey whale", 0.0)
    matcher.reset()
    assert matcher.feed("hey whale", final=False) == WakeWordHit("hey whale", 0.0)
