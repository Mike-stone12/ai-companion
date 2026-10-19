"""Offline start-up self-check for source and packaged builds: ``main.py --self-test [REPORT]``.

It verifies bundled resources and imports, then (in companion/ui/self_test.py) opens
the real window and waits for the renderer to load the Live2D model. It makes no
network requests, uses a throwaway data directory, and never touches the keychain,
so it is safe in CI and on a user's machine. The exit code is 0 only if every
required check passes; the report goes to stdout (when there is one) and REPORT.

Import nothing from companion at module level: ``prepare`` must set the data
directory before companion.paths is first imported.
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

FLAG = "--self-test"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class SelfTestRequest:
    data_dir: Path
    report_path: Path | None


def prepare(argv: Sequence[str], environ: MutableMapping[str, str] = os.environ) -> SelfTestRequest | None:
    """Return a request when FLAG is present, pointing user data at a temporary directory."""
    if FLAG not in argv:
        return None
    index = list(argv).index(FLAG)
    following = argv[index + 1] if index + 1 < len(argv) else ""
    report = Path(following) if following and not following.startswith("-") else None
    data_dir = Path(tempfile.mkdtemp(prefix="ai-companion-selftest-"))
    environ["COMPANION_DATA_DIR"] = str(data_dir)
    # Read the key from nowhere and never prompt for keychain access.
    environ["COMPANION_KEYCHAIN"] = "0"
    return SelfTestRequest(data_dir, report)


def _check(name: str, probe: Callable[[], str], *, required: bool = True) -> Check:
    try:
        return Check(name, True, probe() or "", required)
    except Exception as exc:  # A self-test reports every failure instead of stopping at the first.
        return Check(name, False, f"{type(exc).__name__}: {exc}", required)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def static_checks(platform: str = sys.platform) -> list[Check]:
    from companion import paths

    def resources() -> str:
        _require(paths.HTML_PATH.is_file(), f"missing {paths.HTML_PATH}")
        return str(paths.APP_DIR)

    def model() -> str:
        from companion.core.model_profile import discover_model_profile

        profile = discover_model_profile("")
        _require(profile is not None and profile.path.is_file(), f"no model under {paths.MODELS_DIR}")
        return profile.path.parent.name

    def vendor() -> str:
        from companion.core.model_profile import discover_vendor_dir

        vendor_dir = discover_vendor_dir()
        _require(vendor_dir is not None, f"missing {paths.VENDOR_DIR}")
        missing = [
            name for name in ("pixi.min.js", "live2dcubismcore.min.js", "cubism4.min.js")
            if not (vendor_dir / name).is_file()
        ]
        _require(not missing, f"missing {', '.join(missing)}")
        return str(vendor_dir)

    def data_dir() -> str:
        probe = paths.DATA_DIR / "self-test.txt"
        probe.parent.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        _require(probe.read_text(encoding="utf-8") == "ok", "data directory is not writable")
        probe.unlink()
        return str(paths.DATA_DIR)

    def imports(*modules: str) -> Callable[[], str]:
        def probe() -> str:
            for module in modules:
                importlib.import_module(module)
            return ", ".join(modules)
        return probe

    def keychain_backend() -> str:
        import keyring

        from companion.core.api_key import ApiKeyStore

        # keyring finds backends through entry points, which a frozen build can lose; the app
        # would then silently fall back to .env. An explicit empty environ ignores the
        # self-test's COMPANION_KEYCHAIN=0, and checking availability reads no secret.
        backend = keyring.get_keyring()
        _require(ApiKeyStore(environ={}).available, f"no usable backend ({type(backend).__module__})")
        return type(backend).__module__

    def license_files() -> str:
        for path in (paths.LICENSE_PATH, paths.NOTICE_PATH):
            _require(path.is_file(), f"missing {path.name}")
        _require("CC BY-NC-SA" in paths.NOTICE_PATH.read_text(encoding="utf-8"), "NOTICE.md lacks the model license")
        return "LICENSE, NOTICE.md"

    def persona() -> str:
        from companion.core.persona import BuiltinPersonas

        default = BuiltinPersonas().default()
        _require(bool(default.system_prompt().strip()), "empty default prompt")
        return default.id

    return [
        _check("bundled resources", resources),
        _check("Live2D model", model),
        _check("renderer vendor files", vendor),
        _check("license files", license_files),
        _check("user data directory", data_dir),
        _check("Qt modules", imports(
            "PyQt6.QtCore", "PyQt6.QtWidgets", "PyQt6.QtWebEngineWidgets", "PyQt6.QtWebChannel",
        )),
        _check("text-to-speech package", imports("edge_tts")),
        _check("keyring package", imports("keyring")),
        # Linux CI runners have no secret service; a desktop session normally does.
        _check("keychain backend", keychain_backend, required=not platform.startswith("linux")),
        _check("default persona", persona),
    ]


def format_report(checks: Sequence[Check]) -> str:
    lines = []
    for check in checks:
        status = "PASS" if check.ok else ("FAIL" if check.required else "WARN")
        lines.append(f"{status}  {check.name}" + (f": {check.detail}" if check.detail else ""))
    failed = sum(1 for check in checks if check.required and not check.ok)
    lines.append(f"Self-test {'passed' if not failed else f'failed ({failed} required check(s))'}")
    return "\n".join(lines)


def passed(checks: Sequence[Check]) -> bool:
    return all(check.ok or not check.required for check in checks)


def run(request: SelfTestRequest, gui: Callable[[], list[Check]] | None = None) -> int:
    checks = static_checks()
    try:
        if gui is None:
            from companion.ui.self_test import gui_checks as gui
        checks += gui()
    except Exception as exc:  # Still write a report when the window cannot start at all.
        checks.append(Check("main window", False, f"{type(exc).__name__}: {exc}"))
    report = format_report(checks)
    # A windowed build on Windows has no stdout.
    if sys.stdout is not None:
        print(report, flush=True)
    if request.report_path is not None:
        request.report_path.write_text(report + "\n", encoding="utf-8")
    # Close the log file first so Windows can delete the throwaway directory.
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).is_relative_to(request.data_dir):
            root.removeHandler(handler)
            handler.close()
    shutil.rmtree(request.data_dir, ignore_errors=True)
    return 0 if passed(checks) else 1
