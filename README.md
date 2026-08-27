# AI Companion

A desktop AI companion for Windows with an animated Live2D character, voice output, and persistent long-term memory. The companion sits on your desktop, chats with you through an LLM, speaks its replies aloud, and remembers facts about you across sessions.

## Features

- **Live2D character** — an animated avatar rendered in an embedded web view (PixiJS + `pixi-live2d-display` + Cubism core), displayed in a frameless, draggable desktop window
- **LLM chat** — works with any OpenAI-compatible API (defaults to Moonshot/Kimi); model, base URL, and key are configured via `.env`
- **Voice replies** — text-to-speech via Edge-TTS, with automatic voice switching between Chinese and English based on the reply's language
- **Persistent long-term memory** — the companion extracts durable facts from conversations (your name, preferences, upcoming events) and recalls them in future sessions
- **Non-blocking UI** — chat, TTS, and memory extraction each run on background worker threads, so the interface stays responsive

## How the memory system works

Memory is the core of this project. It runs as a two-path extraction pipeline:

1. **Heuristic path** — lightweight regex patterns match common self-disclosure phrasings (e.g. "My name is…", "I like…", "I live in…") and turn them into categorized memory candidates (`identity`, `preference`, `status`, `profile`, `event`) with zero API cost.
2. **LLM path** — messages that pass a trigger gate (`should_extract_memory`) are additionally sent to the LLM, which returns structured JSON memories for facts the regexes can't capture.

Extracted memories are deduplicated and upserted into a JSON-backed `MemoryStore` (capped at a configurable limit, recency-sorted). On each turn, the most recent entries are rendered into a compact "long-term memory" block and injected into the system context, so the companion stays consistent without unbounded context growth.

## Setup

Requirements: Windows, Python 3.11+.

```bash
git clone https://github.com/Mike-stone12/ai-companion.git
cd ai-companion
python -m venv venv && venv\Scripts\activate
pip install PyQt6 PyQt6-WebEngine edge-tts requests
copy .env.example .env   # then fill in your API key
python main.py
```

### Configuration (`.env`)

| Variable | Purpose |
| --- | --- |
| `OPENAI_API_KEY` | API key for any OpenAI-compatible provider |
| `OPENAI_BASE_URL` | Provider endpoint (default: Moonshot) |
| `OPENAI_MODEL` | Chat model name |
| `EDGE_TTS_VOICE_ZH` / `EDGE_TTS_VOICE_EN` | TTS voices for Chinese / English replies |
| `MEMORY_ENABLED` | Toggle the memory pipeline |
| `MEMORY_LIMIT` | Max number of stored memories |

Your API key and the local memory file (`memory.json`) are git-ignored and never leave your machine except through your configured LLM provider.

## Architecture

```
CompanionWindow (PyQt6, frameless)
 ├── Live2D view  ── live2d_renderer.html (PixiJS + Cubism)
 ├── ChatWorker   ── OpenAI-compatible client → reply
 ├── TTSWorker    ── Edge-TTS → audio playback
 └── MemoryWorker ── heuristic + LLM extraction → MemoryStore (JSON)
```

## Roadmap

- Semantic retrieval over memories (embedding-based) instead of recency-only injection
- Memory editing UI (view / delete stored facts)
- Cross-platform support (macOS / Linux)

## Credits

- Character model: Live2D sample model "Hiyori" (© Live2D Inc., used under the Live2D Free Material License)
- Rendering: [pixi-live2d-display](https://github.com/guansss/pixi-live2d-display), PixiJS, Live2D Cubism Core
