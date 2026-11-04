"""Window placement the user chose (position, size, opacity), kept under "window" in config.json."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from companion.core.settings_file import load_settings, update_section

logger = logging.getLogger(__name__)

SECTION = "window"

# Menu presets. The limits accept hand-edited values between the presets, nothing wilder.
SCALE_STEPS = (0.7, 0.85, 1.0, 1.15, 1.3, 1.5)
OPACITY_STEPS = (1.0, 0.85, 0.7, 0.55)
MIN_SCALE, MAX_SCALE = SCALE_STEPS[0], SCALE_STEPS[-1]
MIN_OPACITY, MAX_OPACITY = OPACITY_STEPS[-1], OPACITY_STEPS[0]

# A saved position is restored only if at least this much of the window would be on a screen,
# enough to grab the drag bar or right-click for the menu after a monitor was unplugged.
MIN_VISIBLE_WIDTH = 120
MIN_VISIBLE_HEIGHT = 60

Rect = tuple[int, int, int, int]  # x, y, width, height


@dataclass(slots=True)
class WindowState:
    x: int | None = None
    y: int | None = None
    scale: float = 1.0
    opacity: float = 1.0
    # Stay above other windows (the original behaviour); the right-click menu can turn it off.
    always_on_top: bool = True
    # Show only the avatar until the pointer is over the window (companion/core/reveal.py).
    chat_on_hover: bool = False

    @property
    def has_position(self) -> bool:
        return self.x is not None and self.y is not None

    def to_dict(self) -> dict:
        data: dict = {
            "scale": self.scale,
            "opacity": self.opacity,
            "always_on_top": self.always_on_top,
            "chat_on_hover": self.chat_on_hover,
        }
        if self.has_position:
            data["x"] = self.x
            data["y"] = self.y
        return data


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_coordinate(raw: object) -> int | None:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return int(raw)


def parse_factor(raw: object, default: float, low: float, high: float) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return default
    return round(clamp(float(raw), low, high), 3)


def parse_window_state(raw: object) -> WindowState:
    """Build a state from the "window" section; anything missing or malformed takes the default."""
    if not isinstance(raw, dict):
        return WindowState()
    x, y = parse_coordinate(raw.get("x")), parse_coordinate(raw.get("y"))
    if x is None or y is None:
        x = y = None
    return WindowState(
        x=x,
        y=y,
        scale=parse_factor(raw.get("scale"), 1.0, MIN_SCALE, MAX_SCALE),
        opacity=parse_factor(raw.get("opacity"), 1.0, MIN_OPACITY, MAX_OPACITY),
        always_on_top=raw.get("always_on_top") if isinstance(raw.get("always_on_top"), bool) else True,
        chat_on_hover=raw.get("chat_on_hover") is True,
    )


def load_window_state(path: Path) -> WindowState:
    return parse_window_state(load_settings(path).get(SECTION))


def save_window_state(path: Path, state: WindowState) -> bool:
    try:
        update_section(path, SECTION, state.to_dict())
    except OSError as exc:
        logger.warning("Could not save window state to %s: %s", path, exc)
        return False
    return True


def scaled_size(base: tuple[int, int], scale: float) -> tuple[int, int]:
    width, height = base
    return max(1, round(width * scale)), max(1, round(height * scale))


def intersection(a: Rect, b: Rect) -> tuple[int, int]:
    """Width and height of the overlap of two rectangles (zero when they do not touch)."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    width = min(ax + aw, bx + bw) - max(ax, bx)
    height = min(ay + ah, by + bh) - max(ay, by)
    return max(0, width), max(0, height)


def fits_on_screens(window: Rect, screens: list[Rect]) -> bool:
    """True if enough of the window lands on some screen for the user to reach it."""
    for screen in screens:
        width, height = intersection(window, screen)
        if width >= MIN_VISIBLE_WIDTH and height >= MIN_VISIBLE_HEIGHT:
            return True
    return False


def clamp_to_screen(window: Rect, screen: Rect) -> tuple[int, int]:
    """Top-left corner that keeps the window inside the screen (aligned top-left if it is larger)."""
    x, y, width, height = window
    sx, sy, sw, sh = screen
    return int(clamp(x, sx, max(sx, sx + sw - width))), int(clamp(y, sy, max(sy, sy + sh - height)))


def resized_rect(window: Rect, size: tuple[int, int], screen: Rect) -> Rect:
    """Rect for a new size that keeps the bottom centre where it was, then stays on the screen."""
    x, y, width, height = window
    new_width, new_height = size
    new_x = x + (width - new_width) // 2
    new_y = y + height - new_height
    new_x, new_y = clamp_to_screen((new_x, new_y, new_width, new_height), screen)
    return new_x, new_y, new_width, new_height
