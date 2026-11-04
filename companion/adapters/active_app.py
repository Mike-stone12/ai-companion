"""Best-effort foreground application names, without inspecting window titles."""

import ctypes
import logging
import ntpath
import subprocess
import sys
from collections.abc import Callable

logger = logging.getLogger(__name__)

_FRONTMOST_SCRIPT = 'tell application "System Events" to get name of first application process whose frontmost is true'


def _windows_app_name() -> str | None:
    from ctypes import wintypes

    # Load Windows libraries only on demand; explicit signatures preserve 64-bit handles.
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    window = user32.GetForegroundWindow()
    if not window:
        return None
    process_id = wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(window, ctypes.byref(process_id)) or not process_id.value:
        raise OSError("GetWindowThreadProcessId failed")
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, process_id.value)
    if not handle:
        raise OSError("OpenProcess failed")
    try:
        path = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(path))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
            raise OSError("QueryFullProcessImageNameW failed")
        return ntpath.splitext(ntpath.basename(path.value))[0]
    finally:
        if not kernel32.CloseHandle(handle):
            raise OSError("CloseHandle failed")


def foreground_app_name(
    *,
    platform: str | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    windows_query: Callable[[], str | None] | None = None,
) -> str | None:
    """Return a case-preserving name suitable for ActiveAppTrigger.record_sample.

    macOS returns the application process name; Windows returns the executable's
    basename without its extension. Unavailable samples return None. Dependencies
    can be injected to avoid OS calls in tests.
    """
    try:
        platform = sys.platform if platform is None else platform
        if platform == "darwin":
            result = (subprocess.run if runner is None else runner)(
                ["osascript", "-e", _FRONTMOST_SCRIPT], capture_output=True, text=True, timeout=2,
            )
            if result.returncode != 0:
                logger.debug("Foreground application query exited with status %s", result.returncode)
                return None
            name = result.stdout
        elif platform == "win32":
            name = (_windows_app_name if windows_query is None else windows_query)()
        else:
            logger.debug("Foreground application query unsupported on %s", platform)
            return None
        if isinstance(name, str) and name.strip():
            return name.strip()
        logger.debug("Foreground application query returned no name")
    except Exception:
        logger.debug("Foreground application query failed", exc_info=True)
    return None
