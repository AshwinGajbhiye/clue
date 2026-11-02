"""
Clue UI — Live 5-Bar Audio Waveform Visualizer
Dynamic animated audio bars reflecting microphone & system loopback activity.
"""

import math
from PyQt6.QtCore import Qt, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QBrush
from PyQt6.QtWidgets import QWidget


class AudioWaveformWidget(QWidget):
    """
    Animated 5-bar live audio waveform matching Cluely's ambient visualizer.
    Pulsates gently when listening and animates dynamically with incoming audio energy.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 20)
        self._is_active = False
        self._energy = 0.0
        self._phase = 0.0
        self._bars = [0.25, 0.45, 0.70, 0.45, 0.25]
        self._color = QColor(16, 185, 129, 220)  # Emerald green by default

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._update_bars)
        self._anim_timer.start(45)  # ~22 FPS smooth animation

    def set_active(self, active: bool, color: QColor = None):
        """Set whether audio is actively being captured or speech is detected."""
        self._is_active = active
        if color:
            self._color = color
        elif active:
            self._color = QColor(16, 185, 129, 240)  # Active emerald
        else:
            self._color = QColor(255, 255, 255, 140)  # Muted white
        self.update()

    def set_energy(self, energy: float):
        """Feed normalized RMS energy [0.0, 1.0] from real audio frames."""
        self._energy = max(0.0, min(1.0, energy))

    def _update_bars(self):
        self._phase += 0.25
        if self._is_active:
            boost = max(self._energy * 1.5, 0.3)
            self._bars[0] = min(1.0, 0.25 + boost * (0.4 + 0.3 * math.sin(self._phase * 1.4)))
            self._bars[1] = min(1.0, 0.35 + boost * (0.5 + 0.4 * math.sin(self._phase * 1.7 + 0.8)))
            self._bars[2] = min(1.0, 0.45 + boost * (0.6 + 0.4 * math.sin(self._phase * 2.0 + 1.6)))
            self._bars[3] = min(1.0, 0.35 + boost * (0.5 + 0.4 * math.sin(self._phase * 1.6 + 2.4)))
            self._bars[4] = min(1.0, 0.25 + boost * (0.4 + 0.3 * math.sin(self._phase * 1.3 + 3.2)))
        else:
            # Idle ambient breathing
            self._bars[0] = 0.20 + 0.08 * math.sin(self._phase * 0.5)
            self._bars[1] = 0.35 + 0.12 * math.sin(self._phase * 0.5 + 0.4)
            self._bars[2] = 0.55 + 0.15 * math.sin(self._phase * 0.5 + 0.8)
            self._bars[3] = 0.35 + 0.12 * math.sin(self._phase * 0.5 + 1.2)
            self._bars[4] = 0.20 + 0.08 * math.sin(self._phase * 0.5 + 1.6)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        bar_count = len(self._bars)
        bar_width = 2.6
        spacing = 3.2
        total_width = bar_count * bar_width + (bar_count - 1) * spacing
        start_x = (w - total_width) / 2.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))

        for i, val in enumerate(self._bars):
            bar_h = max(3.0, val * (h - 4))
            x = start_x + i * (bar_width + spacing)
            y = (h - bar_h) / 2.0
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), 1.3, 1.3)
        painter.end()
