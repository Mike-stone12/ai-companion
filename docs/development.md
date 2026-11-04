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

### Memory benchmark

`evals/memory_benchmark/cases.jsonl` holds 93 user messages (80 Chinese, 13 English) with the facts a memory system should keep from each one: identity, preferences, plans, events, people around the user, chit-chat that must not be stored, the same fact paraphrased across turns (dedup), and later messages that contradict an earlier one (update). Where the extraction harness above scores store decisions, this benchmark scores the facts themselves and what the store ends up holding after multi-turn scenarios.

```bash
python -m evals.memory_benchmark.run_benchmark                    # gate + heuristic fallback, no API calls
python -m evals.memory_benchmark.run_benchmark --extractor llm    # gate + the real LLM extractor (sends requests)
python -m evals.memory_benchmark.run_benchmark --rescore evals/memory_benchmark/results/<file>.jsonl
```

The extractor runs on every message, including those the gate rejects, so a run scores the gate, the extractor alone, and the real pipeline together. Raw extractor output and a markdown report of each run are kept in `evals/memory_benchmark/results/`.

Baseline (2026-10-14/15; LLM rows use `deepseek-flash` with thinking off, median 1.1 s per call). Re-running the offline rows on 2026-11-04 gives identical numbers, so the gate has not changed since:

| Stage | Metric | Result |
| --- | --- | --- |
| Gate | Messages with a fact that reach the extractor | 33/74 (45 %) |
| Gate | Passed messages that actually hold a fact | 33/40 (82 %) |
| Gate | English messages with a fact that pass | 0/11 |
| Gate + LLM extractor (what the app stores) | Precision / recall of extracted facts | 34/34 (100 %) / 36/81 (44 %) |
| LLM extractor alone (gate ignored) | Precision / recall of extracted facts | 76/77 (99 %) / 81/81 (100 %), nothing on chit-chat |
| Gate + heuristic fallback | Precision / recall of extracted facts | 12/12 (100 %) / 12/81 (15 %) |
| Store, LLM extractor alone | Duplicate / stale entries after the paraphrase and conflict scenarios | 8/23 (35 %) / 5/23 (22 %) |

The gate is the main loss: it is keyword-based and Chinese-only, so it drops every English fact, events phrased without a trigger word (拿到 offer, 入职, 搬到), and plain facts such as 我今年24岁 or 我对花生过敏, while seven chit-chat messages pass and cost a request. The store rows feed `MemoryStore` directly, without the consolidation pipeline, so they measure what consolidation has to clean up.

### Human-likeness

`evals/humanlike/` checks whether the companion sounds like a person texting rather than an assistant, end to end. It plays the scripted chats in `scenarios.json` (a burst after a bad day, one-word answers, jealousy, remembering an exam, assistant chores, questions about her own life, 1:30 a.m., "are you an AI") through the real `CompanionWindow`, offscreen, one fresh process and data directory per scenario, with the scenario's wall clock. Then it reports rule-based metrics (assistant phrases, questions at the end of replies, markdown, repeated openers, message length and count) and an LLM judge's 1-10 scores for human, character, emotion, and context.

```bash
python -m evals.humanlike run --label master                       # needs PyQt6-WebEngine and an API key
python -m evals.humanlike run --label my-change --app-dir ../wt    # measure another checkout
python -m evals.humanlike compare evals/humanlike/results/<before>.json evals/humanlike/results/<after>.json
python -m evals.humanlike run --fake --no-judge                    # dry run against a local fake endpoint
```

`compare` asks the judge which run is more human for each scenario, twice with the order swapped, and counts wins. **A real run sends the scripted chats, and then the transcripts, to the configured endpoint.** `JUDGE_MODEL` selects the judge model; the default is the chat model. Run it before and after any change to prompts, pacing, or the persona, and put the comparison in the PR.

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
