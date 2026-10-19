"""Compose short LLM instructions from proactive events without checking policy."""

from .events import ACTIVE_APP, GREETING, IDLE, REMINDER, Event

MAX_REMINDER_TEXT_LENGTH = 200
MAX_APP_NAME_LENGTH = 60
# Instructions travel as a user-role message, so mark them as coming from the app and
# ask for the active persona's voice (defined in the system prompt), spoken to the user.
NOTE_PREFIX = "[Note from the app, not words the user typed] "
IN_CHARACTER = " Say it directly to the user, in character and in your persona's own voice; do not mention this note."


def frame(instruction: str) -> str:
    return f"{NOTE_PREFIX}{instruction}{IN_CHARACTER}"


def _required_text(event: Event, field: str) -> str:
    value = event.payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{event.kind} event requires a non-empty string payload field {field!r}")
    return value


def compose(event: Event) -> str:
    """Return an English instruction asking the companion to speak first.

    Every instruction is wrapped by ``frame``: it is marked as an app note rather
    than user speech, and asks for the current persona's voice addressed to the
    user at the computer (not a third party such as a family member).

    Idle events require no payload and supply no duration. Greetings require
    ``part_of_day`` (night, morning, afternoon, or evening); reminders require
    non-empty string ``text``. Active-app events require a non-empty ``app_name``
    and nonnegative integer ``minutes``. Unknown kinds and missing or invalid required
    fields raise ValueError. All other payload fields, including ``due_at``,
    are ignored. Eligibility and reminder due-time checks belong upstream.

    Reminder whitespace is collapsed, then text is capped at
    MAX_REMINDER_TEXT_LENGTH (200) characters, including a trailing ellipsis
    when truncated. Composition uses only the supplied event, never the
    current clock, so events produced with an injected time are deterministic.
    Active-app names have non-printable characters removed, are trimmed, and
    are capped at MAX_APP_NAME_LENGTH (60) characters. Names that become empty
    after sanitization raise ValueError.
    """
    return frame(_instruction(event))


def _instruction(event: Event) -> str:
    if event.kind == IDLE:
        return "The user has been idle; start a short, friendly check-in."
    if event.kind == GREETING:
        part = _required_text(event, "part_of_day")
        if part not in ("night", "morning", "afternoon", "evening"):
            raise ValueError("greeting event payload field 'part_of_day' must be night, morning, afternoon, or evening")
        return f"It is {part}; start a short, friendly greeting appropriate for this part of the day."
    if event.kind == REMINDER:
        text = " ".join(_required_text(event, "text").split())
        if len(text) > MAX_REMINDER_TEXT_LENGTH:
            text = text[:MAX_REMINDER_TEXT_LENGTH - 1] + "…"
        return f"A reminder is due; give the user a short, friendly reminder about the following: {text}"
    if event.kind == ACTIVE_APP:
        app_name = _required_text(event, "app_name")
        app_name = "".join(char for char in app_name if char.isprintable()).strip()[:MAX_APP_NAME_LENGTH]
        if not app_name:
            raise ValueError("active_app event requires a non-empty printable payload field 'app_name'")
        minutes = event.payload.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 0:
            raise ValueError("active_app event requires a nonnegative integer payload field 'minutes'")
        return (
            f"The user has had {app_name} in the foreground for about {minutes} minutes; "
            "offer them one brief, caring, non-nagging remark."
        )
    raise ValueError(f"Unknown event kind: {event.kind!r}")


def compose_message(event: Event) -> dict[str, str]:
    """Wrap compose(event) in an OpenAI-style user message; propagate ValueError."""
    return {"role": "user", "content": compose(event)}
