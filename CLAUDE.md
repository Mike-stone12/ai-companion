# CLAUDE.md

Guidance for Claude Code sessions working on this repository. The maintainer works from more
than one machine; follow the same conventions on each.

## Communication

- Reply to the maintainer in Chinese. Code, comments, commit messages, PR descriptions, and
  docs stay in English.

## Project at a glance

Desktop AI companion: a PyQt6 window hosting a Live2D avatar (Qt WebEngine page), streaming
LLM chat over any OpenAI-compatible API, sentence-by-sentence Edge TTS with lip sync, emotion
expressions, and persistent memory and chat history.

```
main.py                    entry point (logging, legacy data migration, Qt bootstrap)
companion/core/            pure Python, never imports Qt: config, text, llm (client, SSE),
                           chat (emotion tags, history, conversation summary),
                           memory (store, gate, extractor, recall, consolidation),
                           model profiles, window state (settings file, placement rules)
companion/core/tools/      function-calling tools, opt-in via CHAT_TOOLS
companion/adapters/        Edge TTS
companion/app/             QThread workers, logging setup
companion/memory_cli.py    read-only memory inspector
companion/ui/              main window, chat panel, QWebChannel bridge to the renderer
live2d_renderer.html       avatar renderer (PixiJS + pixi-live2d-display, lip sync, queue)
models/                   Live2D models; companion.json holds window size, motion roles,
                           and the emotion -> expression map
evals/                    offline memory evaluation cases
tests/                     pytest suite for companion/core and adapters (no Qt needed)
```

User data (memory, chat history, logs, and `config.json` with the window placement) lives in the
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
- `models/whale-girl/` is CC BY-NC-SA 4.0 artwork redistributed unmodified; register extra
  model data at runtime (as the renderer does for expressions) instead of editing those files.
  See NOTICE.md.
- Model output is untrusted text: chat bubbles use `Qt.TextFormat.PlainText`.
- Network calls must have bounded waits: chat streams use first-content and idle deadlines
  (providers can hold a stream open with keep-alives), and TTS has per-sentence timeouts.
