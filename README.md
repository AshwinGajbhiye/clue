# ✦ Clue — Standalone Stealth Copilot

**Clue** is a screen-share-invisible AI copilot designed for live technical interviews, high-stakes meetings, and screen-based problem solving. 

> **100% visible to you. Completely invisible to Zoom, Google Meet, Teams, Discord, and all screen recorders.**

Powered by **Google Antigravity (AGY)**: **NO external API keys required!** It uses your existing authenticated Antigravity account directly.

---

## ⚡ Quickstart for Friends using Antigravity (Zero API Key Needed!)

If you have **Antigravity** installed on your Mac, you're 100% ready to go. You do **NOT** need to create or paste any Gemini API key, credit card, or third-party service.

### Step 1: Clone the repository
```bash
git clone https://github.com/AshwinGajbhiye/clue.git
cd clue
```

### Step 2: Run the automated setup
```bash
./setup.sh
```
*The installer automatically detects your Antigravity installation (`agy`), builds the local virtualenv, installs audio dependencies, and hooks directly into your Antigravity session.*

### Step 3: Launch Clue!
```bash
./run.sh
```

Clue will appear as a sleek, translucent floating pill on your screen.

---

## 🤖 How the Antigravity Integration Works

Clue connects directly to your local **Google Antigravity (`agy`)** runtime:
1. When audio or text questions arrive, Clue queries Antigravity via non-blocking token streaming.
2. It uses your existing signed-in Google Antigravity account.
3. No API rate-limits, zero subscription prompts, and no secret keys to manage in `.env`.

*(Note: If you ever run Clue on a machine without Antigravity, you can optionally put a free `GEMINI_API_KEY` in `.env` as a fallback).*

---

## ⌨️ Global Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| **Pill Click** or `⌥ C` (Option + C) | **Toggle Chat Drawer** (Show / Hide flyout) |
| `Cmd + Return` or `⌥ A` (Option + A) | **Instant Solve** (Flush speech buffer & stream answer) |
| `⌥ O` (Option + O) | **Screen Snippet** (Drag crosshair to snip & solve visual problem) |
| `⌥ [` / `⌥ ]` | **Cycle Opacity** (Ghost 40% → Balanced 65% → Focus 85%) |
| `Enter` | **Submit typed question** in the input bar |
| `Esc` | **Close chat drawer** |

---

## 🔒 macOS Permissions (First Run)

On first launch, macOS will ask for permissions. Make sure to allow them in **System Settings → Privacy & Security**:

| Permission | Why It's Needed |
| :--- | :--- |
| **Microphone** | Captures live spoken questions from your mic & headphones |
| **Accessibility** | Listens for global hotkeys (`⌥A`, `⌥C`, `Cmd+Return`) |
| **Screen Recording** | Allows the screen snip tool (`⌥O`) to capture problem regions |

---

## 🏛 Architecture

```
clue/
├── setup.sh                  ← Automated one-command setup
├── run.sh                    ← Launcher script
├── run_clue.py               ← Main application entrypoint
├── requirements.txt          ← Python dependencies
├── clue/
│   ├── config.py             ← Environment & settings
│   ├── orchestrator.py       ← Two-window coordinator (Pill + Drawer)
│   ├── core/
│   │   ├── antigravity_engine.py   ← Antigravity CLI (agy) zero-key streaming
│   │   ├── ai_engine.py            ← Fallback streaming worker
│   │   ├── audio_rules.py          ← Continuous VAD rules engine
│   │   ├── audio_engine.py         ← Dual-channel mic/system capture
│   │   ├── system_audio_tap.py     ← CoreAudio loopback tap
│   │   └── screen_service.py       ← Screen snip capture
│   └── ui/
│       ├── pill_window.py    ← Floating control pill (always visible)
│       ├── chat_drawer.py    ← Flyout response drawer
│       ├── overlay_panel.py  ← macOS NSPanel stealth config (NSWindowSharingNone)
│       └── syntax_styler.py  ← ChatGPT-style colorful syntax highlighting
```
