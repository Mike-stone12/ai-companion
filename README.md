# AI Companion

[![CI](https://github.com/Mike-stone12/ai-companion/actions/workflows/ci.yml/badge.svg)](https://github.com/Mike-stone12/ai-companion/actions/workflows/ci.yml)

**A desktop companion that remembers the conversation.**

A Windows application combining an animated Live2D character, LLM chat, bilingual voice replies, and persistent memory. The project explores how a conversational interface can retain useful facts across sessions while keeping its context compact.

**Stack:** Python · PyQt6 / Qt WebEngine · OpenAI-compatible APIs · Edge-TTS · PixiJS · Live2D

[Quick start](#quick-start) · [Memory design](#memory-design) · [Architecture](#architecture) · [Configuration](#configuration)

## What it does

- **Desktop character:** a transparent, frameless, draggable window with a Live2D avatar. Ships with two models, a whale-girl maid (default) and Hiyori, which can be swapped with one setting.
- **Window controls:** right-click the character or the drag bar for a menu with size presets (70–150 %), opacity presets (55–100 %), reset position, and quit. Position, size, and opacity are saved to `config.json` in the user data directory and restored on the next start; a saved position that is no longer on any screen (an unplugged monitor, for example) falls back to the default spot above the taskbar.
- **Chat history:** a scrollable bubble panel shows the conversation (user right, companion left, notices centered) and the current reply fills in as it streams. The conversation is saved to `history.json` in the user data directory and restored on the next start, both on screen and as context for the model.
- **Emotional expressions:** the model opens each reply with an emotion tag (`[happy]`, `[sad]`, `[angry]`, `[surprised]`, `[shy]`, `[confused]`, `[awkward]`, `[neutral]`). The tag is stripped from the stream before display and speech, and the avatar switches to the matching expression for the reply, returning to default a few seconds after it stops speaking.
- **Streaming chat:** connects to any OpenAI-compatible endpoint (Moonshot/Kimi by default, DeepSeek supported) and streams the reply, so text appears as it is generated and speech starts after the first clause instead of the whole reply. Median time from sending a message to the first spoken word dropped from 2.97 s to 1.70 s (DeepSeek `deepseek-flash`, three prompts) and no longer grows with reply length.
- **Voice replies with lip sync:** synthesizes replies with Edge-TTS, selects a Chinese or English voice based on the response, and moves the avatar's mouth with the speech volume (Web Audio analyser driving `ParamMouthOpenY`, or the model's LipSync parameter).
- **Persistent memory:** extracts short facts, saves them locally, and includes recent memories in later conversations.
- **Background processing:** separate Qt workers handle chat requests, memory extraction, and speech synthesis.

## Memory design

The memory pipeline uses a lightweight extraction gate, structured LLM extraction, and a heuristic fallback:

1. **Detect useful input.** Chinese-language patterns identify personal facts, preferences, plans, and upcoming events. Common chit-chat openers are deliberately not triggers, because every extraction costs an API request.
2. **Extract candidates.** Messages that pass the gate are sent to an LLM in JSON mode. Where the provider supports it (Moonshot, DeepSeek), reasoning is turned off for this call, which makes extraction several times faster. If the LLM finds nothing worth remembering, nothing is stored. High-precision heuristics (name, identity, likes, location) are used only when the request itself fails.
3. **Queue in the background.** Extraction runs off the UI thread. Jobs queue (up to five) instead of being dropped while one is running, and rate-limited requests are retried after 10 s and 25 s.
4. **Normalize and store.** Summaries are shortened, deduplicated by exact summary text, timestamped, and stored in `memory.json` in the user data directory (see [Data flow](#data-flow)).
5. **Recall into context.** Up to eight recent memories are added to the next chat request alongside a bounded conversation history.

The store retains 24 entries by default, configurable through `MEMORY_LIMIT`. This implementation uses external, text-based memory; it does not update model weights.

### Current tradeoffs

- Extraction rules and gating are primarily designed for Chinese input.
- Recall uses recency, so an older relevant fact can be missed.
- Exact-text deduplication does not resolve paraphrases or conflicting facts.
- Memory is added asynchronously and may become available on a later turn.

### Memory benchmark

`eval/memory/cases.jsonl` holds 93 user messages (80 Chinese, 13 English) with the facts a memory system should keep from each one: identity, preferences, plans, events, people around the user, chit-chat that must not be stored, the same fact paraphrased across turns (dedup), and later messages that contradict an earlier one (update). `python -m eval.memory.run_benchmark` scores the rule-based gate without any API call, runs an extractor on every message (the heuristic fallback by default, the real LLM extractor with `--extractor llm`), and feeds each multi-turn scenario through a `MemoryStore` to count duplicate and stale entries. Raw extractor output and the markdown report of each run are kept in `eval/memory/results/`; `--rescore <file>` re-scores a saved run without new requests.

Baseline measured on 2026-10-14, before any change to the gate or extractor:

| Stage | Metric | Result |
| --- | --- | --- |
| Gate | Messages with a fact that reach the extractor | 33/74 (45 %) |
| Gate | Passed messages that actually hold a fact | 33/40 (82 %) |
| Gate | English messages with a fact that pass | 0/11 |
| Gate + heuristic fallback | Precision / recall of extracted facts | 12/12 (100 %) / 12/81 (15 %) |
| Gate + LLM extractor | Precision / recall of extracted facts | not yet measured (needs an API key; see `eval/memory/results/`) |
| Store (heuristic run) | Duplicate / stale entries | 0 / 2 of 4 stored; only 2 of 10 scenarios stored anything |

The gate is the main loss. It is keyword-based and Chinese-only, so it drops 41 of the 74 fact-bearing messages: every English one, every event phrased without a trigger word (拿到 offer, 录取, 入职, 升职, 领证, 搬到, 手术), and plain facts such as 我今年24岁, 我对花生过敏, 我不吃辣, 我养了一只猫. Seven of the 19 chit-chat messages pass the gate and cost a request (明天再说吧, 我是说真的啦, 周末快乐呀, ...). The store keeps whatever the extractor hands it with exact-text dedup only, so a fact the user later corrects stays next to the new one.

## Architecture

```mermaid
flowchart LR
    UI["PyQt desktop window"] --> View["Qt WebEngine / Live2D"]
    UI --> Chat["ChatStreamWorker (SSE)"]
    Chat --> API["Configured LLM endpoint"]
    Chat --> Split["SentenceSplitter"]
    Split --> TTS["TTSWorker / Edge-TTS (one sentence at a time)"]
    TTS --> Bridge["AvatarBridge / QWebChannel"]
    Bridge --> Audio["Renderer audio + talk motion"]
    Audio -- "started / finished" --> Bridge
    Chat --> Memory["MemoryWorker"]
    Memory --> Store["MemoryStore / local JSON"]
    Store --> Context["Recent memory context"]
    Context --> Chat
```

Replies are streamed: `ChatStreamWorker` reads the SSE stream, shows the text as it arrives, and hands each complete sentence to `SentenceSplitter`-driven TTS. Sentences are synthesized strictly in order and queued in the renderer, which plays them back to back with a single talk gesture; the first clause is cut at a comma after a few words so speech starts early. If the stream breaks, the text received so far is kept and marked as interrupted.

Emotion tags are parsed off the start of the stream (`companion/core/chat/emotion.py`); only the leading tag is held back, so untagged replies are not delayed. The tag is kept in the conversation history sent back to the model, because without it the model imitates its own untagged replies and stops tagging after a turn or two (2/8 tagged replies vs 8/8 in an eight-turn test).

The Python application owns conversation state and worker lifecycles. Everything that does not need Qt (configuration, the LLM client, memory, model profiles) lives in `companion/core` and is tested without a GUI. The embedded HTML renderer handles the avatar and plays the synthesized speech. Python and the renderer talk over a QWebChannel object (`companion/ui/avatar_bridge.py`): Python sends play / stop / talking / motion commands, and the renderer reports when it is ready and when audio starts, finishes, or fails. The talk gesture therefore starts with the audio rather than when the request is sent, and the mouth follows the speech volume frame by frame (applied after motions and physics, right before rendering), and a two-minute watchdog resets the window if the renderer never reports back. Qt signals return worker results to the interface.

## Quick start

**Requirements:** Windows, Python 3.11+, and an API key for a compatible LLM provider. Chat and voice synthesis require network access.

Run these commands in **PowerShell**:

```powershell
git clone https://github.com/Mike-stone12/ai-companion.git
cd ai-companion
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with your provider's API key, endpoint, and model, then start the application:

```powershell
.\venv\Scripts\python.exe main.py
```

Using the environment's Python executable directly avoids requiring shell activation.

### Try the memory flow

1. Send a short fact such as `我喜欢咖啡`.
2. Wait for the reply and background memory extraction to finish.
3. Close and restart the application.
4. Ask `我喜欢什么饮料？` to try recall from the saved context.

Recall depends on extraction and the configured model; this is a manual walkthrough, not a benchmark result.

## Configuration

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Provider API key | Required for chat |
| `OPENAI_BASE_URL` | Chat API base URL | `https://api.moonshot.ai/v1` |
| `OPENAI_MODEL` | Model identifier | `kimi-k2.6` |
| `OPENAI_TIMEOUT` | Request timeout in seconds | `60` |
| `OPENAI_RETRIES` | Request retry setting | `2` |
| `CHAT_THINKING` | Let the model reason before chat replies (Moonshot and DeepSeek only). Off is faster and keeps replies short enough to speak. | `0` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Logs go to the terminal and `logs/companion.log` in the user data directory (rotated at 1 MB, 3 backups). | `INFO` |
| `EDGE_TTS_VOICE_ZH` | Chinese voice | `zh-CN-XiaoxiaoNeural` |
| `EDGE_TTS_VOICE_EN` | English voice | `en-US-AriaNeural` |
| `MEMORY_ENABLED` | Enable new memory extraction | `1` |
| `MEMORY_LIMIT` | Maximum retained memory entries | `24` |
| `COMPANION_DATA_DIR` | Where memory and logs are stored | Platform user data directory |
| `COMPANION_SYSTEM_PROMPT` | Companion's system instruction | Built-in companion prompt |
| `LIVE2D_MODEL` | Model folder under `models/` (`whale-girl`, `hiyori`) or a path to a `.model3.json` | `whale-girl` |
| `LIVE2D_VENDOR_DIR` | Optional renderer dependency directory | `vendor/` |

Variables already set in the shell take precedence over values in `.env`.

`MEMORY_ENABLED=0` stops new extraction. Existing memories are still loaded into chat context by the current implementation.

## Project layout

```text
main.py                 Entry point
companion/
  core/                 Pure Python, no Qt: config, text cleanup, LLM client,
                        memory (store, gate, extractor), model profiles,
                        window state (settings file, placement rules)
  adapters/tts_edge.py  Edge TTS synthesis and voice selection
  app/workers.py        QThread workers for chat, TTS, and memory extraction
  ui/main_window.py     The desktop window
  qt_bootstrap.py       Windows Qt DLL setup and import diagnostics
tests/                  pytest suite for companion/core (runs without Qt)
eval/memory/            memory benchmark: cases.jsonl, scoring, runner, saved results
live2d_renderer.html     Embedded avatar renderer
.env.example            Example provider and voice settings
requirements.txt        Pinned Python dependencies
models/whale-girl/      Default model (CC BY-NC-SA 4.0, see NOTICE.md)
models/hiyori/          Alternative model (Live2D Free Material License)
vendor/                 Renderer dependencies (PixiJS 6, Cubism Core, pixi-live2d-display 0.4.0)
```

### Adding a model

Put a Cubism 4 model in its own folder under `models/` and, optionally, add a `companion.json`:

```json
{
  "model": "c_0120.model3.json",
  "window": { "width": 430, "height": 580 },
  "motions": { "talk": ["selfie"], "ambient": ["bubble", "splash"] },
  "expressions": { "happy": "expressions/开心兴奋.exp3.json", "angry": "expressions/生气.exp3.json" }
}
```

`motions.talk` lists the motion groups played when the companion starts replying, and `motions.ambient` lists the groups played occasionally while idle. The model's idle group loops automatically. `expressions` maps emotion tags to `.exp3.json` files; they are registered on the model settings in memory when the model loads, so the model files themselves stay unmodified. Emotions without a mapping (or models without `expressions`) keep the default face. Without `companion.json`, the renderer uses the first `*.model3.json` in the folder and guesses roles from group names (`Talk`/`Tap`, `Flick`). Select the model with `LIVE2D_MODEL=<folder>`.

### Data flow

User data lives outside the project, so a packaged read-only app can still write it:

| Platform | Location |
| --- | --- |
| macOS | `~/Library/Application Support/AICompanion/` |
| Windows | `%APPDATA%\AICompanion\` |
| Linux | `$XDG_DATA_HOME/ai-companion/` (default `~/.local/share/ai-companion/`) |

It holds `memory.json`, `history.json` (the last 200 turns), `config.json` (window position, size, and opacity under a `window` key), and `logs/`. On first start, a `memory.json` left in the project root by older versions is moved there; if one already exists in the data directory, neither file is touched. `.env` (secrets, ignored by Git) and the models stay in the project.

At the default `INFO` level the log records requests, memory counts, and errors but no conversation text; reply and TTS text appear only at `DEBUG`. Memories and conversation history are stored locally as plain JSON, and recalled memory text is sent to the configured LLM endpoint with chat requests. Replies are sent to Edge-TTS for speech synthesis. The renderer loads all dependencies from `vendor/` and only falls back to a version-pinned CDN copy if a local file is missing.

### Troubleshooting

- **Qt import or DLL errors:** use a fresh virtual environment and `pip install -r requirements.txt`. On Windows the startup log prints the DLL directories it added and, for Anaconda installs, whether the ICU runtime conflicts with PyQt6.
- **No character appears:** check the resource paths logged at startup (`logs/companion.log` in the data directory), or set `LIVE2D_MODEL` and `LIVE2D_VENDOR_DIR` explicitly. `LOG_LEVEL=DEBUG` also lists every renderer file it looked for.
- **Chat fails:** verify the API key, model identifier, endpoint, and network connectivity. If no reply text arrives within 30 s (an overloaded DeepSeek keeps the stream open with keep-alive comments and no content), the window gives up with "模型服务繁忙" instead of waiting; a stall of 30 s between pieces of a reply also ends it.
- **No voice on a slow network:** each sentence's speech synthesis is capped at 20 s (5 s to connect, 15 s per read). After the first failure the rest of that reply is shown as text only, so a bad connection does not stack one timeout per sentence.
- **Window in the wrong place or size:** right-click it and choose **Reset position** or a size preset. A saved position that is off every screen is ignored at startup; to discard the rest, delete the `window` section from `config.json` in the data directory.
- **Memory is not recalled:** check that extraction completed, that `memory.json` in the data directory contains the fact, and that it remains among the recent entries.

## Development

```bash
pip install -r requirements-dev.txt
ruff check .
pytest
```

The tests cover `companion/core`, which never imports PyQt or edge-tts, so they run without a display or the GUI dependencies. CI runs `ruff` and `pytest` on Ubuntu, Windows, and macOS for every pull request, with only `requirements-dev.txt` installed; a Qt import added to `companion/core` fails there.

The memory benchmark (see [Memory benchmark](#memory-benchmark)) runs from the repository root:

```bash
python -m eval.memory.run_benchmark                   # gate + heuristic fallback, no API calls
python -m eval.memory.run_benchmark --extractor llm   # the real extractor, key from .env; --rpm 3 on Moonshot's free tier
```

Each run writes its raw output to `eval/memory/results/<date>-<extractor>.jsonl` and prints a markdown report (`--report <file>` saves it). Re-run it after any change to `companion/core/memory` and update the table above.

## Next steps

- Consolidate memories (ADD / UPDATE / DELETE / NOOP against the stored entries) so paraphrases stop piling up and corrected facts replace the old ones, and widen the extraction gate, which the benchmark shows drops every English message and most life events. Re-run `eval/memory/run_benchmark.py` after each change and update the baseline table.
- Add semantic retrieval and conflict-aware memory updates.
- Add an interface for inspecting, editing, and removing stored memories.
- Validate platforms beyond Windows.

## License and credits

The source code is released under the [MIT License](LICENSE).

Model and runtime assets are not covered by the MIT License. Full terms are in [NOTICE.md](NOTICE.md).

- **Whale girl** (default), [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), **non-commercial**. Character design by 上善无形, DeepSeek-themed maid redesign by ZipZipPipe, Live2D model by 氵六青, via [Andersen216/dsh-whale-girl-live2d](https://github.com/Andersen216/dsh-whale-girl-live2d). This is fan art; the project is not affiliated with DeepSeek.
- **Hiyori** (© Live2D Inc.), used under the Live2D Free Material License; see [`models/hiyori/LIVE2D_README.txt`](models/hiyori/LIVE2D_README.txt).

Rendering uses [PixiJS](https://github.com/pixijs/pixijs), [pixi-live2d-display](https://github.com/guansss/pixi-live2d-display), and Live2D Cubism Core.
