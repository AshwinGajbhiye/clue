"""
Clue Core — Screen Capture & Interactive Region Snipping Service
"""

import io
import os
import subprocess
import tempfile
from typing import Optional
from PyQt6.QtCore import QThread, pyqtSignal


def capture_screen_bytes() -> Optional[bytes]:
    """
    Fast full-screen capture returning PNG bytes.
    Uses PIL.ImageGrab if available, with fallback to macOS screencapture CLI.
    """
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        pass

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        # macOS screencapture silent mode
        subprocess.run(["screencapture", "-x", "-m", tmp_path], check=True, timeout=2)
        with open(tmp_path, "rb") as f:
            data = f.read()
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return data
    except Exception:
        return None


class ScreenSnipperWorker(QThread):
    """
    Background worker that runs macOS native interactive selection screencapture:
    `screencapture -i -s -x <target_path>`
      -i: interactive selection mode (crosshair marquee)
      -s: only allow mouse selection mode
      -x: silent mode (no shutter sound)
    """
    snippet_captured = pyqtSignal(str)   # Absolute file path to captured PNG
    snippet_cancelled = pyqtSignal()
    snippet_error = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.output_path = os.path.join(tempfile.gettempdir(), "clue_screen_snip.png")

    def run(self):
        if os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
            except Exception:
                pass

        try:
            subprocess.run(
                ["screencapture", "-i", "-s", "-x", self.output_path],
                capture_output=True,
                timeout=30,
            )

            if os.path.exists(self.output_path) and os.path.getsize(self.output_path) > 100:
                self.snippet_captured.emit(self.output_path)
            else:
                self.snippet_cancelled.emit()
        except subprocess.TimeoutExpired:
            self.snippet_cancelled.emit()
        except Exception as e:
            self.snippet_error.emit(str(e))
