"""
Clue UI — Next-Gen Translucent Stealth Floating HUD Window
Features:
- Screen-Share Invisibility (NSWindowSharingNone)
- Sticky Multi-Space Overlay (Follows across all virtual desktops/Spaces)
- 100% Complete Answer Visibility with Zero Cutoffs
- Translucent Frosted Glass with Background Visibility
- ChatGPT-Style Vibrant Syntax Highlighting
- Code Generated ONLY When Explicitly Asked
- Zero Fluff & Clear Direct Spoken Talking Points
- Ultra-Fast Antigravity Streaming Engine
- Continuous Audio Capture (Never Stops During Answering)
"""

import sys
import threading
import time
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QPoint, QRect, QRectF, QTimer, QEasingCurve, QPropertyAnimation, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QCursor,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from clue.config import Config
from clue.core.ai_engine import LLMStreamWorker
from clue.core.antigravity_engine import get_warm_antigravity
from clue.core.audio_engine import Role
from clue.core.audio_rules import AudioSessionState, ContinuousAudioRulesEngine
from clue.core.interview_modes import InterviewMode, MODE_DISPLAY_NAMES
from clue.core.screen_service import ScreenSnipperWorker, capture_screen_bytes
from clue.ui.overlay_panel import (
    clamp_to_visible_screen,
    configure_overlay_panel,
    reassert_overlay,
)
from clue.ui.styles import (
    BUTTON_COLLAPSED_STYLESHEET,
    BUTTON_EXPANDED_STYLESHEET,
    BUTTON_PRIMARY_STYLESHEET,
    BUTTON_SECONDARY_STYLESHEET,
    INPUT_STYLESHEET,
    PALETTE,
    get_hud_stylesheet,
)
from clue.ui.syntax_styler import render_markdown_to_rich_html
from clue.ui.waveform import AudioWaveformWidget


