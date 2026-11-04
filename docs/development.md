# Development

Conventions for contributors are in [CLAUDE.md](../CLAUDE.md). Architecture notes are in [architecture.md](architecture.md).

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover the core, adapters, and CLIs without a display or GUI dependencies; `companion/core` never imports PyQt or edge-tts. For every pull request, CI runs `ruff` on Ubuntu and `pytest` on Ubuntu, Windows, and macOS with Python 3.11 and only `requirements-dev.txt` installed. These checks do not launch or validate the GUI.

Run the repeatable offline evaluation of the extraction gate and lexical recall with:

```bash
python -m companion.core.memory.evaluation
```

The extraction harness uses labelled Chinese cases in `evals/extraction_cases.json` and can score injected extractors fully offline. Run `python -m companion.core.memory.extraction_eval` for usage without making requests. A maintainer can explicitly run `python -m companion.core.memory.extraction_eval --live` with a configured API key; **`--live` sends the case messages to the configured LLM endpoint**. It reports store-decision accuracy, false stores, missed stores, keyword hit rate (all expected substrings found per positive case), and per-case errors. Live runs reuse the existing extractor, including its heuristic fallback on request or parse failures.

## Packaging

Build on each target operating system from the repository root, using the app
environment with `requirements.txt` installed. Install PyInstaller separately;
it is not included in either requirements file:

```bash
pip install pyinstaller
pyinstaller ai-companion.spec
```

Output goes in `dist/`: `AI Companion.app` on macOS, and the `AI Companion/`
one-folder build on Windows and Linux. The bundle includes the renderer, Live2D
models, and vendor assets. Optional `vosk` is excluded, so wake-word detection
is unavailable in this build; push-to-talk remains supported.

Check a build (or a source checkout) without network access or touching your data:

```bash
"dist/AI Companion.app/Contents/MacOS/AI Companion" --self-test report.txt   # macOS
"dist/AI Companion/AI Companion" --self-test report.txt                      # Linux
python main.py --self-test                                                   # source
```

The self-test checks bundled resources, imports, and the keychain backend, then
opens the real window and waits for the Live2D model to render. It uses a
temporary data directory (deleted afterwards), never reads the keychain or calls
an API, prints a PASS/FAIL report (also written to the optional path), and exits
non-zero if a required check fails. A 120 s watchdog writes a failing report and ends
the process if the window part ever hangs.

The **Package** GitHub Actions workflow builds with `ai-companion.spec` on macOS,
Windows, and Linux for every pull request and push to `master`/`agent-dev`, runs
the self-test on each frozen build, and uploads `AI-Companion-macOS.zip`,
`AI-Companion-Windows.zip`, and `AI-Companion-Linux.tar.gz` as workflow artifacts
(kept 14 days). Builds are unsigned. Each build bundles the default whale-girl
character, which is licensed under CC BY-NC-SA 4.0: **the builds must not be used
commercially** (see [NOTICE.md](../NOTICE.md)). `LICENSE` and `NOTICE.md` are included
inside every bundle and at the top level of every archive.

User data still lives in the [platform data directory](architecture.md#data-flow-and-privacy) (or the
`COMPANION_DATA_DIR` override). `.env` is never bundled. To use it, place it next
to the executable: `dist/AI Companion/.env` on Windows/Linux, or
`dist/AI Companion.app/Contents/MacOS/.env` on macOS. The frozen path resolver
passes that exact file to `companion/env.py`; it does not search beside the outer
`.app` directory. The loader reads UTF-8 `KEY=value` lines, skips blank lines and
comments, strips surrounding quotes, and preserves existing environment values.
Alternatively, use the user data directory's `config.json` settings and the
environment; API keys come from the system keychain (Settings…), the environment, or `.env`, never `config.json`.
