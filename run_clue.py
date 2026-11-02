#!/usr/bin/env python3
"""
Clue — Standalone Stealth Copilot (Cluely Clone)
=================================================
Two-window architecture exactly like Cluely:
  T  — Control Pill (220×44 floating pill, always visible)
  w  — Chat Drawer (720×540 flyout, summon on pill click / Cmd+Return)

Run:
    /path/to/python3 run_clue.py
Hotkeys:
    Pill click / ⌥C        → Toggle chat drawer
    Cmd+Return / ⌥A        → Instant solve from live audio
    ⌥O                     → Screen snippet & solve
    Escape                 → Close chat drawer
    ⌥[ / ⌥]               → Cycle opacity (Ghost 40% / Balanced 65% / Focus 85%)
"""

import os
import signal
import ssl
import sys
from pathlib import Path

# ── 1. Fix macOS SSL before ANY import ────────────────────────────────────────
try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    ssl._create_default_https_context = lambda: ssl.create_default_context(
        cafile=certifi.where()
    )
except Exception:
    pass

# ── 2. Silence gRPC fork warnings BEFORE gRPC/Antigravity import ──────────────
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"
os.environ["GRPC_POLL_STRATEGY"] = "poll"

# ── 3. Add project root to path ───────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt6.QtWidgets import QApplication
from clue.ui.overlay_panel import ensure_accessory_policy
from clue.orchestrator import ClueApp


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setApplicationName("Clue")
    app.setQuitOnLastWindowClosed(False)   # Keep running even when drawer closes

    # macOS: NSApplicationActivationPolicyAccessory
    # → invisible from Dock, floats over fullscreen apps
    ensure_accessory_policy()

    # Launch two-window Cluely architecture
    clue = ClueApp()
    clue.show()

    print("════════════════════════════════════════════════════════════════")
    print("  ✦ Clue Stealth Copilot Active (Screen-Share Invisible)")
    print("  ● Pill: Click to toggle chat drawer | 🎙️ button to toggle mic")
    print("  ● Hotkeys: Cmd+Return (Instant Solve) | ⌥M (Mute) | ⌥O (Snip) | ⌥C (Toggle)")
    print("  ● Audio: Continuous 24/7 capture ACTIVE automatically")
    print("════════════════════════════════════════════════════════════════")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
