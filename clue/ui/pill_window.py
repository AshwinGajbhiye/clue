"""
Clue UI — Control Pill Window (Cluely-exact clone)
==================================================
A minimal 163×44 frameless floating pill that mirrors Cluely's Control Pill (T):
  - Screen-saver window level (kCGScreenSaverWindowLevel = 1000)
  - NSWindowSharingNone (screen-share invisible)
  - Multi-Space sticky (0x151 / kCGSTagSticky)
  - Hidden from Mission Control & taskbar
  - Cmd+Return → instant solve
  - Shows live mic waveform + listening state
  - Double-click to snap back to top-center
  - On click expands the chat drawer (w)
"""

import sys
import threading
from typing import Optional, Callable

from PyQt6.QtCore import (
    Qt, QPoint, QRect, QTimer, QPropertyAnimation, QEasingCurve, pyqtSignal
)
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QCursor, QKeySequence, QShortcut
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QPushButton, QWidget
)

from clue.ui.waveform import AudioWaveformWidget
from clue.ui.overlay_panel import configure_overlay_panel, reassert_overlay, clamp_to_visible_screen


# ── Pill exact dimensions (matching Cluely) ─────────────────────────────────
PILL_W = 230     # fits logo, status, live waveform, mic toggle, and dot
PILL_H = 44
PILL_RADIUS = 22


