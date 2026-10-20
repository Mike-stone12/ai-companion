# Configuration

Everything the app can be told, and where it keeps its data. Most people only need the [Quick start](../README.md#quick-start) in the README.

## Settings

Settings come from three places, highest precedence first: environment variables (including a
`.env` file), the `settings` section of `config.json` in the user data directory, and built-in
defaults. **Settings…** in the right-click menu edits the most common of these in `config.json` and stores
the API key in the system keychain; changes apply on the next start (a new API key applies at once). **Persona…** edits the companion's
character, and **Memories…** views, searches, and edits stored memory summaries.

| Variable | Purpose | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | Provider API key; used only when the system keychain holds none (see below) | Required for chat |
| `OPENAI_BASE_URL` | Chat API base URL (any OpenAI-compatible endpoint, e.g. `https://api.deepseek.com/v1`); must use https unless the host is loopback (local model servers) | `https://api.moonshot.ai/v1` |
| `OPENAI_MODEL` | Model identifier | `kimi-k2.6` |
| `OPENAI_TIMEOUT` | Request timeout in seconds | `60` |
| `OPENAI_RETRIES` | Request retry setting | `2` |
| `CHAT_THINKING` | Let the model reason before chat replies (Moonshot and DeepSeek only). Off is faster and keeps replies short enough to speak. | `0` |
| `CHAT_TOOLS` | Enable time and reminder tools (up to 3 model requests per turn). Reminders persist across restarts in `reminders.json` in the user data directory. When off, this file is not read or written. | `0` |
| `VOICE_INPUT` | Show the opt-in **Hold to talk** button beside chat input; release to transcribe and send. Requires a non-empty `TRANSCRIPTION_MODEL`. Off creates no button or microphone. | `0` |
| `TRANSCRIPTION_MODEL` | Transcription model identifier; uses the chat base URL and API key. Empty or whitespace-only disables voice input even when its flag is on. | Empty |
| `WAKE_WORD` | Enable offline wake detection; requires `WAKE_WORD_PHRASES`, `WAKE_WORD_MODEL_DIR`, `VOICE_INPUT=1`, a non-empty `TRANSCRIPTION_MODEL`, and the separately installed `vosk` package. “Wake word on” indicates microphone listening. Detection captures roughly 5 seconds, then transcribes and sends through normal chat. Listening pauses during capture and replies. | `0` |
| `WAKE_WORD_PHRASES` | Comma-separated wake phrases, e.g. `小鲸,hey whale`; full-width commas are also accepted. Empty disables the wake word. | Empty |
| `WAKE_WORD_MODEL_DIR` | Path to an unpacked Vosk model directory for offline recognition. Empty or whitespace-only disables the wake word. Missing Vosk or an invalid model disables only wake detection for the session and logs a warning. | Empty |
| `PROACTIVE_CHAT` | Opt in to idle chat, time-of-day greetings, and spoken due reminders, checked every 30 seconds. Enable `CHAT_TOOLS` to set persistent reminders. With `COMPANION_STATE` on, feelings steer it: missing the user (or a great mood) starts one short message after ten quiet minutes (at most every two hours, and never another until the user has replied), and while clearly annoyed or jealous it starts nothing but reminders. Off creates no proactive timer or requests. | `0` |
| `ACTIVE_APP_MONITOR` | Opt in to comments after a long foreground-app streak; requires `PROACTIVE_CHAT=1`. Uses only the foreground app name locally to track duration, then sends a short app-name/duration summary to the LLM. | `0` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Logs go to the terminal and `logs/companion.log` in the user data directory (rotated at 1 MB, 3 backups). | `INFO` |
| `EDGE_TTS_VOICE_ZH` | Chinese voice | `zh-CN-XiaoyiNeural` |
| `TTS_PITCH` | Pitch offset for the Chinese voice, e.g. `+10Hz` (±100 Hz); English is unchanged | `+10Hz` |
| `TTS_RATE` | Speed offset for the Chinese voice, e.g. `+6%` (±99 %) | `+6%` |
| `COMPANION_STATE` | The companion's mood carries over between replies, fades toward calm, turns into missing you after a day without a message, and sets the idle face. Stored in `state.json`. | `1` |
| `EMOTION_APPRAISAL` | Judge emotional turns (praise, another person, apology, criticism, care, the user's own news, brushing it off) with one extra JSON request in the background; a keyword gate skips small talk, so ordinary turns cost nothing extra. `0` leaves feelings to the reply tags only. | `1` |
| `MOOD_HALF_LIFE_MINUTES` | How fast the mood fades (minimum 5) | `120` |
| `COMPANION_DIARY` | For each day with conversation, once it is over (checked at start and every 10 minutes, at most 3 days back), one request writes a short diary entry in the persona's voice (`diary.json`, 60 entries). Replies with a first-person preference, backstory, or promise are mined for the companion's own memories (`self_memory.json`, separate from the user's `memory.json`). Recent diary entries and relevant self memories go into one bounded system message. | `1` |
| `REPLY_PACING` | Reply in one to four short messages, one per line from the model, each after a "typing…" pause based on its length (0.6–4 s, slower when annoyed or hurt); a busy or sleeping companion picks up 4–15 s or 3–8 s later (never over 30 s). Speech follows the messages. `0` restores one streaming bubble. | `1` |
| `DAILY_SCHEDULE` | Follow the persona's daily routine: what it is doing goes into the prompt and the top bar, and while asleep it starts nothing but reminders (it still answers) | `1` |
| `EDGE_TTS_VOICE_EN` | English voice | `en-US-AriaNeural` |
| `MEMORY_ENABLED` | Enable new memory extraction | `1` |
| `MEMORY_CONSOLIDATION` | Compare and merge candidates with stored memories; `0` restores exact-text deduplication only | `1` |
| `MEMORY_RELEVANT_RECALL` | Prefer lexical matches to the current user message, then fill by recency; `0` restores newest-first recall | `1` |
| `MEMORY_SEMANTIC_RECALL` | Enable semantic recall when an embedding model is configured; sends stored memory text and the user message to the embeddings endpoint | `0` |
| `EMBEDDING_MODEL` | Embedding model identifier; uses the chat base URL and API key. Empty disables semantic recall even when its flag is on | Empty |
| `CONVERSATION_SUMMARY` | Fold older turns into a running summary; `0` disables updates and summary context | `1` |
| `MEMORY_LIMIT` | Maximum retained memory entries | `24` |
| `COMPANION_DATA_DIR` | Where memory, chat history, settings, and logs are stored | Platform user data directory |
| `COMPANION_SYSTEM_PROMPT` | Expert override for the whole system instruction; when set it replaces the persona and the first-start persona dialog is skipped | Empty (use the persona) |
| `LIVE2D_MODEL` | Model folder under `models/` (`whale-girl`, `hiyori`) or a path to a `.model3.json` | `whale-girl` |
| `LIVE2D_VENDOR_DIR` | Optional renderer dependency directory | `vendor/` |

Variables already set in the shell take precedence over values in `.env`.

**API key in the system keychain.** Open **Settings…** from the right-click menu and paste a key under *API key* to store it in the operating system's keychain (macOS Keychain, Windows Credential Manager, or the Secret Service on Linux) through the `keyring` package. A key in the keychain takes precedence over `OPENAI_API_KEY`/`MOONSHOT_API_KEY`; **Remove from keychain** deletes it and falls back to the environment again. Chat uses a new key immediately. The dialog shows only where the key comes from, never the key itself, and the key is never written to `config.json` or the logs. Set `COMPANION_KEYCHAIN=0` to skip the keychain entirely, for example on a headless Linux machine without a secret service.

You can also add an optional `"settings"` object to `config.json` in the user data directory, alongside `"window"`, for example `"settings": {"MEMORY_LIMIT": 32, "CHAT_THINKING": true, "LOG_LEVEL": "DEBUG"}`. Keys use the environment variable names above; values may be strings, numbers, or booleans (`true` becomes `"1"`, `false` becomes `"0"`). Precedence is built-in defaults < `config.json` settings < environment variables (including `.env`). API keys and any key containing `KEY`, `SECRET`, `TOKEN`, or `PASSWORD`, as well as `COMPANION_DATA_DIR`, are ignored in this object. Loading these settings never writes to `config.json`.

`MEMORY_ENABLED=0` stops new extraction. Existing memories are still loaded into chat context by the current implementation.

## Wake word setup

Wake detection is off by default. The optional `vosk` package is not in `requirements.txt`; install it separately with pip into the same Python environment that runs the app:

```powershell
# Windows (PowerShell), using the Quick start environment
.\venv\Scripts\python.exe -m pip install vosk
```

```bash
# macOS / Linux, using the Quick start environment
.venv/bin/python -m pip install vosk
```

Download a model for your wake phrases' language from the [official Vosk models page](https://alphacephei.com/vosk/models) and unpack it. Set `WAKE_WORD_MODEL_DIR` to the unpacked model directory, not the downloaded archive. For example, add this to `.env`, replacing both placeholders with your model directory's absolute path and a transcription model supported by your chat provider:

```dotenv
WAKE_WORD=1
WAKE_WORD_PHRASES=hey whale,hello whale
WAKE_WORD_MODEL_DIR=<unpacked-model-directory>
VOICE_INPUT=1
TRANSCRIPTION_MODEL=<provider-transcription-model>
```

Restart the app after changing settings. Wake phrases are comma-separated (full-width commas also work). Voice transcription requires the configured chat endpoint to support `/audio/transcriptions`, using the same base URL and API key as chat. When “Wake word on” is visible, say a wake phrase, then speak your message during the roughly five-second capture. Listening pauses during capture, transcription, and replies; detections are ignored while the chat input contains typed text.

Empty wake phrases or an empty model directory leave wake detection disabled, as do disabled voice input or an empty transcription model. If `vosk` or a required dependency is missing, the model directory does not exist, or the model fails to load, the app logs a warning, stops wake listening, and disables wake detection for the session. Hold-to-talk and typed chat remain available; fix the installation or model path and restart to retry.

## Command-line tools

### Inspect stored memories

Use the CLI without installing the GUI dependencies:

```bash
python -m companion.memory_cli list
python -m companion.memory_cli list --limit 5
python -m companion.memory_cli search "咖啡"
python -m companion.memory_cli show 1
python -m companion.memory_cli edit 1 "Corrected memory text"
python -m companion.memory_cli edit 1 "Corrected memory text" --write
python -m companion.memory_cli --data-dir /path/to/data list
```

The default directory follows the app's settings, including `COMPANION_DATA_DIR`
from the environment or `.env`. Lists are newest first; indices are stable,
1-based positions in the stored file and also work with `show` and `edit`. Search
matches case-insensitive substrings. By default, `edit` is a dry run: it prints the
old and new summary without changing the file. Summaries use the store's whitespace
normalization and shortening. With `--write`, it first copies the original file to
`memory.json.bak` in the same directory (overwriting an older backup), then saves
the correction and updates that entry's timestamp if the normalized summary changes.
Invalid indices, empty text, missing files, and exact duplicate summaries are rejected. Only `edit --write`
saves data; none of these commands migrate data.

### Edit settings

Inspect or change the editable, non-secret settings in the user data directory's
`config.json` without GUI dependencies:

```bash
python -m companion.settings_cli list
python -m companion.settings_cli show LOG_LEVEL
python -m companion.settings_cli set MEMORY_LIMIT 32
python -m companion.settings_cli set CHAT_TOOLS true --write
python -m companion.settings_cli --data-dir /path/to/data set LOG_LEVEL DEBUG --write
```

`list` and `show` report merged configuration values and their source: default,
`config.json`, or environment (highest precedence). Values use the core loader's
text representation, including `"1"`/`"0"` for stored booleans; `show` also describes
the setting's type and allowed values. For `set`, use `true`/`false` for booleans,
JSON numbers for numeric settings, and plain text for strings and choices.
By default, `set` prints the old and new stored values without changing the file.
`--write` saves atomically, creating a missing file and preserving the `window`
section and all other keys. Changes apply on the next configuration load; an
environment override is reported when editing. Directory selection follows the
memory CLI, including `COMPANION_DATA_DIR` and `.env`. Unknown, invalid, secret,
and non-editable settings (including `COMPANION_DATA_DIR`) are rejected.
