import ctypes
import importlib.util
import logging
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest

from companion.adapters import active_app


def test_macos_success(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, stdout="  Safari\n"))
    assert active_app.foreground_app_name(runner=runner) == "Safari"
    runner.assert_called_once_with(
        [
            "osascript", "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ],
        capture_output=True, text=True, timeout=2,
    )


@pytest.mark.parametrize("returncode, stdout", [(1, "Safari"), (0, ""), (0, " \n\t")])
def test_macos_unsuccessful_result(returncode, stdout, caplog):
    runner = Mock(return_value=subprocess.CompletedProcess([], returncode, stdout=stdout))
    with caplog.at_level(logging.DEBUG, logger=active_app.__name__):
        assert active_app.foreground_app_name(platform="darwin", runner=runner) is None
    assert caplog.records and all(record.levelno == logging.DEBUG for record in caplog.records)


@pytest.mark.parametrize("error", [subprocess.TimeoutExpired("osascript", 2), OSError("unavailable")])
def test_macos_errors(error, caplog):
    runner = Mock(side_effect=error)
    with caplog.at_level(logging.DEBUG, logger=active_app.__name__):
        assert active_app.foreground_app_name(platform="darwin", runner=runner) is None
    assert "Foreground application query failed" in caplog.text


@pytest.mark.parametrize("platform", ["linux", "freebsd", "unknown"])
def test_unsupported_platform(platform, caplog):
    runner, query = Mock(), Mock()
    with caplog.at_level(logging.DEBUG, logger=active_app.__name__):
        assert active_app.foreground_app_name(platform=platform, runner=runner, windows_query=query) is None
    runner.assert_not_called()
    query.assert_not_called()
    assert "unsupported" in caplog.text


@pytest.mark.parametrize("name, expected", [("Game", "Game"), (None, None), ("", None)])
def test_windows_injected_query(name, expected):
    query = Mock(return_value=name)
    assert active_app.foreground_app_name(platform="win32", windows_query=query) == expected
    query.assert_called_once_with()


def test_windows_query_exception(caplog):
    with caplog.at_level(logging.DEBUG, logger=active_app.__name__):
        assert active_app.foreground_app_name(
            platform="win32", windows_query=Mock(side_effect=OSError("access denied")),
        ) is None
    assert "Foreground application query failed" in caplog.text


def test_import_does_not_access_windll(monkeypatch):
    class GuardedCtypes(ModuleType):
        def __getattr__(self, name):
            if name == "windll":
                pytest.fail("Import must not access ctypes.windll")
            return getattr(ctypes, name)

    monkeypatch.setitem(sys.modules, "ctypes", GuardedCtypes("ctypes"))
    spec = importlib.util.spec_from_file_location("isolated_active_app_adapter", active_app.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.foreground_app_name)


@pytest.fixture
def windows_api(monkeypatch):
    from ctypes import wintypes

    def get_process_id(window, process_id):
        ctypes.cast(process_id, ctypes.POINTER(wintypes.DWORD)).contents.value = 42
        return 7

    def get_image_name(handle, flags, path, size):
        path.value = r"C:\Program Files\Game\My.Game.exe"
        return True

    user32 = SimpleNamespace(
        GetForegroundWindow=Mock(return_value=123),
        GetWindowThreadProcessId=Mock(side_effect=get_process_id),
    )
    kernel32 = SimpleNamespace(
        OpenProcess=Mock(return_value=456),
        QueryFullProcessImageNameW=Mock(side_effect=get_image_name),
        CloseHandle=Mock(return_value=True),
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(user32=user32, kernel32=kernel32), raising=False)
    return user32, kernel32


def test_windows_ctypes_success_and_handle_cleanup(windows_api):
    user32, kernel32 = windows_api
    assert active_app.foreground_app_name(platform="win32") == "My.Game"
    user32.GetForegroundWindow.assert_called_once_with()
    kernel32.OpenProcess.assert_called_once_with(0x1000, False, 42)
    kernel32.CloseHandle.assert_called_once_with(456)


@pytest.mark.parametrize("error", [None, OSError("query failed")])
def test_windows_closes_handle_on_query_failure(windows_api, error):
    _, kernel32 = windows_api
    kernel32.QueryFullProcessImageNameW.side_effect = error
    kernel32.QueryFullProcessImageNameW.return_value = False
    assert active_app.foreground_app_name(platform="win32") is None
    kernel32.CloseHandle.assert_called_once_with(456)


@pytest.mark.parametrize("failure", ["window", "process_id", "open"])
def test_windows_failure_before_opening_handle(windows_api, failure):
    user32, kernel32 = windows_api
    if failure == "window":
        user32.GetForegroundWindow.return_value = 0
    elif failure == "process_id":
        user32.GetWindowThreadProcessId.side_effect = None
        user32.GetWindowThreadProcessId.return_value = 0
    else:
        kernel32.OpenProcess.return_value = None
    assert active_app.foreground_app_name(platform="win32") is None
    kernel32.QueryFullProcessImageNameW.assert_not_called()
    kernel32.CloseHandle.assert_not_called()