class ControlPill(QWidget):
    """
    Minimal floating control pill — always on screen, follows all Spaces.
    Clicking it toggles the chat drawer.
    """

    # Signals forwarded to orchestrator
    toggle_chat_requested = pyqtSignal()        # pill click → show/hide chat
    toggle_listening_requested = pyqtSignal()   # mic button click → toggle listening
    instant_solve_requested = pyqtSignal()      # Cmd+Return hotkey
    screen_snip_requested = pyqtSignal()        # ⌥O hotkey

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_listening = False
        self._is_generating = False
        self._is_dragging = False
        self._drag_start = QPoint()
        self._drag_win_start = QPoint()

        self.setWindowTitle("CluePill")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFixedSize(PILL_W, PILL_H)

        self._build_ui()
        self._setup_shortcuts()
        self._position_top_center()

        # Reassert stickiness every 1.2s
        self._reassert_timer = QTimer(self)
        self._reassert_timer.timeout.connect(self._reassert)
        self._reassert_timer.start(1200)

        # Pulse timer for "generating" animation
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._tick_pulse)
        self._pulse_val = 0
        self._pulse_up = True

    def showEvent(self, e):
        super().showEvent(e)
        configure_overlay_panel(
            self, level=1000, can_become_key=True,
            screen_share_invisible=True,
            window_title_hint="CluePill"
        )
        clamp_to_visible_screen(self)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        # ✦ Logo
        self.logo = QLabel("✦", self)
        self.logo.setStyleSheet("color: #38BDF8; font-size: 15px; font-weight: 900;")
        layout.addWidget(self.logo)

        # Status text
        self.status_lbl = QLabel("Clue", self)
        self.status_lbl.setStyleSheet(
            "color: rgba(255,255,255,0.90); font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(self.status_lbl)

        # Live waveform (tiny)
        self.wave = AudioWaveformWidget(self)
        self.wave.setFixedSize(40, 20)
        layout.addWidget(self.wave)

        layout.addStretch()

        # Mic toggle button
        self.mic_btn = QPushButton("🎙️", self)
        self.mic_btn.setFixedSize(26, 26)
        self.mic_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.mic_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 13px;
                font-size: 11px;
                padding: 0px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.18);
            }
        """)
        self.mic_btn.clicked.connect(self.toggle_listening_requested.emit)
        layout.addWidget(self.mic_btn)

        # Stealth dot
        self.dot = QLabel("●", self)
        self.dot.setStyleSheet("color: #10B981; font-size: 9px;")
        layout.addWidget(self.dot)

    def _setup_shortcuts(self):
        # Cmd+Return → instant solve (macOS Cluely exact)
        QShortcut(QKeySequence("Ctrl+Return"), self, self.instant_solve_requested.emit)
        QShortcut(QKeySequence("Meta+Return"), self, self.instant_solve_requested.emit)
        # ⌥A → instant solve alternative
        QShortcut(QKeySequence("Alt+A"), self, self.instant_solve_requested.emit)
        # ⌥M → toggle listening
        QShortcut(QKeySequence("Alt+M"), self, self.toggle_listening_requested.emit)
        # ⌥O → screen snip
        QShortcut(QKeySequence("Alt+O"), self, self.screen_snip_requested.emit)
        # ⌥C → toggle chat drawer
        QShortcut(QKeySequence("Alt+C"), self, self.toggle_chat_requested.emit)
        # Escape → collapse drawer
        QShortcut(QKeySequence("Escape"), self, self.toggle_chat_requested.emit)

    # ── Public API ───────────────────────────────────────────────────────────
    def set_listening(self, active: bool):
        self._is_listening = active
        self.wave.set_active(active)
        if active:
            self.status_lbl.setText("Listening")
            self.dot.setStyleSheet("color: #EF4444; font-size: 9px;")
            self.mic_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(239, 68, 68, 0.28);
                    border: 1px solid rgba(239, 68, 68, 0.65);
                    border-radius: 13px;
                    font-size: 11px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background: rgba(239, 68, 68, 0.45);
                }
            """)
        else:
            self.status_lbl.setText("Clue")
            self.dot.setStyleSheet("color: #10B981; font-size: 9px;")
            self.mic_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(255, 255, 255, 0.08);
                    border: 1px solid rgba(255, 255, 255, 0.15);
                    border-radius: 13px;
                    font-size: 11px;
                    padding: 0px;
                }
                QPushButton:hover {
                    background: rgba(255, 255, 255, 0.18);
                }
            """)

    def set_generating(self, active: bool):
        self._is_generating = active
        if active:
            self.status_lbl.setText("Thinking...")
            self._pulse_timer.start(60)
        else:
            self._pulse_timer.stop()
            if self._is_listening:
                self.status_lbl.setText("Listening")
            else:
                self.status_lbl.setText("Clue")

    def set_energy(self, rms: float):
        self.wave.set_energy(rms)

    def set_chat_open(self, open: bool):
        self.logo.setStyleSheet(
            f"color: {'#FFFFFF' if open else '#38BDF8'}; font-size: 15px; font-weight: 900;"
        )

    def _tick_pulse(self):
        if self._pulse_up:
            self._pulse_val = min(100, self._pulse_val + 8)
            if self._pulse_val >= 100:
                self._pulse_up = False
        else:
            self._pulse_val = max(0, self._pulse_val - 8)
            if self._pulse_val <= 0:
                self._pulse_up = True
        alpha = int(155 + self._pulse_val)
        self.logo.setStyleSheet(f"color: rgba(56,189,248,{alpha}); font-size: 15px; font-weight: 900;")

    def _reassert(self):
        if self.isVisible():
            reassert_overlay(self)

    # ── Custom pill painting ─────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), PILL_RADIUS, PILL_RADIUS)
        p.fillPath(path, QColor(14, 17, 24, 220))
        # subtle glow border
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)

    # ── Mouse drag ───────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._drag_start = e.globalPosition().toPoint()
            self._drag_win_start = self.pos()

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            delta = e.globalPosition().toPoint() - self._drag_start
            if delta.manhattanLength() > 4:
                self._is_dragging = True
                self.move(self._drag_win_start + delta)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if not self._is_dragging:
                self.toggle_chat_requested.emit()
            self._is_dragging = False
            reassert_overlay(self)

    def mouseDoubleClickEvent(self, e):
        self._position_top_center()
        reassert_overlay(self)

    def _position_top_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            self.move(g.left() + (g.width() - self.width()) // 2, g.top() + 16)
