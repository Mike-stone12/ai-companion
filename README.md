# AI Companion

[![CI](https://github.com/Mike-stone12/ai-companion/actions/workflows/ci.yml/badge.svg)](https://github.com/Mike-stone12/ai-companion/actions/workflows/ci.yml)
[![Package](https://github.com/Mike-stone12/ai-companion/actions/workflows/package.yml/badge.svg)](https://github.com/Mike-stone12/ai-companion/actions/workflows/package.yml)

**A Live2D character that lives on your desktop, talks with you out loud, and remembers what you tell it.**

AI Companion puts an animated character in a small transparent window on your screen. You chat with it in text or by voice; it answers in a natural voice with matching lip sync and facial expressions, keeps the conversation across restarts, and gradually remembers facts about you. Out of the box it plays your childhood friend from next door (青梅竹马), and you can describe any other personality you like.

It runs on macOS, Windows, and Linux, and works with any OpenAI-compatible chat API (Moonshot/Kimi, DeepSeek, and others) using your own API key.

[Quick start](#quick-start) · [Persona](#persona) · [Configuration](#configuration) · [Privacy](#privacy) · [License](#license)

## Highlights

- **A character, not a chat box.** A frameless, draggable Live2D avatar with idle motions, emotion expressions picked by the model (happy, shy, surprised, …), and mouth movement that follows its voice.
- **Texts like a friend.** A reply arrives as one to four short messages with a "typing…" pause between them, a little later when it is busy or asleep; the first one is spoken as soon as it is complete.
- **Speaks as it thinks.** Replies stream in and the first sentence is spoken while the rest is still being written; median time to the first spoken word is about 1.7 s. Chinese and English voices are chosen automatically (Edge TTS), with a lively, slightly raised Chinese voice by default.
- **Real feelings, with a personality you set.** It can be happy, annoyed, hurt, jealous, or miss you, each for a reason it remembers; how strongly it reacts depends on personality sliders (quick to anger, jealous, easily hurt, gets over things quickly, candid or tsundere). A sincere apology for the actual thing works better than a quick "sorry", and when you are genuinely upset it sets its own feelings aside to look after you. It never guilt-trips you or threatens to leave.
- **Keeps a diary.** The day after you talk it writes a short diary entry in its own voice, and it remembers what it has said about itself (favourite things, promises) so it stays consistent. You can read both under **Memories…**.
- **A life of its own.** Its mood carries over from one reply to the next and fades over a couple of hours; after a day without hearing from you it misses you, and the idle face shows how it feels. It also keeps a daily routine: in class in the morning, free in the evening, sleepy late at night, asleep after half past midnight. It still answers when asleep (groggily), and while asleep it starts nothing but your reminders.
- **Remembers you.** Short facts ("you like coffee", "your exam is on Friday") are extracted in the background, merged with what it already knows, and brought back when relevant. Older conversation is folded into a running summary.
- **A personality you choose.** Pick or write the companion's name, relationship to you, personality, and speaking style. See [Persona](#persona).
- **Your key stays in the keychain.** The API key is stored in the operating system's keychain from the Settings dialog, never in a settings file or the logs.
- **Sees your pictures.** Send one with the **Picture** button, paste, or drag-and-drop; a vision model describes it and the companion answers in its own voice. On a DeepSeek endpoint this needs no setup.
- **Optional extras**, all off by default: hold-to-talk voice input, an offline wake word, proactive chat (greetings, check-ins, reminders), and a gentle nudge after long sessions in the same app, such as 40 minutes of gaming.

## Quick start

You need an API key from an OpenAI-compatible provider. The defaults point at [Moonshot (Kimi)](https://platform.moonshot.ai/); DeepSeek and others work by changing the endpoint and model.

### Option A: download a build

Builds for macOS, Windows, and Linux are produced automatically by the [Package workflow](https://github.com/Mike-stone12/ai-companion/actions/workflows/package.yml). There is no tagged release yet; until there is, open the latest successful run on `agent-dev` or `master` and download the archive for your system from **Artifacts** (a GitHub login is required).

| System | Archive | Start it |
| --- | --- | --- |
| macOS (Apple silicon) | `AI-Companion-macOS.zip` | Unzip and open `AI Companion.app`. The build is not signed: the first time, right-click the app and choose **Open**, or run `xattr -dr com.apple.quarantine "AI Companion.app"`. |
| Windows | `AI-Companion-Windows.zip` | Unzip and run `AI Companion\AI Companion.exe`. If SmartScreen warns about an unknown publisher, choose **More info → Run anyway**. |
| Linux | `AI-Companion-Linux.tar.gz` | `tar -xzf AI-Companion-Linux.tar.gz` and run `"AI Companion/AI Companion"`. |

The packaged builds include both characters and everything except the optional wake word. They bundle the default whale-girl character, which is licensed for **non-commercial use only** (CC BY-NC-SA 4.0); `LICENSE` and `NOTICE.md` are in every archive. See [License](#license).

### Option B: run from source

Requires Python 3.11 or newer.

```bash
git clone https://github.com/Mike-stone12/ai-companion.git
cd ai-companion
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

On Windows (PowerShell):

```powershell
git clone https://github.com/Mike-stone12/ai-companion.git
cd ai-companion
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

### First start

1. **Choose a persona.** A dialog asks who your companion should be. Keep the childhood friend or edit it, then click **Save** (or **Keep default**).
2. **Add your API key.** Right-click the character and choose **Settings…**. Paste the key under *API key* and click **Save to keychain**; chat uses it immediately.
3. **Pick a provider (optional).** In the same dialog, set *Chat API base URL* and *Chat model*, for example `https://api.deepseek.com/v1` and `deepseek-flash`, click **Save**, and restart the app.
4. **Say hi.** Type in the box under the character and press Enter.

Without a key the app runs in a demo mode that answers with a fixed message. Right-click the character any time for size, opacity, always on top, persona, settings, memories, and quit; drag the **Drag me** bar above it to move it.

To check an installation without using the network, run it with `--self-test` (for example `.venv/bin/python main.py --self-test`). It prints a PASS/FAIL report and exits.

## Persona

The persona is who the companion is. It becomes the model's instructions, so it shapes every reply, including the messages the companion starts on its own.

| Field | What it does |
| --- | --- |
| Companion's name | Its name. Leave it empty and it will take a name you give it in conversation. |
| What it calls you | Your name or nickname, if you want one used. |
| Relationship to you | Who it is to you: childhood friend, older sister, study partner, … |
| Personality | Temperament and attitude. |
| Speaking style | How it talks: casual or polite, teasing, short sentences, … |
| Background | Anything else it should know about its situation. |
| Personality sliders | How quickly it gets annoyed, jealous, or hurt, how fast it gets over things, how candid it is, and how it shows being upset (says it straight, sarcastic, goes cold, sulks cutely). |
| Daily routine | One time block per line, e.g. `08:30-12:00 [busy] in class`; kinds are `busy`, `drowsy`, `asleep`, or free time. The top bar shows what it is doing. |

The default persona is a **childhood friend** who grew up next door: warm, a little teasing, honest rather than flattering, and quick to notice when you are tired. Whatever persona you choose, the companion talks directly to you, replies in the language you write in, and does not invent shared memories you never mentioned.

Change it any time with **Persona…** in the right-click menu; the next reply uses it. The persona is saved in `persona.json` in your [data directory](#privacy). Proactive messages and the long-session nudge also speak in the persona's voice, to you. Advanced users can replace the whole instruction with the `COMPANION_SYSTEM_PROMPT` setting, which overrides the persona.

## Configuration

Most things can be changed from **Settings…** in the right-click menu; changes apply on the next start. You can also put settings in a `.env` file (copy [`.env.example`](.env.example)), which takes precedence. For a source checkout `.env` sits in the repository folder; for a packaged build it goes next to the executable (`AI Companion.app/Contents/MacOS/.env` on macOS).

| Setting | Default | |
| --- | --- | --- |
| `OPENAI_BASE_URL` | `https://api.moonshot.ai/v1` | Chat endpoint (OpenAI-compatible) |
| `OPENAI_MODEL` | `kimi-k2.6` | Chat model |
| `VISION_MODEL` / `VISION_BASE_URL` | automatic on DeepSeek | Picture model and endpoint; another provider needs its own key (Settings… > Pictures key) |
| `OPENAI_API_KEY` | | Fallback when no key is in the keychain |
| `LIVE2D_MODEL` | `whale-girl` | Character: `whale-girl` or `hiyori` |
| `EDGE_TTS_VOICE_ZH` / `EDGE_TTS_VOICE_EN` | Xiaoyi / Aria | Voices for Chinese and English replies |
| `TTS_PITCH` / `TTS_RATE` | `+10Hz` / `+6%` | Pitch and speed offsets for the Chinese voice |
| `TTS_PROVIDER` + `TTS_MODEL` / `TTS_VOICE` | Edge | A custom voice from any OpenAI-compatible `/audio/speech` service (or a local server); falls back to Edge TTS. Another provider needs its own key (Settings… > Voice key). Use AI-generated or licensed voices only |
| `COMPANION_STATE` | on | Feelings that carry over between replies and colour the voice (`MOOD_HALF_LIFE_MINUTES`, default 120); right-click > **Companion state…** shows them. `EMOTION_APPRAISAL` (on) spends one extra small request on emotional turns only |
| `DAILY_SCHEDULE` | on | The daily routine from the persona: sleeping, busy, and drowsy times |
| `COMPANION_DIARY` | on | A diary entry for each day you talked, and its own memories about itself |
| `REPLY_PACING` | on | Replies arrive as a few short messages with "typing…" pauses, like texting |
| `VOICE_INPUT` + `TRANSCRIPTION_MODEL` | off | Hold-to-talk button (needs a transcription model from your provider) |
| `PROACTIVE_CHAT` | off | Greetings, idle check-ins, and spoken reminders; with its feelings on, it also reaches out when it misses you or is happy, and waits to be coaxed when annoyed |
| `ACTIVE_APP_MONITOR` | off | One caring remark after about 40 minutes in the same app (needs `PROACTIVE_CHAT`; Windows and macOS) |
| `CHAT_TOOLS` | off | Lets the model tell the time and set reminders |
| `WAKE_WORD` | off | Offline wake phrase (source install with Vosk; see the guide) |

The full list, the wake word setup, and command-line tools for memories and settings are in **[docs/configuration.md](docs/configuration.md)**.

## Privacy

- Your messages, recalled memories, and the persona are sent to the chat API you configure. Replies are sent to Microsoft Edge's text-to-speech service to be spoken. Voice input, when enabled, is sent to your provider's transcription endpoint. A picture is uploaded to the vision endpoint only when you send it, and your chat key is never sent to a different provider.
- The long-session nudge sends only the foreground app's name and how long it has been in front, nothing else.
- Memories, chat history, settings, the persona, its feelings, and its diary are stored locally as plain JSON in your data directory: `~/Library/Application Support/AICompanion/` on macOS, `%APPDATA%\AICompanion\` on Windows, `~/.local/share/ai-companion/` on Linux. **Memories…** in the right-click menu lets you review and edit what it remembers.
- The API key lives in the system keychain (or your own `.env`), never in those files or the logs.

## Troubleshooting

- **It answers with a demo message:** no API key was found. Add one in **Settings…** (see [First start](#first-start)).
- **Chat fails:** check the key, the endpoint, the model name, and your network. Logs are in `logs/companion.log` in the data directory.
- **No voice:** speech needs network access to Edge TTS; on a slow connection a reply may be shown as text only.
- **No character appears (virtual machine or no GPU):** the avatar needs WebGL, which Chromium disables without a usable GPU. Start the app with the environment variable `QTWEBENGINE_CHROMIUM_FLAGS` set to render it in software: `--ignore-gpu-blocklist` on Windows, or `--use-gl=angle --use-angle=swiftshader --enable-unsafe-swiftshader` on macOS and Linux. `--self-test` shows whether the model renders.
- **The character is off-screen or too big:** right-click it and choose **Reset position** or a smaller size.
- **macOS says the app is damaged:** it is unsigned; see [Option A](#option-a-download-a-build).
- **macOS asks for keychain access again after an update:** an unsigned build gets a new code signature with every version, so macOS asks once more whether it may read the stored key. Choose **Always Allow**.

More in [docs/configuration.md](docs/configuration.md#settings) and [docs/architecture.md](docs/architecture.md).

## For developers

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest
```

The core (`companion/core`) is pure Python and tested without Qt on Ubuntu, Windows, and macOS; every pull request is also packaged on all three systems and smoke-tested with `--self-test`. See [docs/development.md](docs/development.md) for packaging and evaluation, [docs/architecture.md](docs/architecture.md) for how memory, streaming, and the persona work, and [CLAUDE.md](CLAUDE.md) for project conventions.

## Roadmap

- [x] Live2D desktop character with streaming chat, voice replies, lip sync, and emotion expressions
- [x] Persistent memory with consolidation, relevant recall, and conversation summaries
- [x] Settings, persona, and memory dialogs; API key in the OS keychain
- [x] Opt-in voice input, wake word, proactive chat, reminders, and long-session nudges
- [x] Packaged builds for macOS, Windows, and Linux, built and smoke-tested in CI
- [x] A mood that carries over and a daily routine; a livelier default voice
- [x] Personality-driven emotions, texting-style replies, a diary, pictures, and a custom voice provider
- [ ] An AI-designed voice of its own (Qwen voice design or a local voice-design model)
- [ ] First tagged release with downloadable builds
- [ ] Persona presets library and import/export
- [ ] Hands-on testing of the packaged builds on Windows and Linux desktops
- [ ] Refine voice input and the wake word with real-device feedback
- [ ] Demo GIF
- [ ] Publish live memory-extraction evaluation numbers

## License

The **source code** is released under the [MIT License](LICENSE).

The characters and renderer runtime are **not** covered by the MIT License:

- **Whale girl** (the default character) is licensed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). **It may not be used commercially**, including in any paid product or service. Character design by 上善无形, DeepSeek-themed maid redesign by ZipZipPipe, Live2D model by 氵六青, via [Andersen216/dsh-whale-girl-live2d](https://github.com/Andersen216/dsh-whale-girl-live2d). This is fan art; the project is not affiliated with DeepSeek. For commercial use, switch to another model (`LIVE2D_MODEL=hiyori`) and check its license.
- **Hiyori** (© Live2D Inc.) is used under the Live2D Free Material License; see [`models/hiyori/LIVE2D_README.txt`](models/hiyori/LIVE2D_README.txt).
- **Live2D Cubism Core** is under the Live2D Proprietary Software License; PixiJS and pixi-live2d-display are MIT.

Full terms and attribution are in [NOTICE.md](NOTICE.md).
