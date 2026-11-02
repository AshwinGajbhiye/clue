"""
Clue UI — Chat Drawer Window (Cluely-exact clone)
=================================================
The main chat/answer panel (690×520) — appears anchored magnetically below the
control pill when summoned. Matches Cluely's chat window (w) architecture:

  - Screen-saver level, NSWindowSharingNone, 0x151 multi-space sticky
  - Frosted glass translucency (variable opacity)
  - Live token-stream rendering: WHAT TO SAY sections appear as they arrive
  - ChatGPT-style syntax highlighting with Pygments
  - Session Q&A history
  - Screen snip integration
  - Cmd+Return instant solve
  - Escape or pill click collapses
"""

import sys
import threading
import time
from typing import Dict, List, Optional

from PyQt6.QtCore import (
    Qt, QPoint, QRect, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
)
from PyQt6.QtGui import (
    QColor, QFont, QCursor, QKeySequence, QPainter, QPainterPath, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget
)

from clue.config import Config
from clue.core.ai_engine import LLMStreamWorker
from clue.core.antigravity_engine import get_warm_antigravity
from clue.core.audio_engine import Role
from clue.core.audio_rules import AudioSessionState, ContinuousAudioRulesEngine
from clue.core.interview_modes import InterviewMode, MODE_DISPLAY_NAMES
from clue.core.screen_service import ScreenSnipperWorker, capture_screen_bytes
from clue.ui.overlay_panel import (
    clamp_to_visible_screen, configure_overlay_panel, reassert_overlay
)
from clue.ui.styles import (
    BUTTON_PRIMARY_STYLESHEET,
    BUTTON_SECONDARY_STYLESHEET,
    INPUT_STYLESHEET,
    PALETTE,
    get_hud_stylesheet,
)
from clue.ui.syntax_styler import render_markdown_to_rich_html
from clue.ui.waveform import AudioWaveformWidget

# ── Drawer exact dimensions (matching Cluely) ────────────────────────────────
DRAWER_W   = 720
DRAWER_H   = 540
DRAWER_MAX = 980    # max height on large displays

ANIM_MS    = 210    # open/close animation duration


