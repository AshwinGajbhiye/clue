"""
Clue — Cluely-Exact Master Orchestrator
========================================
Coordinates the two-window architecture (Control Pill + Chat Drawer)
exactly as Cluely's dist-electron/main.js coordinates its BrowserWindows:

  T (Control Pill):   163×44 floating pill — always visible
  w (Chat Drawer):    690×520 flyout — summoned on click / hotkey
  Audio Engine:       Dual-channel continuous capture (never stops)
  AI Pipeline:        Warm Antigravity Agent → sub-second streaming
"""

import sys
import threading
from typing import Optional

from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtWidgets import QApplication

from clue.config import Config
from clue.core.antigravity_engine import get_warm_antigravity
from clue.core.audio_rules import AudioSessionState, ContinuousAudioRulesEngine
from clue.ui.chat_drawer import ChatDrawer
from clue.ui.pill_window import ControlPill
from clue.ui.overlay_panel import ensure_accessory_policy


class ClueApp:
    """
    Master orchestrator — owns both windows and routes all signals
    between the Control Pill, Chat Drawer, and Audio Rules Engine.
    """

    def __init__(self):
        self._chat_open = False
        self._listening = False

        # ── Audio Rules Engine (the audio never stops) ────────────────────────
        self.audio_rules = ContinuousAudioRulesEngine(auto_answer_questions=True)

        # ── Control Pill (T) ──────────────────────────────────────────────────
        self.pill = ControlPill()
        self.pill.toggle_chat_requested.connect(self._toggle_chat)
        self.pill.toggle_listening_requested.connect(self._toggle_listening)
        self.pill.instant_solve_requested.connect(self._instant_solve)
        self.pill.screen_snip_requested.connect(self._start_snip)

        # Forward audio signals to pill and orchestrator
        self.audio_rules.audio_energy_updated.connect(self.pill.set_energy)
        self.audio_rules.status_changed.connect(self._on_audio_status)
        self.audio_rules.question_ready_for_answer.connect(self._on_question_detected)

        # ── Chat Drawer (w) ───────────────────────────────────────────────────
        self.drawer = ChatDrawer(audio_rules=self.audio_rules)
        self.drawer.listening_toggled.connect(self._toggle_listening)
        self.drawer.device_cycle_requested.connect(self.drawer._cycle_device)
        self.drawer.instant_solve_requested.connect(self._instant_solve)
        self.drawer.screen_snip_requested.connect(self._start_snip)
        self.drawer.close_requested.connect(self._close_chat)
        self.drawer.answer_completed.connect(self._on_answer_completed)

        # ── Pre-warm Antigravity in background ────────────────────────────────
        threading.Thread(target=get_warm_antigravity, daemon=True, name="ClueWarmup").start()

    def show(self):
        """Show only the pill initially, and start continuous audio listening immediately."""
        self.pill.show()
        # Cluely 24/7 ambient continuous audio capture starts on launch
        QTimer.singleShot(150, self._start_initial_listening)

    def _start_initial_listening(self):
        if not self._listening:
            self._toggle_listening()

    # ── WINDOW COORDINATION ──────────────────────────────────────────────────
    def _pill_rect(self) -> QRect:
        return QRect(self.pill.x(), self.pill.y(), self.pill.width(), self.pill.height())

    def _toggle_chat(self):
        if self._chat_open:
            self._close_chat()
        else:
            self._open_chat()

    def _open_chat(self):
        if self._chat_open:
            return
        self._chat_open = True
        self.pill.set_chat_open(True)
        self.drawer.open_below(self._pill_rect(), animate=True)

    def _close_chat(self):
        if not self._chat_open:
            return
        self._chat_open = False
        self.pill.set_chat_open(False)
        self.drawer.close_drawer(animate=True)

    # ── LISTENING LIFECYCLE ──────────────────────────────────────────────────
    def _toggle_listening(self):
        if self.audio_rules.state == AudioSessionState.IDLE:
            ok, msg = self.audio_rules.start_listening()
            self._listening = ok
            self.pill.set_listening(ok)
            self.drawer.update_listen_button(ok, f"● {msg}" if ok else f"⚠️ {msg}")
        else:
            self.audio_rules.stop_listening()
            self._listening = False
            self.pill.set_listening(False)
            self.drawer.update_listen_button(False, "Audio paused.")

    def _on_audio_status(self, msg: str):
        if self.drawer.isVisible():
            self.drawer.status_lbl.setText(msg)

    # ── INSTANT SOLVE (Cmd+Return — Cluely exact) ─────────────────────────────
    def _instant_solve(self):
        # Open drawer if not already open so user sees the answer
        if not self._chat_open:
            self._open_chat()
        self.audio_rules.trigger_instant_ask()

    # ── SCREEN SNIP ──────────────────────────────────────────────────────────
    def _start_snip(self):
        if not self._chat_open:
            self._open_chat()
        self.drawer.start_snip()

    # ── GENERATING PILL STATE ─────────────────────────────────────────────────
    def _on_generating_started(self):
        self.pill.set_generating(True)

    def _on_generating_done(self):
        self.pill.set_generating(False)

    def _on_question_detected(self, question: str, transcript: str):
        """When an interview question is detected from audio, open drawer and start generating."""
        if not self._chat_open:
            self._open_chat()
        self.pill.set_generating(True)

    def _on_answer_completed(self, question: str, full_answer: str):
        """When AI answer finishes streaming, return pill to listening state."""
        self.pill.set_generating(False)
