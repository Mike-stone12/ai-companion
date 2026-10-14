from __future__ import annotations

import os
import site
import sys
from pathlib import Path


def bootstrap_windows_qt_dlls() -> list[Path]:
    if os.name != "nt":
        return []

    raw_candidates: list[Path] = [
        Path(sys.prefix),
        Path(sys.prefix) / "DLLs",
        Path(sys.prefix) / "Library" / "bin",
        Path(sys.prefix) / "Library" / "usr" / "bin",
        Path(sys.prefix) / "Scripts",
    ]

    try:
        raw_candidates.extend(Path(path) for path in site.getsitepackages())
    except Exception:
        pass

    try:
        raw_candidates.append(Path(site.getusersitepackages()))
    except Exception:
        pass

    raw_candidates.extend(Path(path) for path in sys.path if path)

    candidate_dirs: list[Path] = []
    seen: set[str] = set()
    for root in raw_candidates:
        for candidate in (
            root,
            root / "PyQt6" / "Qt6" / "bin",
            root / "PyQt6" / "Qt" / "bin",
            root / "PyQt6",
            root / "PyQt5" / "Qt5" / "bin",
            root / "PyQt5" / "Qt" / "bin",
            root / "PyQt5",
        ):
            key = str(candidate).lower()
            if key in seen:
                continue
            seen.add(key)
            if candidate.exists():
                candidate_dirs.append(candidate)

    active_dirs: list[Path] = []
    for dll_dir in candidate_dirs:
        os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(dll_dir))
            except OSError:
                continue
        active_dirs.append(dll_dir)

    return active_dirs


def diagnose_pyqt6_icu_mismatch() -> str | None:
    try:
        import lief
    except Exception:
        return None

    qt6_core = Path(sys.prefix) / "Lib" / "site-packages" / "PyQt6" / "Qt6" / "bin" / "Qt6Core.dll"
    icu_uc = Path(sys.prefix) / "Library" / "bin" / "icuuc.dll"
    if not qt6_core.exists() or not icu_uc.exists():
        return None

    try:
        qt_binary = lief.parse(str(qt6_core))
        icu_binary = lief.parse(str(icu_uc))
    except Exception:
        return None

    required_symbols: list[str] = []
    for imported in qt_binary.imports:
        if imported.name.lower() == "icuuc.dll":
            for entry in imported.entries:
                if entry.name:
                    required_symbols.append(entry.name)
            break

    if not required_symbols:
        return None

    exported_symbols = {entry.name for entry in icu_binary.exported_functions if entry.name}
    missing = [name for name in required_symbols if name not in exported_symbols]
    if not missing:
        return None

    preview = ", ".join(missing[:5])
    return (
        "[PyQt6 bootstrap] 检测到 ICU 运行时不兼容。\n"
        f"[PyQt6 bootstrap] Qt6Core.dll 需要这些未版本化符号: {preview}\n"
        f"[PyQt6 bootstrap] 但当前加载到的 ICU 是: {icu_uc}\n"
        "[PyQt6 bootstrap] 这是 pip 安装的 PyQt6-Qt6 与 Anaconda base 环境 ICU 冲突的典型现象。"
    )


def report_qt_import_failure(exc: ImportError, active_dll_dirs: list[Path]) -> None:
    print("[PyQt6 bootstrap] Failed to import PyQt6 modules.")
    print(f"[PyQt6 bootstrap] ImportError: {exc}")
    if active_dll_dirs:
        print("[PyQt6 bootstrap] DLL directories added:")
        for dll_dir in active_dll_dirs:
            print(f"  - {dll_dir}")
    diagnosis = diagnose_pyqt6_icu_mismatch()
    if diagnosis:
        print(diagnosis)
    print("[PyQt6 bootstrap] Install the pinned dependencies in a fresh virtual environment: pip install -r requirements.txt")
