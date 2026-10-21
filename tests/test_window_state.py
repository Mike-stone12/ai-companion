import json
import logging

import pytest

from companion.core.settings_file import load_settings, save_settings, update_section
from companion.core.window_state import (
    MAX_SCALE,
    MIN_OPACITY,
    WindowState,
    clamp_to_screen,
    fits_on_screens,
    load_window_state,
    parse_window_state,
    resized_rect,
    save_window_state,
    scaled_size,
)

SCREEN = (0, 0, 1920, 1080)


def test_defaults_when_section_missing_or_malformed():
    for raw in (None, [], "x", {"x": "left", "y": 10, "scale": "big", "opacity": None}):
        state = parse_window_state(raw)
        assert state == WindowState()
        assert not state.has_position


def test_position_needs_both_coordinates():
    assert parse_window_state({"x": 10}).has_position is False
    assert parse_window_state({"x": 10, "y": 20.7}) == WindowState(x=10, y=20)
    assert parse_window_state({"x": True, "y": 20}).has_position is False


def test_scale_and_opacity_are_clamped_to_the_supported_range():
    state = parse_window_state({"scale": 9, "opacity": 0.01})
    assert state.scale == MAX_SCALE
    assert state.opacity == MIN_OPACITY
    assert parse_window_state({"scale": 1.15, "opacity": 0.85}) == WindowState(scale=1.15, opacity=0.85)


def test_round_trip_keeps_other_settings(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"theme": "dark", "window": {"x": 1, "y": 2}}), encoding="utf-8")

    assert save_window_state(path, WindowState(x=300, y=400, scale=1.3, opacity=0.7)) is True

    assert load_window_state(path) == WindowState(x=300, y=400, scale=1.3, opacity=0.7)
    assert json.loads(path.read_text(encoding="utf-8"))["theme"] == "dark"
    assert not path.with_name("config.json.tmp").exists()


def test_state_without_position_does_not_store_coordinates(tmp_path):
    path = tmp_path / "config.json"
    save_window_state(path, WindowState(scale=0.85))
    saved = json.loads(path.read_text(encoding="utf-8"))["window"]
    assert saved == {"scale": 0.85, "opacity": 1.0, "always_on_top": True, "chat_on_hover": False}


def test_missing_and_broken_config_files_fall_back_to_defaults(tmp_path, caplog):
    assert load_window_state(tmp_path / "missing.json") == WindowState()

    broken = tmp_path / "config.json"
    broken.write_text("{not json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        assert load_window_state(broken) == WindowState()
    assert "unreadable settings file" in caplog.text

    broken.write_text("[1, 2]", encoding="utf-8")
    assert load_settings(broken) == {}


def test_save_creates_the_data_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "config.json"
    save_settings(path, {"a": 1})
    update_section(path, "window", {"scale": 1.0})
    assert load_settings(path) == {"a": 1, "window": {"scale": 1.0}}


def test_save_failure_is_reported_not_raised(tmp_path, caplog):
    blocker = tmp_path / "config.json"
    blocker.mkdir()  # a directory where the file should go makes the write fail
    with caplog.at_level(logging.WARNING):
        assert save_window_state(blocker, WindowState()) is False
    assert "Could not save window state" in caplog.text


def test_scaled_size_rounds_from_the_base_size():
    assert scaled_size((430, 640), 1.0) == (430, 640)
    assert scaled_size((430, 640), 0.7) == (301, 448)
    assert scaled_size((430, 640), 1.5) == (645, 960)


@pytest.mark.parametrize(
    ("window", "screens", "expected"),
    [
        ((100, 100, 430, 640), [SCREEN], True),
        ((1800, 900, 430, 640), [SCREEN], True),  # overhangs the bottom-right corner
        ((2500, 100, 430, 640), [SCREEN], False),  # on an unplugged second monitor
        ((-380, 100, 430, 640), [SCREEN], False),  # only a 50 px sliver visible
        ((-300, 100, 430, 640), [SCREEN], True),  # 130 px visible: still grabbable
        ((100, -600, 430, 640), [SCREEN], False),  # only the bottom 40 px visible
        ((2500, 100, 430, 640), [SCREEN, (1920, 0, 1920, 1080)], True),
    ],
)
def test_fits_on_screens(window, screens, expected):
    assert fits_on_screens(window, screens) is expected


def test_clamp_to_screen_keeps_the_window_inside():
    assert clamp_to_screen((100, 100, 430, 640), SCREEN) == (100, 100)
    assert clamp_to_screen((1700, 800, 430, 640), SCREEN) == (1490, 440)
    assert clamp_to_screen((-50, -50, 430, 640), SCREEN) == (0, 0)
    assert clamp_to_screen((100, 100, 3000, 2000), SCREEN) == (0, 0)


def test_resized_rect_grows_around_the_bottom_centre():
    rect = resized_rect((1000, 400, 430, 640), (645, 960), SCREEN)
    assert rect == (1000 - 108, 400 + 640 - 960, 645, 960)  # (430 - 645) // 2 == -108


def test_resized_rect_is_pulled_back_onto_the_screen():
    assert resized_rect((1472, 448, 430, 640), (645, 960), SCREEN) == (1275, 120, 645, 960)


def test_always_on_top_defaults_on_and_round_trips(tmp_path):
    from companion.core.window_state import WindowState, load_window_state, parse_window_state, save_window_state

    assert parse_window_state({}).always_on_top is True
    assert parse_window_state({"always_on_top": False}).always_on_top is False
    assert parse_window_state({"always_on_top": "no"}).always_on_top is True

    path = tmp_path / "config.json"
    save_window_state(path, WindowState(always_on_top=False))
    assert load_window_state(path).always_on_top is False


def test_chat_on_hover_defaults_off_and_round_trips(tmp_path):
    from companion.core.window_state import WindowState, load_window_state, parse_window_state, save_window_state

    assert parse_window_state({}).chat_on_hover is False
    assert parse_window_state({"chat_on_hover": True}).chat_on_hover is True
    assert parse_window_state({"chat_on_hover": 1}).chat_on_hover is False

    path = tmp_path / "config.json"
    save_window_state(path, WindowState(chat_on_hover=True))
    assert load_window_state(path).chat_on_hover is True
