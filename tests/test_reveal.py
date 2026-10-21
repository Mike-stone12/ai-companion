from companion.core.reveal import RevealPolicy


def test_hidden_until_the_pointer_arrives_then_lingers_briefly():
    policy = RevealPolicy(hide_delay=1.5, message_hold=8.0)
    assert policy.visible(0.0, hovered=False, engaged=False) is False
    assert policy.visible(1.0, hovered=True, engaged=False) is True
    # The pointer left at 1.0; the chat stays for the hide delay so a brief slip does not flicker.
    assert policy.visible(2.0, hovered=False, engaged=False) is True
    assert policy.visible(2.6, hovered=False, engaged=False) is False


def test_stays_while_engaged_even_without_the_pointer():
    policy = RevealPolicy(hide_delay=1.5, message_hold=8.0)
    for now in (0.0, 5.0, 60.0):
        assert policy.visible(now, hovered=False, engaged=True) is True
    assert policy.visible(61.0, hovered=False, engaged=False) is True
    assert policy.visible(61.6, hovered=False, engaged=False) is False


def test_a_new_message_shows_the_chat_for_a_while():
    policy = RevealPolicy(hide_delay=1.5, message_hold=8.0)
    policy.note_message(10.0)
    assert policy.visible(10.0, hovered=False, engaged=False) is True
    assert policy.visible(17.9, hovered=False, engaged=False) is True
    assert policy.visible(18.1, hovered=False, engaged=False) is False


def test_a_message_never_shortens_a_longer_reveal():
    policy = RevealPolicy(hide_delay=20.0, message_hold=8.0)
    assert policy.visible(0.0, hovered=True, engaged=False) is True
    policy.note_message(1.0)
    assert policy.visible(15.0, hovered=False, engaged=False) is True


def test_reset_hides_at_once():
    policy = RevealPolicy(hide_delay=1.5, message_hold=8.0)
    policy.note_message(0.0)
    policy.reset()
    assert policy.visible(0.1, hovered=False, engaged=False) is False