class ClueHUDWindow(QWidget):
    """
    Persistent, translucent, screen-share invisible floating HUD for Clue.
    Follows user across all macOS virtual desktops (Spaces).
    """

    COLLAPSED_WIDTH = 640
    COLLAPSED_HEIGHT = 170
    EXPANDED_HEIGHT = 620
    MAX_HEIGHT = 1100

    def __init__(self, parent=None):
        super().__init__(parent)

        self.current_opacity_name = Config.DEFAULT_OPACITY_MODE
        self.current_opacity = Config.get_opacity(self.current_opacity_name)
        self.current_mode = InterviewMode.CODING_INTERVIEW

        # Code Generation Policy: "auto" (only if asked), "always", "off"
        self.code_policy = "auto"

        self._is_expanded = False
        self._history_visible = False
        self._is_dragging = False
        self._drag_start_pos = QPoint()
        self._drag_start_window_pos = QPoint()

        # Session Q&A history
        self._qa_history: List[Dict[str, str]] = []
        self._current_answer_raw = ""
        self._stream_worker: Optional[LLMStreamWorker] = None

        # ── Pre-heat warm Antigravity Agent in background ─────────────────────
        threading.Thread(target=get_warm_antigravity, daemon=True).start()

        # ── Audio Rules Engine ────────────────────────────────────────────────
        self.audio_rules = ContinuousAudioRulesEngine(auto_answer_questions=True)
        self.audio_rules.audio_energy_updated.connect(self._on_audio_energy)
        self.audio_rules.speech_started.connect(self._on_speech_started)
        self.audio_rules.utterance_transcribed.connect(self._on_utterance_transcribed)
        self.audio_rules.status_changed.connect(self._on_status_changed)
        self.audio_rules.question_ready_for_answer.connect(self._on_question_triggered)
        self.audio_rules.speech_detected_during_answer.connect(self._on_background_speech_detected)

        # ── Screen Snipper ────────────────────────────────────────────────────
        self._snipper_worker: Optional[ScreenSnipperWorker] = None

        # ── Window Attributes ─────────────────────────────────────────────────
        self.setWindowTitle(Config.HUD_WINDOW_TITLE)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.resize(self.COLLAPSED_WIDTH, self.COLLAPSED_HEIGHT)

        self._build_ui()
        self._setup_shortcuts()
        self._position_top_center()

        # ── Smooth Geometry Animation for Responsive Expand / Collapse ───────
        self._anim = QPropertyAnimation(self, b"geometry")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_animation_finished)

        # ── Periodic Stickiness Reassert Timer (Multi-Space stickiness) ────────
        self._reassert_timer = QTimer(self)
        self._reassert_timer.timeout.connect(self._reassert_stickiness)
        self._reassert_timer.start(1200)

    def showEvent(self, event):
        super().showEvent(event)
        # Configure macOS NSPanel: level=1000, 0x151 multi-space, screen-share invisible
        configure_overlay_panel(
            self,
            level=Config.HUD_WINDOW_LEVEL,
            can_become_key=True,
            screen_share_invisible=True,
            window_title_hint=Config.HUD_WINDOW_TITLE,
        )
        clamp_to_visible_screen(self)

    def _reassert_stickiness(self):
        """Reassert multi-space stickiness so window follows across virtual desktops."""
        if self.isVisible():
            reassert_overlay(self)

    # ── UI CONSTRUCTION ───────────────────────────────────────────────────────
    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(8, 6, 8, 8)
        root_layout.setSpacing(0)

        # Main Frosted Glass Card
        self.card = QFrame(self)
        self.card.setObjectName("card")
        self.card.setStyleSheet(get_hud_stylesheet(self.current_opacity))

        # Soft floating drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 10)
        self.card.setGraphicsEffect(shadow)

        self.card_layout = QVBoxLayout(self.card)
        self.card_layout.setContentsMargins(14, 10, 14, 10)
        self.card_layout.setSpacing(8)

        # ── ROW 1: HEADER STRIP (Logo, Mode, Code Policy, Opacity, Badge) ─────
        header_row = QHBoxLayout()
        header_row.setContentsMargins(2, 0, 2, 0)
        header_row.setSpacing(8)

        # Logo Icon
        self.logo_label = QLabel("✦ CLUE", self.card)
        self.logo_label.setStyleSheet("color: #FFFFFF; font-size: 13px; font-weight: 800; letter-spacing: 0.8px;")
        header_row.addWidget(self.logo_label)

        # Mode Selector Button
        self.mode_btn = QPushButton(MODE_DISPLAY_NAMES[self.current_mode], self.card)
        self.mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mode_btn.setToolTip("Click to cycle interview mode")
        self.mode_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.mode_btn.clicked.connect(self._cycle_interview_mode)
        header_row.addWidget(self.mode_btn)

        # Code Policy Button: "💻 Code: When Asked" / "💻 Code: Always" / "💻 Code: Off"
        self.code_btn = QPushButton("💻 Code: When Asked", self.card)
        self.code_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.code_btn.setToolTip("Toggle code rule: only provide code when explicitly asked (simple, clean, short variable names)")
        self.code_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.code_btn.clicked.connect(self._cycle_code_policy)
        header_row.addWidget(self.code_btn)

        # Opacity Presets Button (Ghost 40%, Balanced 65%, Focus 85%)
        self.opacity_btn = QPushButton(f"◐ {self.current_opacity_name.title()} ({int(self.current_opacity*100)}%)", self.card)
        self.opacity_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.opacity_btn.setToolTip("Toggle Translucency (Ghost 40% / Balanced 65% / Focus 85%)")
        self.opacity_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.opacity_btn.clicked.connect(self._cycle_opacity)
        header_row.addWidget(self.opacity_btn)

        # Audio Input Device Selector (Earphones / Built-in Mic)
        self.input_devices = self.audio_rules.list_devices()
        self.current_device_idx = 0
        has_earphones = any(d.get("is_earphone") for d in self.input_devices)
        initial_label = "🎧 Earphones" if has_earphones else "🎙️ Mic"
        self.device_btn = QPushButton(initial_label, self.card)
        self.device_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.device_btn.setToolTip("Click to toggle audio input device (Earphones / Mic)")
        self.device_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.device_btn.clicked.connect(self._cycle_input_device)
        header_row.addWidget(self.device_btn)

        header_row.addStretch()

        # Stealth Screen-Share Invisible Badge
        self.stealth_badge = QLabel("🛡️ Invisibility Active", self.card)
        self.stealth_badge.setStyleSheet("""
            color: #10B981;
            font-size: 11px;
            font-weight: 600;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.25);
            border-radius: 6px;
            padding: 3px 7px;
        """)
        header_row.addWidget(self.stealth_badge)

        # Close / Hide Button
        self.close_btn = QPushButton("✕", self.card)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.close_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.06);
                color: rgba(255,255,255,0.6);
                border: none;
                border-radius: 12px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.15);
                color: #FFFFFF;
            }
        """)
        self.close_btn.clicked.connect(self.close)
        header_row.addWidget(self.close_btn)

        self.card_layout.addLayout(header_row)

        # ── ROW 2: INPUT BAR & RETURN BUTTON ─────────────────────────────────
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)

        self.input_field = QLineEdit(self.card)
        self.input_field.setPlaceholderText("Ask question... (e.g., 'Explain QuickSort' or 'Write code for 3Sum')")
        self.input_field.setStyleSheet(INPUT_STYLESHEET)
        self.input_field.returnPressed.connect(self._on_manual_submit)
        input_row.addWidget(self.input_field, 1)

        self.ask_btn = QPushButton("↵ Ask", self.card)
        self.ask_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.ask_btn.setStyleSheet(BUTTON_PRIMARY_STYLESHEET)
        self.ask_btn.clicked.connect(self._on_manual_submit)
        input_row.addWidget(self.ask_btn)

        self.card_layout.addLayout(input_row)

        # ── ROW 3: TOOLBAR (Continuous Listen Button, Waveform, Snip, Drawer) ─
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)

        # 🎙️ CONTINUOUS LISTEN TOGGLE BUTTON (Requirement 7)
        self.listen_btn = QPushButton("🎙️ Start Listening", self.card)
        self.listen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.listen_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.listen_btn.clicked.connect(self._toggle_listening)
        toolbar.addWidget(self.listen_btn)

        # Live Animated Audio Waveform
        self.waveform = AudioWaveformWidget(self.card)
        toolbar.addWidget(self.waveform)

        # Status Label
        self.status_label = QLabel("Click 'Start Listening' to capture audio", self.card)
        self.status_label.setStyleSheet("color: rgba(255,255,255,0.55); font-size: 11.5px; font-weight: 500;")
        toolbar.addWidget(self.status_label)

        toolbar.addStretch()

        # Screen Snip Action (🖼)
        self.snip_btn = QPushButton("🖼 Snip Screen", self.card)
        self.snip_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.snip_btn.setToolTip("Interactive marquee snip (⌥O)")
        self.snip_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.snip_btn.clicked.connect(self._start_screen_snip)
        toolbar.addWidget(self.snip_btn)

        # Copy Entire Answer (📋)
        self.copy_btn = QPushButton("📋 Copy", self.card)
        self.copy_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.copy_btn.setToolTip("Copy entire response to clipboard")
        self.copy_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.copy_btn.clicked.connect(self._copy_answer_to_clipboard)
        toolbar.addWidget(self.copy_btn)

        # Session History Button
        self.history_btn = QPushButton("📜 History", self.card)
        self.history_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.history_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
        self.history_btn.clicked.connect(self._toggle_history)
        toolbar.addWidget(self.history_btn)

        # Expand / Collapse Drawer Chevron (▼ / ▲)
        self.expand_btn = QPushButton("▼ Expand", self.card)
        self.expand_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.expand_btn.setToolTip("Toggle Question & Answer Drawer (⌥E / Ctrl+E)")
        self.expand_btn.setStyleSheet(BUTTON_COLLAPSED_STYLESHEET)
        self.expand_btn.clicked.connect(self._toggle_expand)
        toolbar.addWidget(self.expand_btn)

        self.card_layout.addLayout(toolbar)

        # ── BACKGROUND SPEECH ALERT PILL ─────────────────────────────────────
        self.bg_alert_frame = QFrame(self.card)
        self.bg_alert_frame.setObjectName("inner_box")
        self.bg_alert_frame.hide()
        bg_alert_layout = QHBoxLayout(self.bg_alert_frame)
        bg_alert_layout.setContentsMargins(10, 6, 10, 6)
        bg_alert_layout.setSpacing(8)

        self.bg_alert_label = QLabel("", self.bg_alert_frame)
        self.bg_alert_label.setStyleSheet("color: #38BDF8; font-size: 12px; font-weight: 600;")
        bg_alert_layout.addWidget(self.bg_alert_label, 1)

        self.bg_solve_btn = QPushButton("⚡ Answer Follow-up", self.bg_alert_frame)
        self.bg_solve_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.bg_solve_btn.setStyleSheet(BUTTON_PRIMARY_STYLESHEET)
        self.bg_solve_btn.clicked.connect(self._solve_background_question)
        bg_alert_layout.addWidget(self.bg_solve_btn)

        self.card_layout.addWidget(self.bg_alert_frame)

        # ── EXPANDED DRAWER: ANSWER & CODE DISPLAY ────────────────────────────
        self.drawer_frame = QFrame(self.card)
        self.drawer_frame.hide()
        drawer_layout = QVBoxLayout(self.drawer_frame)
        drawer_layout.setContentsMargins(0, 6, 0, 0)
        drawer_layout.setSpacing(6)

        # Active Question Title Banner
        self.question_title_label = QLabel("Awaiting prompt or live audio...", self.drawer_frame)
        self.question_title_label.setWordWrap(True)
        self.question_title_label.setStyleSheet("""
            color: #FFFFFF;
            font-size: 13px;
            font-weight: 600;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 8px;
            padding: 6px 10px;
        """)
        drawer_layout.addWidget(self.question_title_label)

        # Rich Answer Display: Monospace code with ChatGPT-style vibrant colors + smooth scroll
        self.answer_browser = QTextBrowser(self.drawer_frame)
        self.answer_browser.setOpenExternalLinks(False)
        self.answer_browser.setReadOnly(True)
        self.answer_browser.setMinimumHeight(420)
        self.answer_browser.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.answer_browser.setStyleSheet("""
            QTextBrowser {
                background-color: transparent;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 12px;
                padding: 10px 12px;
            }
        """)
        drawer_layout.addWidget(self.answer_browser, 1)

        self.card_layout.addWidget(self.drawer_frame)
        root_layout.addWidget(self.card)

    # ── SHORTCUTS & NAVIGATION ───────────────────────────────────────────────
    def _setup_shortcuts(self):
        # ⌥C to toggle HUD visibility
        QShortcut(QKeySequence("Alt+C"), self, self._toggle_visibility)
        # ⌥E or Ctrl+E to toggle expand/collapse drawer
        QShortcut(QKeySequence("Alt+E"), self, self._toggle_expand)
        QShortcut(QKeySequence("Ctrl+E"), self, self._toggle_expand)
        # ⌥A to instant listen & answer
        QShortcut(QKeySequence("Alt+A"), self, self._on_manual_submit)
        # ⌥O to snip screen
        QShortcut(QKeySequence("Alt+O"), self, self._start_screen_snip)
        # ⌥[ and ⌥] to cycle opacity
        QShortcut(QKeySequence("Alt+["), self, self._cycle_opacity)
        QShortcut(QKeySequence("Alt+]"), self, self._cycle_opacity)

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            reassert_overlay(self)

    # ── TRANSLUCENCY CONTROLS ─────────────────────────────────────────────────
    def _cycle_opacity(self):
        """Cycle between Ghost (40%), Balanced (65%), and Focus (85%)."""
        modes = ["ghost", "balanced", "focus"]
        curr_idx = modes.index(self.current_opacity_name) if self.current_opacity_name in modes else 1
        next_mode = modes[(curr_idx + 1) % len(modes)]
        self.current_opacity_name = next_mode
        self.current_opacity = Config.OPACITY_LEVELS[next_mode]

        self.card.setStyleSheet(get_hud_stylesheet(self.current_opacity))
        self.opacity_btn.setText(f"◐ {next_mode.title()} ({int(self.current_opacity*100)}%)")

    # ── CODE POLICY TOGGLE (Improvement 1) ────────────────────────────────────
    def _cycle_code_policy(self):
        """Cycles between: When Asked (default) -> Always -> Off."""
        if self.code_policy == "auto":
            self.code_policy = "always"
            self.code_btn.setText("💻 Code: Always")
        elif self.code_policy == "always":
            self.code_policy = "off"
            self.code_btn.setText("💻 Code: Off")
        else:
            self.code_policy = "auto"
            self.code_btn.setText("💻 Code: When Asked")

    # ── INTERVIEW MODE CONTROLS ───────────────────────────────────────────────
    def _cycle_interview_mode(self):
        modes = list(InterviewMode)
        curr_idx = modes.index(self.current_mode) if self.current_mode in modes else 0
        self.current_mode = modes[(curr_idx + 1) % len(modes)]
        self.mode_btn.setText(MODE_DISPLAY_NAMES[self.current_mode])

    # ── AUDIO INPUT DEVICE CYCLING (EARPHONES / MIC) ─────────────────────────
    def _cycle_input_device(self):
        self.input_devices = self.audio_rules.list_devices()
        if not self.input_devices:
            return
        self.current_device_idx = (self.current_device_idx + 1) % len(self.input_devices)
        chosen = self.input_devices[self.current_device_idx]
        self.audio_rules.set_mic_device(chosen["index"])
        prefix = "🎧" if chosen["is_earphone"] else "🎙️"
        short_name = chosen["name"].split("(")[0].strip()
        if len(short_name) > 16:
            short_name = short_name[:14] + ".."
        self.device_btn.setText(f"{prefix} {short_name}")
        self.status_label.setText(f"Active input: {chosen['name']}")

    # ── AUDIO LISTENING CONTROLS ──────────────────────────────────────────────
    def _toggle_listening(self):
        """Toggle continuous audio capture."""
        try:
            if self.audio_rules.state == AudioSessionState.IDLE:
                ok, msg = self.audio_rules.start_listening()
                if ok:
                    self.listen_btn.setText("🔴 Listening Live")
                    self.listen_btn.setStyleSheet("""
                        QPushButton {
                            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #10b981, stop:1 #059669);
                            border: 1px solid rgba(110, 231, 183, 0.4);
                            border-radius: 8px;
                            color: #FFFFFF;
                            font-size: 12px;
                            font-weight: 700;
                            padding: 5px 12px;
                        }
                    """)
                    self.status_label.setText(f"● {msg}")
                    self.waveform.set_active(True)
                else:
                    self.status_label.setText(f"⚠️ {msg}")
                    self.waveform.set_active(False)
            else:
                self.audio_rules.stop_listening()
                self.listen_btn.setText("🎙️ Start Listening")
                self.listen_btn.setStyleSheet(BUTTON_SECONDARY_STYLESHEET)
                self.status_label.setText("Audio capture paused.")
                self.waveform.set_active(False)
        except Exception as e:
            self.status_label.setText(f"Audio error: {e}")

    def _on_audio_energy(self, rms_energy: float):
        self.waveform.set_energy(rms_energy)

    def _on_speech_started(self, speaker: str):
        label = "Interviewer" if speaker == "them" else "You"
        if not self.audio_rules._is_generating_answer:
            self.status_label.setText(f"● {label} speaking...")

    def _on_utterance_transcribed(self, role: str, text: str, timestamp: str):
        speaker = "Interviewer" if role == Role.THEM.value else "You"
        short_preview = text if len(text) <= 45 else text[:42] + "..."
        self.status_label.setText(f"🎙️ [{timestamp}] Heard {speaker}: \"{short_preview}\"")
        if not self.audio_rules._is_generating_answer:
            self.question_title_label.setText(f"🎙️ {speaker}: {text}")

    def _on_status_changed(self, msg: str):
        self.status_label.setText(msg)

    # ── EXPAND / COLLAPSE DRAWER ──────────────────────────────────────────────
    def _toggle_expand(self, animated: bool = True):
        self._is_expanded = not self._is_expanded

        # Stop any in-flight animation cleanly to allow rapid clicking
        if hasattr(self, "_anim") and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()

        if not animated or not self.isVisible():
            if self._is_expanded:
                self.drawer_frame.show()
                self.card_layout.activate()
                self.resize(self.COLLAPSED_WIDTH, self.EXPANDED_HEIGHT)
                self.expand_btn.setText("▲ Collapse")
                self.expand_btn.setStyleSheet(BUTTON_EXPANDED_STYLESHEET)
            else:
                self.drawer_frame.hide()
                self.card_layout.activate()
                self.adjustSize()
                self.resize(self.COLLAPSED_WIDTH, self.COLLAPSED_HEIGHT)
                self.expand_btn.setText("▼ Expand")
                self.expand_btn.setStyleSheet(BUTTON_COLLAPSED_STYLESHEET)
            return

        # Smooth, responsive animated transition
        if self._is_expanded:
            self.drawer_frame.show()
            self.card_layout.activate()
            target_geo = QRect(self.x(), self.y(), self.width(), self.EXPANDED_HEIGHT)
            self.expand_btn.setText("▲ Collapse")
            self.expand_btn.setStyleSheet(BUTTON_EXPANDED_STYLESHEET)
        else:
            target_geo = QRect(self.x(), self.y(), self.width(), self.COLLAPSED_HEIGHT)
            self.expand_btn.setText("▼ Expand")
            self.expand_btn.setStyleSheet(BUTTON_COLLAPSED_STYLESHEET)

        self._anim.setStartValue(self.geometry())
        self._anim.setEndValue(target_geo)
        self._anim.start()

    def _on_animation_finished(self):
        if not self._is_expanded:
            self.drawer_frame.hide()
            self.card_layout.activate()
            self.adjustSize()
            self.resize(self.width(), self.COLLAPSED_HEIGHT)
        else:
            self.card_layout.activate()

    def _ensure_expanded(self):
        if not self._is_expanded:
            self._toggle_expand(animated=True)

    # ── AI ANSWER GENERATION & SIMULTANEOUS INGESTION ─────────────────────────
    def _on_manual_submit(self):
        query = self.input_field.text().strip()
        self.input_field.clear()
        self.audio_rules.trigger_instant_ask(manual_query=query)

    def _on_question_triggered(self, question_text: str, full_transcript: str):
        """Dispatches fast answer generation while audio continues listening."""
        self._ensure_expanded()
        self.bg_alert_frame.hide()
        self.question_title_label.setText(f"Q: {question_text}")
        self.answer_browser.setHtml("<div style='color: #94A3B8; font-style: italic; padding: 8px;'>✦ Asking Antigravity...</div>")

        self.audio_rules.set_generating_state(True)
        self.status_label.setText("✦ Generating answer (Audio still listening...)")

        if self._stream_worker and self._stream_worker.isRunning():
            self._stream_worker.cancel()

        # Capture full screenshot ONLY if user specifically requests screen context
        screen_bytes = None
        q_lower = question_text.lower()
        if any(w in q_lower for w in ["screen", "on screen", "this image", "snippet", "look at my screen"]):
            screen_bytes = capture_screen_bytes()

        # Determine code policy
        force_code = None
        if self.code_policy == "always":
            force_code = True
        elif self.code_policy == "off":
            force_code = False

        self._current_answer_raw = ""
        self._stream_worker = LLMStreamWorker(
            query=question_text,
            transcript_text=full_transcript,
            mode=self.current_mode,
            language=Config.PREFERRED_LANGUAGE,
            screenshot_bytes=screen_bytes,
            force_code=force_code,
        )
        self._stream_worker.token_received.connect(self._on_token_received)
        self._stream_worker.stream_completed.connect(lambda ans: self._on_stream_completed(question_text, ans))
        self._stream_worker.start()

    def _on_token_received(self, token: str):
        self._current_answer_raw += token
        html_content = render_markdown_to_rich_html(self._current_answer_raw, Config.PREFERRED_LANGUAGE)
        self.answer_browser.setHtml(html_content)

    def _on_stream_completed(self, question: str, full_answer: str):
        self._current_answer_raw = full_answer
        html_content = render_markdown_to_rich_html(full_answer, Config.PREFERRED_LANGUAGE)
        self.answer_browser.setHtml(html_content)

        # Record in session history
        self._qa_history.append({
            "question": question,
            "answer": full_answer,
            "time": time.strftime("%H:%M:%S")
        })

        self.audio_rules.set_generating_state(False)
        self.status_label.setText("● Live: Mic & Interviewer Loopback Active")

    def _on_background_speech_detected(self, speaker: str, text: str):
        """Notifies user of speech while reading previous answer."""
        self.bg_alert_label.setText(f"🎙️ {speaker} just said: \"{text[:65]}...\"")
        self._pending_bg_question = text
        self.bg_alert_frame.show()

    def _solve_background_question(self):
        if hasattr(self, "_pending_bg_question") and self._pending_bg_question:
            self.bg_alert_frame.hide()
            self.audio_rules.trigger_instant_ask(manual_query=self._pending_bg_question)

    # ── SCREEN SNIPPET TOOL ───────────────────────────────────────────────────
    def _start_screen_snip(self):
        self._snipper_worker = ScreenSnipperWorker()
        self._snipper_worker.snippet_captured.connect(self._on_snippet_captured)
        self._snipper_worker.start()

    def _on_snippet_captured(self, file_path: str):
        try:
            with open(file_path, "rb") as f:
                snippet_bytes = f.read()
            self._ensure_expanded()
            self.question_title_label.setText("🖼 Solving Screen Snippet Question...")
            self.answer_browser.setHtml("<div style='color: #94A3B8; font-style: italic; padding: 8px;'>Analyzing screen snippet with Antigravity...</div>")

            if self._stream_worker and self._stream_worker.isRunning():
                self._stream_worker.cancel()

            self._current_answer_raw = ""
            self._stream_worker = LLMStreamWorker(
                query="Solve the problem shown in this screen snippet. Provide spoken explanation, code only if requested, and complexity.",
                transcript_text=self.audio_rules.transcript_store.get_formatted_transcript(),
                mode=self.current_mode,
                language=Config.PREFERRED_LANGUAGE,
                screenshot_bytes=snippet_bytes,
            )
            self._stream_worker.token_received.connect(self._on_token_received)
            self._stream_worker.stream_completed.connect(lambda ans: self._on_stream_completed("Screen Snippet", ans))
            self._stream_worker.start()
        except Exception as e:
            self.status_label.setText(f"Error loading snippet: {e}")

    # ── HISTORY VIEWER ────────────────────────────────────────────────────────
    def _toggle_history(self):
        self._history_visible = not self._history_visible
        if self._history_visible:
            self._ensure_expanded()
            if not self._qa_history:
                self.answer_browser.setHtml("<div style='color: #94A3B8; padding: 12px;'>No previous questions recorded in this session.</div>")
                return
            history_html = ["<h3 style='color: #38BDF8;'>📜 Session Q&A History</h3>"]
            for i, item in enumerate(reversed(self._qa_history), 1):
                history_html.append(f"""
                <div style="background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 10px; margin-bottom: 12px;">
                    <div style="color: #FBBF24; font-weight: 700; margin-bottom: 4px;">[{item['time']}] Q: {item['question']}</div>
                    <div style="color: #E2E8F0; font-size: 13px;">{render_markdown_to_rich_html(item['answer'], Config.PREFERRED_LANGUAGE)}</div>
                </div>
                """)
            self.answer_browser.setHtml("".join(history_html))
        else:
            if self._current_answer_raw:
                self.answer_browser.setHtml(render_markdown_to_rich_html(self._current_answer_raw, Config.PREFERRED_LANGUAGE))

    def _copy_answer_to_clipboard(self):
        if self._current_answer_raw:
            clipboard = QApplication.clipboard()
            clipboard.setText(self._current_answer_raw)
            self.copy_btn.setText("✓ Copied!")
            QTimer.singleShot(1800, lambda: self.copy_btn.setText("📋 Copy"))

    # ── DRAG & POSITIONING ────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._drag_start_pos = event.globalPosition().toPoint()
            self._drag_start_window_pos = self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            self.move(self._drag_start_window_pos + delta)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._is_dragging = False
        reassert_overlay(self)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self._position_top_center()
        reassert_overlay(self)
        event.accept()

    def _position_top_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = geo.left() + (geo.width() - self.width()) // 2
            y = geo.top() + 20
            self.move(x, y)
