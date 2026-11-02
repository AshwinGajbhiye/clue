"""
Clue Core — System Audio Tap Service (Earphone / Headphone Meeting Capture)
Reverse engineered from Cluely's native CoreAudio CATapDescription interception engine.

Captures system/meeting audio (Zoom, Google Meet, Microsoft Teams, Slack, Chrome, YouTube)
even when the user is wearing headphones, AirPods, or external DACs, without requiring
virtual loopback drivers (BlackHole, Soundflower) or aggregate devices.

Mechanism:
1. Employs CoreAudio Process Tap (`CATapDescription` / `AudioHardwareCreateProcessTap`)
   which intercepts audio at the HAL (Hardware Abstraction Layer) level BEFORE it is routed
   to physical output endpoints (AirPods, 3.5mm jack, USB DAC, or internal speakers).
2. Converts raw audio on-the-fly to 16kHz mono 16-bit signed PCM using AVAudioConverter.
3. Streams PCM chunks via stdout into Clue's Audio Pipeline (Role.THEM).
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger("ClueSystemAudioTap")


class AudioTapStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class AudioTapConfig:
    sample_rate: int = 16000
    chunk_duration: float = 0.03  # 30ms chunks (480 samples = 960 bytes at 16kHz 16-bit mono)
    include_pids: List[int] = field(default_factory=list)
    exclude_pids: List[int] = field(default_factory=list)
    mute_tapped: bool = False
    binary_path: Optional[str] = None
    auto_restart: bool = True
    max_restart_retries: int = 3


class SystemAudioTapService:
    """
    Manages the lifecycle of the native CoreAudio tap process (audiotee).
    Streams decoded 16-bit Mono PCM audio into Clue's ambient pipeline.
    """

    KNOWN_BINARY_LOCATIONS = [
        # 1. Bundled inside Clue bin directory
        str(Path(__file__).resolve().parent.parent.parent / "bin" / "audiotee"),
        # 2. Cluely macOS application bundle
        "/Applications/Cluely (New).app/Contents/Resources/extra-resources/audiotee-0.0.7/audiotee",
        "/Applications/Cluely.app/Contents/Resources/extra-resources/audiotee-0.0.7/audiotee",
        # 3. Jarvis fallback bundle
        "/Users/ashwingajbhiye/Desktop/jarvis/jarvis-2.0/voice/bin/audiotee",
    ]

    def __init__(self, config: Optional[AudioTapConfig] = None):
        self.config = config or AudioTapConfig()
        self.status = AudioTapStatus.STOPPED
        self.binary_path = self._resolve_binary_path()

        self._process: Optional[subprocess.Popen] = None
        self._stdout_thread: Optional[threading.Thread] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._monitor_thread: Optional[threading.Thread] = None

        self._stop_event = threading.Event()
        self._on_chunk_callbacks: List[Callable[[bytes], None]] = []
        self._on_status_callbacks: List[Callable[[AudioTapStatus, str], None]] = []
        self._bytes_captured = 0
        self._chunks_captured = 0
        self._restart_count = 0
        self._lock = threading.Lock()

    def _resolve_binary_path(self) -> Optional[str]:
        """Locates the audiotee binary or returns None if not found."""
        if self.config.binary_path and os.path.isfile(self.config.binary_path):
            return self.config.binary_path

        for loc in self.KNOWN_BINARY_LOCATIONS:
            if os.path.isfile(loc) and os.access(loc, os.X_OK):
                return loc

        which_path = shutil.which("audiotee")
        if which_path:
            return which_path

        return None

    def add_chunk_callback(self, callback: Callable[[bytes], None]):
        """Register a callback for raw PCM audio chunks."""
        with self._lock:
            if callback not in self._on_chunk_callbacks:
                self._on_chunk_callbacks.append(callback)

    def remove_chunk_callback(self, callback: Callable[[bytes], None]):
        with self._lock:
            if callback in self._on_chunk_callbacks:
                self._on_chunk_callbacks.remove(callback)

    def add_status_callback(self, callback: Callable[[AudioTapStatus, str], None]):
        with self._lock:
            if callback not in self._on_status_callbacks:
                self._on_status_callbacks.append(callback)

    def _set_status(self, status: AudioTapStatus, message: str = ""):
        self.status = status
        for cb in self._on_status_callbacks:
            try:
                cb(status, message)
            except Exception as e:
                logger.error(f"Status callback failed: {e}")

    def is_available(self) -> bool:
        """Checks if native CoreAudio tap capability is available on this system."""
        return self.binary_path is not None and sys.platform == "darwin"

    def start(self) -> bool:
        """Starts the native audio tap process and begins streaming."""
        with self._lock:
            if self.status == AudioTapStatus.RUNNING:
                return True

            if not self.is_available():
                self._set_status(
                    AudioTapStatus.ERROR,
                    f"audiotee binary not found or non-macOS platform (current: {sys.platform})"
                )
                return False

            self._stop_event.clear()
            self._set_status(AudioTapStatus.STARTING, "Launching CoreAudio process tap")

            cmd = [
                self.binary_path,
                "--sample-rate", str(self.config.sample_rate),
                "--chunk-duration", str(self.config.chunk_duration),
            ]

            if self.config.mute_tapped:
                cmd.append("--mute")

            if self.config.include_pids:
                cmd.append("--include-processes")
                cmd.extend(str(pid) for pid in self.config.include_pids)
            elif self.config.exclude_pids:
                cmd.append("--exclude-processes")
                cmd.extend(str(pid) for pid in self.config.exclude_pids)

            try:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
            except Exception as e:
                self._set_status(AudioTapStatus.ERROR, f"Failed to spawn {self.binary_path}: {e}")
                return False

            # Start streaming threads
            self._stdout_thread = threading.Thread(
                target=self._stdout_loop,
                name="ClueAudioTap-Stdout",
                daemon=True,
            )
            self._stderr_thread = threading.Thread(
                target=self._stderr_loop,
                name="ClueAudioTap-Stderr",
                daemon=True,
            )
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                name="ClueAudioTap-Monitor",
                daemon=True,
            )

            self._stdout_thread.start()
            self._stderr_thread.start()
            self._monitor_thread.start()

            self._set_status(AudioTapStatus.RUNNING, "System audio tap active")
            return True

    def stop(self, timeout: float = 2.0):
        """Gracefully terminates the audio tap process."""
        self._stop_event.set()

        proc = self._process
        if proc:
            if proc.poll() is None:
                try:
                    # audiotee intercepts SIGTERM and triggers graceful CoreAudio tap cleanup
                    proc.send_signal(signal.SIGTERM)
                    proc.wait(timeout=timeout)
                except (subprocess.TimeoutExpired, ProcessLookupError):
                    try:
                        proc.kill()
                        proc.wait(timeout=1.0)
                    except Exception:
                        pass
            try:
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()
            except Exception:
                pass

        self._process = None
        self._set_status(AudioTapStatus.STOPPED, "Audio tap stopped")

    def _stdout_loop(self):
        """Reads raw PCM bytes from stdout and distributes them to subscribers."""
        proc = self._process
        if not proc or not proc.stdout:
            return

        # Chunk byte size: sample_rate * chunk_duration * (16 bits / 8) * 1 channel
        chunk_bytes = int(self.config.sample_rate * self.config.chunk_duration * 2)

        while not self._stop_event.is_set() and proc.poll() is None:
            try:
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break

                self._bytes_captured += len(data)
                self._chunks_captured += 1

                # Notify subscribers with a copy of callbacks to allow concurrent modifications
                callbacks = list(self._on_chunk_callbacks)
                for cb in callbacks:
                    try:
                        cb(data)
                    except Exception as e:
                        logger.error(f"Error in audio chunk subscriber: {e}")

            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Error reading audio tap stdout: {e}")
                break

    def _stderr_loop(self):
        """Parses structured JSON log events from audiotee."""
        proc = self._process
        if not proc or not proc.stderr:
            return

        while not self._stop_event.is_set() and proc.poll() is None:
            try:
                line = proc.stderr.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue

                try:
                    event = json.loads(text)
                    msg_type = event.get("message_type")
                    msg_data = event.get("data", {})
                    msg = msg_data.get("message", "")

                    if msg_type == "metadata":
                        logger.info(f"AudioTap stream metadata: {msg_data}")
                    elif msg_type == "info":
                        logger.debug(f"AudioTap info: {msg}")
                    elif msg_type == "error":
                        logger.warning(f"AudioTap error: {msg}")

                except json.JSONDecodeError:
                    logger.debug(f"AudioTap raw log: {text}")

            except Exception as e:
                if not self._stop_event.is_set():
                    logger.error(f"Error reading audio tap stderr: {e}")
                break

    def _monitor_loop(self):
        """Monitors child process exit and manages auto-restarts."""
        proc = self._process
        if not proc:
            return

        proc.wait()

        if not self._stop_event.is_set():
            logger.warning(f"AudioTap process exited unexpectedly with code {proc.returncode}")
            if self.config.auto_restart and self._restart_count < self.config.max_restart_retries:
                self._restart_count += 1
                logger.info(f"Auto-restarting AudioTap (attempt {self._restart_count}/{self.config.max_restart_retries})")
                time.sleep(0.5)
                self.start()
            else:
                self._set_status(
                    AudioTapStatus.ERROR,
                    f"Process terminated with exit code {proc.returncode}"
                )

    @property
    def metrics(self) -> dict:
        return {
            "status": self.status.value,
            "bytes_captured": self._bytes_captured,
            "chunks_captured": self._chunks_captured,
            "restart_count": self._restart_count,
            "binary_path": self.binary_path,
        }
