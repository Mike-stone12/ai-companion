# CLAUDE.md

Guidance for Claude Code sessions working on this repository. The maintainer works from more
than one machine; follow the same conventions on each.

## Communication

- Reply to the maintainer in Chinese. Code, comments, commit messages, PR descriptions, and
  docs stay in English.

## Project at a glance

Desktop AI companion: a PyQt6 window hosting a Live2D avatar (Qt WebEngine page), streaming
LLM chat over any OpenAI-compatible API, sentence-by-sentence Edge TTS with lip sync, emotion
expressions, and persistent memory and chat history. Opt-in voice input adds a **Hold to talk**
button beside the chat input: press to capture, release to transcribe and send through the
normal chat path. Enable `VOICE_INPUT` and set a non-empty `TRANSCRIPTION_MODEL`; otherwise
no control or microphone is created and QtMultimedia is not imported at window startup.

Opt-in wake detection requires `WAKE_WORD=1`, non-empty `WAKE_WORD_PHRASES`, an unpacked
Vosk model directory in `WAKE_WORD_MODEL_DIR`, a separately installed `vosk` package, and
usable voice input (`VOICE_INPUT=1` plus `TRANSCRIPTION_MODEL`). A plain-text “Wake word on”
indicator shows when the microphone is listening. Detection captures roughly 5 seconds,
then uses normal transcription and chat submission. Listening pauses during capture and
replies; detections with typed input are ignored. Missing Vosk or a model load failure logs
a warning and disables wake detection for the session.

```
main.py                    entry point (self-test flag, logging, legacy data migration, Qt bootstrap)
companion/self_test.py     offline --self-test checks (GUI half in companion/ui/self_test.py)
ai-companion.spec          PyInstaller build: macOS .app, Windows/Linux one-folder
companion/paths.py         resource resolution inside a frozen bundle or source checkout; user data paths
companion/core/            pure Python, never imports Qt: config, api_key (keychain first,
                           then .env/environment; keyring imported lazily), text, llm (client, SSE),
                           chat (emotion tags, history, conversation summary),
                           memory (store, gate, extractor, recall, consolidation),
                           model profiles, window state (settings file, placement rules),
                           persona.py (Persona data, PersonaProvider presets, PersonaStore;
                           default "childhood friend"; renders the system prompt)
                           voice_input.py (push-to-talk capture model, WAV encoder),
                           voice_input_controller.py (session controller),
                           wake_word.py (pure-Python wake-word matcher),
                           wake_word_controller.py (listening session controller),
                           llm/transcription.py (transcription client)
companion/core/proactive/  events, policy, triggers (including active-app trigger active_app.py),
                           composer (app-note framing; replies stay in the persona's voice and
                           address the user), engine tick; opt-in via PROACTIVE_CHAT
companion/core/tools/      function-calling tools, opt-in via CHAT_TOOLS
companion/adapters/        Edge TTS (tts_edge.py), foreground-app adapter (active_app.py),
                           Qt microphone capture (microphone.py), lazy Vosk recognizer (wake_word_vosk.py)
companion/app/             workers.py (chat, transcription, TTS, memory, summary),
                           wake_word_worker.py (local wake recognition), logging_setup.py
companion/memory_cli.py    memory inspection and editing (dry run unless --write)
companion/settings_cli.py  non-secret settings inspection and editing
companion/ui/              main window, chat panel, QWebChannel bridge to the renderer
                           settings_dialog.py, memory_dialog.py, persona_dialog.py
live2d_renderer.html       avatar renderer (PixiJS + pixi-live2d-display, lip sync, queue)
models/                    Live2D models; companion.json holds window size, motion roles,
                           and the emotion -> expression map
evals/                     offline memory evaluation cases
tests/                     pytest suite for companion/core and adapters (no Qt needed)
```

User data (memory, chat history, logs, `reminders.json` when `CHAT_TOOLS` is enabled,
and `config.json` with the window placement) lives in the
platform user data directory, e.g. `~/Library/Application Support/AICompanion/` on macOS, not in
the repo.

## Setup and commands

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # then add an API key; never commit .env
.venv/bin/ruff check .
.venv/bin/pytest
.venv/bin/python main.py
```

Packaging: in the app environment, run `pip install pyinstaller`, then
`pyinstaller ai-companion.spec` from the repository root on each target OS.
PyInstaller is installed separately; it is not in the requirements files.
`python main.py --self-test [REPORT]` (or the frozen executable with the same flag) is an
offline smoke test: resources, imports, keychain backend, then the real window until the
Live2D model renders; temporary data dir, no keychain reads, no network. The `Package`
workflow builds all three OSes, runs it on each frozen build, and uploads the archives.

CI runs ruff and pytest on Ubuntu, Windows, and macOS with only `requirements-dev.txt`
installed, so anything imported by the tests must not need PyQt or edge-tts. Keep Qt out of
`companion/core`.

## Workflow

- The roadmap and task list live in the maintainer's private notes repository
  (`ai-companion-notes`, file `优化计划.md`, usually symlinked into this folder and gitignored).
  Before starting a task, pull it and check the task is not claimed by the other machine;
  claim it there, and mark it done with the PR number afterwards.
- One change per branch and PR. Branch from the latest `master` with a prefix: `feat/`, `fix/`,
  `perf/`, `refactor/`, `chore/`, `ci/`, `docs/`, `test/`, `eval/`, `build/`.
- PRs always target `master`. If work depends on an unmerged PR, branch from that PR's branch
  but still target `master` (merging in either order then works). Do not stack PRs on feature
  branches; that has merged changes into the wrong branch before.
- Conventional Commits (`feat: ...`, `fix: ...`) with a body explaining why.
- Write the failing test first for logic in `companion/core` and adapters.
- UI, audio, and renderer changes must be verified in the real window, not only by tests:
  scripted probes against `CompanionWindow`, the WebEngine debug port
  (`QTWEBENGINE_REMOTE_DEBUGGING`) for renderer state and screenshots, and real API calls
  where behaviour depends on the model. Use a temporary `COMPANION_DATA_DIR` so the
  maintainer's real memory and history are not touched.
- Report measured numbers in PR descriptions (latency, compliance rates, before/after).

## Things to keep in mind

- Never commit `.env`, user data, or the private plan. Check staged diffs for keys.
- The API key lives in the OS keychain or `.env`, never in `config.json`, logs, or the UI.
  Tests run with `COMPANION_KEYCHAIN=0` (tests/conftest.py) and inject fake keyring backends.
- `models/whale-girl/` is CC BY-NC-SA 4.0 artwork redistributed unmodified; register extra
  model data at runtime (as the renderer does for expressions) instead of editing those files.
  See NOTICE.md.
- Model output is untrusted text: chat bubbles use `Qt.TextFormat.PlainText`.
- Network calls must have bounded waits: chat streams use first-content and idle deadlines
  (providers can hold a stream open with keep-alives), and TTS has per-sentence timeouts.