class ChatDrawer(QWidget):
    """
    Cluely-style chat drawer: frameless, translucent, screen-share invisible,
    anchored magnetically below the control pill. Appears/disappears with a
    smooth height animation matching Cluely's drawer behavior.
    """

    # Forward signals to orchestrator
    listening_toggled = pyqtSignal()
    device_cycle_requested = pyqtSignal()
    instant_solve_requested = pyqtSignal()
    screen_snip_requested = pyqtSignal()
    close_requested = pyqtSignal()
    answer_completed = pyqtSignal(str, str)

    def __init__(self, audio_rules: ContinuousAudioRulesEngine, parent=None):
        super().__init__(parent)
        self.audio_rules = audio_rules

        self.current_mode = InterviewMode.CODING_INTERVIEW
        self.code_policy = "auto"
        self.current_opacity_name = Config.DEFAULT_OPACITY_MODE
        self.current_opacity = Config.get_opacity(self.current_opacity_name)

        self._qa_history: List[Dict[str, str]] = []
        self._current_answer_raw = ""
        self._stream_worker: Optional[LLMStreamWorker] = None
        self._snipper_worker: Optional[ScreenSnipperWorker] = None
        self._pending_bg_question: str = ""
        self._history_visible = False

        # ── Window flags ─────────────────────────────────────────────────────
        self.setWindowTitle("ClueChat")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._build_ui()
        self._setup_shortcuts()

        # ── Smooth open animation ─────────────────────────────────────────────
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # ── Connect audio signals ─────────────────────────────────────────────
        self.audio_rules.audio_energy_updated.connect(self._on_audio_energy)
        self.audio_rules.speech_started.connect(self._on_speech_started)
        self.audio_rules.utterance_transcribed.connect(self._on_utterance_transcribed)
        self.audio_rules.status_changed.connect(self._on_status_changed)
        self.audio_rules.question_ready_for_answer.connect(self._on_question_triggered)
        self.audio_rules.speech_detected_during_answer.connect(self._on_bg_speech_detected)

        # ── Stickiness reassert ───────────────────────────────────────────────
        self._reassert_timer = QTimer(self)
        self._reassert_timer.timeout.connect(lambda: reassert_overlay(self) if self.isVisible() else None)
        self._reassert_timer.start(1200)

        # Pre-warm Antigravity
        threading.Thread(target=get_warm_antigravity, daemon=True).start()

    def showEvent(self, e):
        super().showEvent(e)
        configure_overlay_panel(
            self, level=1000, can_become_key=True,
            screen_share_invisible=True,
            window_title_hint="ClueChat"
        )
        clamp_to_visible_screen(self)

    # ── UI BUILD ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(0)

        # Main glass card
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet(get_hud_stylesheet(self.current_opacity))

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setColor(QColor(0, 0, 0, 170))
        shadow.setOffset(0, 14)
        self.card.setGraphicsEffect(shadow)

        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(16, 12, 16, 14)
        cl.setSpacing(9)

        # ── HEADER ROW ────────────────────────────────────────────────────────
        h = QHBoxLayout()
        h.setSpacing(7)

        self.logo_lbl = QLabel("✦ CLUE", self.card)
        self.logo_lbl.setStyleSheet(
            "color:#38BDF8; font-size:14px; font-weight:900; letter-spacing:1px;"
        )
        h.addWidget(self.logo_lbl)

        # Mode selector
        self.mode_btn = QPushButton(MODE_DISPLAY_NAMES[self.current_mode], self.card)
        self.mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mode_btn.setToolTip("Click to cycle interview mode (Coding / Behavioral / System Design / General)")
        self.mode_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.mode_btn.clicked.connect(self._cycle_mode)
        h.addWidget(self.mode_btn)

        # Code policy
        self.code_btn = QPushButton("💻 Code: On Ask", self.card)
        self.code_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.code_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.code_btn.clicked.connect(self._cycle_code_policy)
        h.addWidget(self.code_btn)

        # Opacity
        self.opacity_btn = QPushButton(
            f"◐ {self.current_opacity_name.title()} ({int(self.current_opacity*100)}%)",
            self.card
        )
        self.opacity_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.opacity_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.opacity_btn.clicked.connect(self._cycle_opacity)
        h.addWidget(self.opacity_btn)

        # Device picker (earphones/mic)
        from clue.core.audio_engine import list_input_devices
        devs = list_input_devices()
        has_earphones = any(d.get("is_earphone") for d in devs)
        self._input_devices = devs
        self._device_idx = 0
        self.device_btn = QPushButton("🎧 Earphones" if has_earphones else "🎙️ Mic", self.card)
        self.device_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.device_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.device_btn.clicked.connect(self._cycle_device)
        h.addWidget(self.device_btn)

        h.addStretch()

        # Stealth badge
        badge = QLabel("🛡️ Invisible", self.card)
        badge.setStyleSheet("""
            color:#10B981; font-size:10px; font-weight:700;
            background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.25);
            border-radius:5px; padding:2px 6px;
        """)
        h.addWidget(badge)

        # Close button
        self.close_btn = QPushButton("✕", self.card)
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.close_btn.setStyleSheet("""
            QPushButton {
                background:rgba(255,255,255,0.06); color:rgba(255,255,255,0.55);
                border:none; border-radius:11px; font-size:10px;
            }
            QPushButton:hover { background:rgba(239,68,68,0.25); color:#EF4444; }
        """)
        self.close_btn.clicked.connect(self.close_requested.emit)
        h.addWidget(self.close_btn)

        cl.addLayout(h)

        # ── TRANSCRIPT TICKER (live rolling transcript) ────────────────────────
        self.transcript_lbl = QLabel("● Awaiting audio or prompt...", self.card)
        self.transcript_lbl.setWordWrap(True)
        self.transcript_lbl.setStyleSheet("""
            color:rgba(255,255,255,0.50); font-size:11px; font-style:italic;
            background:rgba(255,255,255,0.03); border-radius:6px;
            padding:4px 8px;
        """)
        cl.addWidget(self.transcript_lbl)

        # ── INPUT BAR ─────────────────────────────────────────────────────────
        row_in = QHBoxLayout()
        row_in.setSpacing(6)

        self.input_field = QLineEdit(self.card)
        self.input_field.setPlaceholderText(
            "Type a question... or press Cmd+Return to instant-solve from audio"
        )
        self.input_field.setStyleSheet(INPUT_STYLESHEET)
        self.input_field.returnPressed.connect(self._on_submit)
        row_in.addWidget(self.input_field, 1)

        self.ask_btn = QPushButton("↵ Ask", self.card)
        self.ask_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.ask_btn.setStyleSheet(BUTTON_PRIMARY_STYLESHEET)
        self.ask_btn.clicked.connect(self._on_submit)
        row_in.addWidget(self.ask_btn)

        cl.addLayout(row_in)

        # ── TOOLBAR ───────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(7)

        self.listen_btn = QPushButton("🎙️ Start Listening", self.card)
        self.listen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.listen_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.listen_btn.clicked.connect(self.listening_toggled.emit)
        toolbar.addWidget(self.listen_btn)

        self.waveform = AudioWaveformWidget(self.card)
        self.waveform.setFixedSize(52, 22)
        toolbar.addWidget(self.waveform)

        self.status_lbl = QLabel("Click 'Start Listening' to begin", self.card)
        self.status_lbl.setStyleSheet("color:rgba(255,255,255,0.50); font-size:11px;")
        toolbar.addWidget(self.status_lbl)

        toolbar.addStretch()

        self.snip_btn = QPushButton("🖼 Snip", self.card)
        self.snip_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.snip_btn.setToolTip("Snip region of screen & solve (⌥O)")
        self.snip_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.snip_btn.clicked.connect(self.screen_snip_requested.emit)
        toolbar.addWidget(self.snip_btn)

        self.copy_btn = QPushButton("📋 Copy", self.card)
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.copy_btn.clicked.connect(self._copy_answer)
        toolbar.addWidget(self.copy_btn)

        self.history_btn = QPushButton("📜 History", self.card)
        self.history_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.history_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.history_btn.clicked.connect(self._toggle_history)
        toolbar.addWidget(self.history_btn)

        cl.addLayout(toolbar)

        # ── BACKGROUND SPEECH ALERT BANNER ───────────────────────────────────
        self.bg_banner = QFrame(self.card)
        self.bg_banner.setObjectName("inner_box")
        self.bg_banner.hide()
        bg_row = QHBoxLayout(self.bg_banner)
        bg_row.setContentsMargins(10, 5, 10, 5)
        bg_row.setSpacing(8)
        self.bg_lbl = QLabel("", self.bg_banner)
        self.bg_lbl.setStyleSheet("color:#38BDF8; font-size:11.5px; font-weight:600;")
        bg_row.addWidget(self.bg_lbl, 1)
        self.bg_solve_btn = QPushButton("⚡ Answer Now", self.bg_banner)
        self.bg_solve_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.bg_solve_btn.setStyleSheet(BUTTON_PRIMARY_STYLESHEET)
        self.bg_solve_btn.clicked.connect(self._solve_bg_question)
        bg_row.addWidget(self.bg_solve_btn)
        cl.addWidget(self.bg_banner)

        # ── ACTIVE QUESTION TITLE ─────────────────────────────────────────────
        self.q_title = QLabel("Awaiting prompt or live audio...", self.card)
        self.q_title.setWordWrap(True)
        self.q_title.setStyleSheet("""
            color:#FFFFFF; font-size:13px; font-weight:700;
            background:rgba(56,189,248,0.08); border:1px solid rgba(56,189,248,0.18);
            border-radius:8px; padding:7px 11px;
        """)
        cl.addWidget(self.q_title)

        # ── ANSWER BROWSER (rich HTML, custom scrollbar) ─────────────────────
        self.answer_browser = QTextBrowser(self.card)
        self.answer_browser.setOpenExternalLinks(False)
        self.answer_browser.setReadOnly(True)
        self.answer_browser.setMinimumHeight(340)
        self.answer_browser.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.answer_browser.setStyleSheet("""
            QTextBrowser {
                background-color: transparent;
                border: 1px solid rgba(255,255,255,0.07);
                border-radius: 12px;
                padding: 12px 14px;
                font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, monospace;
                font-size: 13px;
                color: #E2E8F0;
                line-height: 1.65;
            }
            QScrollBar:vertical {
                background: transparent; width: 5px; margin: 3px 1px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.20); border-radius:2px; min-height:24px;
            }
            QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.42); }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
        """)
        cl.addWidget(self.answer_browser, 1)

        root.addWidget(self.card)

    def _setup_shortcuts(self):
        # Cmd+Return (macOS: Meta+Return via Qt) → instant solve
        QShortcut(QKeySequence("Ctrl+Return"), self, self._instant_solve)
        QShortcut(QKeySequence("Meta+Return"), self, self._instant_solve)
        QShortcut(QKeySequence("Alt+A"), self, self._instant_solve)
        QShortcut(QKeySequence("Alt+O"), self, self.screen_snip_requested.emit)
        QShortcut(QKeySequence("Alt+["), self, self._cycle_opacity)
        QShortcut(QKeySequence("Alt+]"), self, self._cycle_opacity)
        QShortcut(QKeySequence("Escape"), self, self.close_requested.emit)

    # ── OPEN / CLOSE ANIMATION anchored below pill ────────────────────────────
    def open_below(self, pill_rect: QRect, animate: bool = True):
        """Slide the drawer open, magnetically anchored below the pill."""
        x = pill_rect.left() + (pill_rect.width() - DRAWER_W) // 2
        y = pill_rect.bottom() + 8

        # Clamp to screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x = max(sg.left() + 4, min(x, sg.right() - DRAWER_W - 4))
            y = min(y, sg.bottom() - DRAWER_H - 4)

        target = QRect(x, y, DRAWER_W, DRAWER_H)

        if animate:
            start = QRect(x, y, DRAWER_W, 0)
            self.setGeometry(start)
            self.show()
            self._anim.setStartValue(start)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.setGeometry(target)
            self.show()

        configure_overlay_panel(
            self, level=1000, can_become_key=True,
            screen_share_invisible=True,
            window_title_hint="ClueChat"
        )

    def close_drawer(self, animate: bool = True):
        if not self.isVisible():
            return
        if animate:
            cur = self.geometry()
            end = QRect(cur.x(), cur.y(), DRAWER_W, 0)
            self._anim.setStartValue(cur)
            self._anim.setEndValue(end)
            self._anim.finished.connect(self._on_close_anim_done)
            self._anim.start()
        else:
            self.hide()

    def _on_close_anim_done(self):
        self.hide()
        try:
            self._anim.finished.disconnect(self._on_close_anim_done)
        except Exception:
            pass

    # ── PUBLIC STATE UPDATES (called by orchestrator) ─────────────────────────
    def update_listen_button(self, active: bool, msg: str = ""):
        if active:
            self.listen_btn.setText("🔴 Listening Live")
            self.listen_btn.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #059669,stop:1 #047857);
                    border:1px solid rgba(110,231,183,0.4); border-radius:8px;
                    color:#FFFFFF; font-size:12px; font-weight:700; padding:5px 12px;
                }
            """)
            self.waveform.set_active(True)
        else:
            self.listen_btn.setText("🎙️ Start Listening")
            self.listen_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
            self.waveform.set_active(False)
        if msg:
            self.status_lbl.setText(msg)

    def update_device_button(self, label: str):
        self.device_btn.setText(label)

    # ── CONTROLS ──────────────────────────────────────────────────────────────
    def _cycle_mode(self):
        modes = list(InterviewMode)
        idx = modes.index(self.current_mode) if self.current_mode in modes else 0
        self.current_mode = modes[(idx + 1) % len(modes)]
        self.mode_btn.setText(MODE_DISPLAY_NAMES[self.current_mode])

    def _cycle_code_policy(self):
        if self.code_policy == "auto":
            self.code_policy = "always"
            self.code_btn.setText("💻 Code: Always")
        elif self.code_policy == "always":
            self.code_policy = "off"
            self.code_btn.setText("💻 Code: Off")
        else:
            self.code_policy = "auto"
            self.code_btn.setText("💻 Code: On Ask")

    def _cycle_opacity(self):
        modes = ["ghost", "balanced", "focus"]
        idx = modes.index(self.current_opacity_name) if self.current_opacity_name in modes else 1
        self.current_opacity_name = modes[(idx + 1) % len(modes)]
        self.current_opacity = Config.OPACITY_LEVELS[self.current_opacity_name]
        self.card.setStyleSheet(get_hud_stylesheet(self.current_opacity))
        self.opacity_btn.setText(
            f"◐ {self.current_opacity_name.title()} ({int(self.current_opacity*100)}%)"
        )

    def _cycle_device(self):
        from clue.core.audio_engine import list_input_devices
        self._input_devices = list_input_devices()
        if not self._input_devices:
            return
        self._device_idx = (self._device_idx + 1) % len(self._input_devices)
        dev = self._input_devices[self._device_idx]
        self.audio_rules.set_mic_device(dev["index"])
        prefix = "🎧" if dev.get("is_earphone") else "🎙️"
        name = dev["name"].split("(")[0].strip()[:16]
        self.device_btn.setText(f"{prefix} {name}")
        self.status_lbl.setText(f"Input: {dev['name']}")

    # ── AUDIO SIGNALS ─────────────────────────────────────────────────────────
    def _on_audio_energy(self, rms: float):
        self.waveform.set_energy(rms)

    def _on_speech_started(self, speaker: str):
        if not self.audio_rules._is_generating_answer:
            who = "Interviewer" if speaker == "them" else "You"
            self.status_lbl.setText(f"● {who} speaking...")

    def _on_utterance_transcribed(self, role: str, text: str, ts: str):
        who = "Interviewer" if role == Role.THEM.value else "You"
        preview = text if len(text) <= 55 else text[:52] + "..."
        self.transcript_lbl.setText(f"🎙️ [{ts}] {who}: \"{preview}\"")
        if not self.audio_rules._is_generating_answer:
            self.q_title.setText(f"🎙️ {who}: {text}")

    def _on_status_changed(self, msg: str):
        self.status_lbl.setText(msg)

    # ── QUESTION → ANSWER PIPELINE ────────────────────────────────────────────
    def _on_submit(self):
        query = self.input_field.text().strip()
        self.input_field.clear()
        self.audio_rules.trigger_instant_ask(manual_query=query)

    def _instant_solve(self):
        self.audio_rules.trigger_instant_ask()

    def _on_question_triggered(self, question: str, transcript: str):
        self.bg_banner.hide()
        self.q_title.setText(f"Q: {question}")
        self.answer_browser.setHtml(
            "<div style='color:#94A3B8;font-style:italic;padding:10px;'>"
            "✦ Asking Antigravity...</div>"
        )
        self.audio_rules.set_generating_state(True)
        self.status_lbl.setText("✦ Generating... (audio still listening)")

        if self._stream_worker and self._stream_worker.isRunning():
            self._stream_worker.cancel()

        # Screen context only if explicitly asked
        screen_bytes = None
        q_low = question.lower()
        if any(w in q_low for w in ["screen", "on screen", "this image", "snippet", "look at"]):
            screen_bytes = capture_screen_bytes()

        force_code = True if self.code_policy == "always" else (
            False if self.code_policy == "off" else None
        )

        self._current_answer_raw = ""
        self._stream_worker = LLMStreamWorker(
            query=question,
            transcript_text=transcript,
            mode=self.current_mode,
            language=Config.PREFERRED_LANGUAGE,
            screenshot_bytes=screen_bytes,
            force_code=force_code,
        )
        self._stream_worker.token_received.connect(self._on_token)
        self._stream_worker.stream_completed.connect(
            lambda ans: self._on_completed(question, ans)
        )
        self._stream_worker.stream_error.connect(self._on_stream_error)
        self._stream_worker.start()

    def _on_stream_error(self, err: str):
        self.status_lbl.setText(f"⚠️ {err}")
        self.audio_rules.set_generating_state(False)
        self.answer_completed.emit("", "")

    def _on_token(self, token: str):
        self._current_answer_raw += token
        html = render_markdown_to_rich_html(self._current_answer_raw, Config.PREFERRED_LANGUAGE)
        self.answer_browser.setHtml(html)
        # Auto-scroll to bottom while streaming
        sb = self.answer_browser.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_completed(self, question: str, full_answer: str):
        self._current_answer_raw = full_answer
        self.answer_browser.setHtml(
            render_markdown_to_rich_html(full_answer, Config.PREFERRED_LANGUAGE)
        )
        self._qa_history.append({
            "question": question,
            "answer": full_answer,
            "time": time.strftime("%H:%M:%S"),
        })
        self.audio_rules.set_generating_state(False)
        self.status_lbl.setText("● Live listening (audio never stopped)")
        self.answer_completed.emit(question, full_answer)

    def _on_bg_speech_detected(self, speaker: str, text: str):
        self.bg_lbl.setText(f"🎙️ {speaker}: \"{text[:60]}...\"")
        self._pending_bg_question = text
        self.bg_banner.show()

    def _solve_bg_question(self):
        if self._pending_bg_question:
            self.bg_banner.hide()
            self.audio_rules.trigger_instant_ask(manual_query=self._pending_bg_question)

    # ── SCREEN SNIP ───────────────────────────────────────────────────────────
    def start_snip(self):
        self._snipper_worker = ScreenSnipperWorker()
        self._snipper_worker.snippet_captured.connect(self._on_snippet)
        self._snipper_worker.start()

    def _on_snippet(self, path: str):
        try:
            with open(path, "rb") as f:
                data = f.read()
            self.q_title.setText("🖼 Solving Screen Snippet...")
            self.answer_browser.setHtml(
                "<div style='color:#94A3B8;font-style:italic;padding:10px;'>"
                "Analyzing snippet with Antigravity...</div>"
            )
            if self._stream_worker and self._stream_worker.isRunning():
                self._stream_worker.cancel()
            self._current_answer_raw = ""
            self._stream_worker = LLMStreamWorker(
                query="Solve the problem shown in this screen snippet. Spoken explanation only; code if asked.",
                transcript_text=self.audio_rules.transcript_store.get_formatted_transcript(),
                mode=self.current_mode,
                language=Config.PREFERRED_LANGUAGE,
                screenshot_bytes=data,
            )
            self._stream_worker.token_received.connect(self._on_token)
            self._stream_worker.stream_completed.connect(
                lambda ans: self._on_completed("Screen Snippet", ans)
            )
            self._stream_worker.start()
        except Exception as ex:
            self.status_lbl.setText(f"Snippet error: {ex}")

    # ── HISTORY ───────────────────────────────────────────────────────────────
    def _toggle_history(self):
        self._history_visible = not self._history_visible
        if self._history_visible:
            if not self._qa_history:
                self.answer_browser.setHtml(
                    "<div style='color:#94A3B8;padding:12px;'>No history yet.</div>"
                )
                return
            parts = ["<h3 style='color:#38BDF8;'>📜 Session Q&A History</h3>"]
            for item in reversed(self._qa_history):
                parts.append(f"""
                <div style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);
                            border-radius:8px;padding:10px;margin-bottom:10px;">
                  <div style="color:#FBBF24;font-weight:700;margin-bottom:4px;">
                    [{item['time']}] {item['question']}
                  </div>
                  <div style="color:#E2E8F0;font-size:12.5px;">
                    {render_markdown_to_rich_html(item['answer'], Config.PREFERRED_LANGUAGE)}
                  </div>
                </div>""")
            self.answer_browser.setHtml("".join(parts))
        else:
            if self._current_answer_raw:
                self.answer_browser.setHtml(
                    render_markdown_to_rich_html(self._current_answer_raw, Config.PREFERRED_LANGUAGE)
                )

    # ── CLIPBOARD ─────────────────────────────────────────────────────────────
    def _copy_answer(self):
        if self._current_answer_raw:
            QApplication.clipboard().setText(self._current_answer_raw)
            self.copy_btn.setText("✓ Copied!")
            QTimer.singleShot(1800, lambda: self.copy_btn.setText("📋 Copy"))
