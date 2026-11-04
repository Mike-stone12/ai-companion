# Build in the app environment: pip install pyinstaller
# Then run from the repository root: pyinstaller ai-companion.spec
# Output goes in dist/. Build separately on each target operating system.

import sys

# Destinations are relative to sys._MEIPASS, as used by companion/paths.py.
DATAS = [
    ("live2d_renderer.html", "."),
    # The bundled whale-girl model (CC BY-NC-SA 4.0) and Cubism Core require their
    # license and attribution notices to travel with the build.
    ("LICENSE", "."),
    ("NOTICE.md", "."),
    ("models", "models"),
    ("vendor", "vendor"),
]

# Include Qt modules used by the renderer and the opt-in microphone adapter.
HIDDENIMPORTS = [
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineCore",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebChannel",
    "PyQt6.QtMultimedia",
    "edge_tts",
]

EXCLUDES = [
    "vosk",
    "pytest",
    "ruff",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDENIMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AI Companion",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="AI Companion",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="AI Companion.app",
        info_plist={
            "NSMicrophoneUsageDescription": "AI Companion uses the microphone for push-to-talk and wake-word input.",
            "NSHighResolutionCapable": True,
            # Keep timers (renderer, proactive chat, the self-test) running when the window is
            # in the background; App Nap would otherwise throttle them.
            "NSAppSleepDisabled": True,
        },
    )
