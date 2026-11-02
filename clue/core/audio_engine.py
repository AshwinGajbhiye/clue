"""
Clue Core — Real-Time Ambient Audio Capture & Dual-Channel Pipeline
Reverse-engineered from Cluely's native dual-channel VAD & loopback architecture.
"""

import io
import math
import os
import ssl
import struct
import subprocess
import threading
import time
import wave
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    import audioop
except ImportError:
    import audioop_lts as audioop

try:
    import certifi
    os.environ["SSL_CERT_FILE"] = certifi.where()
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())
except Exception:
    pass


class Role(str, Enum):
    ME = "me"      # User speaking via microphone
    THEM = "them"  # Interviewer / others speaking via system loopback (BlackHole / Soundflower)


class TranscriptStatus(str, Enum):
    TRANSCRIBING = "transcribing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class TranscriptEntry:
    id: str
    created_at: float
    relative_ms: int
    role: Role
    text: str = ""
    status: TranscriptStatus = TranscriptStatus.TRANSCRIBING
    wav_bytes: Optional[bytes] = None

    def formatted_line(self) -> str:
        seconds = self.relative_ms // 1000
        mins = seconds // 60
        secs = seconds % 60
        speaker = "You (Candidate)" if self.role == Role.ME else "Interviewer"
        return f"[{mins:02d}:{secs:02d}] {speaker}: {self.text}"


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Encode raw 16-bit PCM bytes into valid WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class CrossTalkSuppressor:
    """
    Suppresses acoustic feedback from computer speakers back into the microphone.
    When 'Them' (the interviewer) is speaking, mic energy is ducked or muted.
    """

    def __init__(self, ducking_factor: float = 0.05):
        self.ducking_factor = ducking_factor  # 0.05 = 95% ducking

    def process_mic_chunk(self, pcm_data: bytes, them_active: bool) -> bytes:
        if not them_active or len(pcm_data) < 2:
            return pcm_data

        if self.ducking_factor == 0.0:
            return b"\x00" * len(pcm_data)

        sample_count = len(pcm_data) // 2
        samples = struct.unpack(f"<{sample_count}h", pcm_data)
        ducked_samples = [int(s * self.ducking_factor) for s in samples]
        return struct.pack(f"<{sample_count}h", *ducked_samples)


class RealtimeVAD:
    """
    Frame-based Voice Activity Detector for 16kHz 16-bit Mono PCM.
    Calculates RMS energy and tracks speech start / end with redemption frames.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        energy_threshold: float = 0.007,
        redemption_ms: int = 850,         # 850ms silence marks utterance end
        pre_speech_pad_ms: int = 300,
        min_speech_ms: int = 350,         # Minimum 350ms to catch short questions
        max_utterance_ms: int = 15000,    # 15s chunk cap
    ):
        self.sample_rate = sample_rate
        self.frame_size = int(sample_rate * (frame_duration_ms / 1000.0))  # 480 samples
        self.energy_threshold = energy_threshold
        self.redemption_frames = int(redemption_ms / frame_duration_ms)
        self.pre_speech_pad_frames = int(pre_speech_pad_ms / frame_duration_ms)
        self.min_speech_frames = int(min_speech_ms / frame_duration_ms)
        self.max_utterance_frames = int(max_utterance_ms / frame_duration_ms)

        self._reset()

    def _reset(self):
        self.is_speaking = False
        self.speech_frame_count = 0
        self.redemption_counter = 0
        self.pre_buffer: List[bytes] = []
        self.speech_buffer: List[bytes] = []
        self.current_energy = 0.0

    def process_frame(self, pcm_frame: bytes) -> Tuple[bool, Optional[bytes], float]:
        """
        Process a single 30ms PCM frame.
        Returns:
            (has_voice_activity: bool, completed_speech_wav_or_none: Optional[bytes], current_rms: float)
        """
        if len(pcm_frame) != self.frame_size * 2:
            return self.is_speaking, None, 0.0

        samples = struct.unpack(f"<{self.frame_size}h", pcm_frame)
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / self.frame_size) / 32768.0
        self.current_energy = rms
        frame_is_speech = rms >= self.energy_threshold

        if not self.is_speaking:
            self.pre_buffer.append(pcm_frame)
            if len(self.pre_buffer) > self.pre_speech_pad_frames:
                self.pre_buffer.pop(0)

            if frame_is_speech:
                self.speech_frame_count += 1
                if self.speech_frame_count >= 2:  # debounce
                    self.is_speaking = True
                    self.speech_buffer = list(self.pre_buffer)
                    self.pre_buffer.clear()
            else:
                self.speech_frame_count = 0
            return self.is_speaking, None, rms

        # Currently speaking
        self.speech_buffer.append(pcm_frame)
        self.speech_frame_count += 1

        if frame_is_speech:
            self.redemption_counter = 0
        else:
            self.redemption_counter += 1

        # Check for natural pause (silence redemption) or utterance cap
        ended = False
        if self.redemption_counter >= self.redemption_frames:
            ended = True
        elif self.speech_frame_count >= self.max_utterance_frames:
            ended = True

        if ended:
            completed_audio = self._finalize_audio()
            self._reset()
            return False, completed_audio, rms

        return True, None, rms

    def flush_in_flight(self) -> Optional[bytes]:
        """
        Instant cutoff: Flushes whatever speech is in flight without waiting for silence.
        Used by 'Instant Ask' (Enter / ⌥A).
        """
        if not self.is_speaking or not self.speech_buffer:
            return None
        raw_pcm = b"".join(self.speech_buffer)
        audio = pcm_to_wav(raw_pcm, sample_rate=self.sample_rate)
        self._reset()
        return audio

    def _finalize_audio(self) -> Optional[bytes]:
        if len(self.speech_buffer) < self.min_speech_frames:
            return None
        raw_pcm = b"".join(self.speech_buffer)
        return pcm_to_wav(raw_pcm, sample_rate=self.sample_rate)


class TranscriptStore:
    """Thread-safe storage for timestamped diarized conversation transcripts."""

    def __init__(self, session_start_time: Optional[float] = None):
        self.session_start = session_start_time or time.time()
        self.entries: List[TranscriptEntry] = []
        self._lock = threading.Lock()

    def add_entry(self, role: Role, wav_bytes: bytes) -> TranscriptEntry:
        now = time.time()
        rel_ms = int((now - self.session_start) * 1000)
        entry_id = f"{role.value}-{int(now * 1000)}"
        entry = TranscriptEntry(
            id=entry_id,
            created_at=now,
            relative_ms=rel_ms,
            role=role,
            status=TranscriptStatus.TRANSCRIBING,
            wav_bytes=wav_bytes,
        )
        with self._lock:
            self.entries.append(entry)
        return entry

    def update_text(self, entry_id: str, text: str):
        with self._lock:
            for entry in self.entries:
                if entry.id == entry_id:
                    entry.text = text.strip()
                    entry.status = TranscriptStatus.READY if text.strip() else TranscriptStatus.FAILED
                    break

    def get_formatted_transcript(self, last_n: int = 10) -> str:
        with self._lock:
            ready_entries = [e for e in self.entries if e.status == TranscriptStatus.READY and e.text]
            return "\n".join(e.formatted_line() for e in ready_entries[-last_n:])

    def get_latest_question(self) -> Optional[str]:
        """Return the most recent utterance from the interviewer."""
        with self._lock:
            for e in reversed(self.entries):
                if e.role == Role.THEM and e.status == TranscriptStatus.READY and e.text:
                    return e.text
        return None



# ── Local Whisper STT singleton cache ───────────────────────────────────────
_whisper_model = None
_whisper_lock  = threading.Lock()


def _load_whisper():
    """Load local Whisper model once, cache it for reuse."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    with _whisper_lock:
        if _whisper_model is not None:          # double-check after lock
            return _whisper_model

        # Tier 1: faster-whisper (CTranslate2 backend — ~10× faster, smaller)
        try:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(
                "tiny",
                device="cpu",
                compute_type="int8",      # very fast on Apple Silicon / Intel
                download_root=str(Path.home() / ".cache" / "clue" / "whisper"),
            )
            return _whisper_model
        except Exception:
            pass

        # Tier 2: openai-whisper — guard against whisper.py name collision
        try:
            import importlib as _il
            oai = _il.import_module("whisper")
            if callable(getattr(oai, "load_model", None)):
                _whisper_model = oai.load_model("tiny")
                return _whisper_model
        except Exception:
            pass

    return None   # neither installed → silent degraded mode


def default_transcribe_audio(wav_bytes: bytes, role: Role) -> str:
    """Offline local STT using Whisper tiny model. Zero network calls ever."""
    if not wav_bytes or len(wav_bytes) < 2048:
        return ""

    try:
        import io, wave, numpy as np

        model = _load_whisper()
        if model is None:
            return ""   # no whisper installed — degrade silently

        # Read 16-bit PCM frames in-memory and convert to float32 normalized [-1.0, 1.0]
        # In-memory numpy array bypasses PyAV / disk I/O and avoids metadata_errors bugs
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            pcm = wf.readframes(wf.getnframes())

        if not pcm:
            return ""

        audio_np = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0

        # faster-whisper: WhisperModel has feature_extractor attribute
        if hasattr(model, "feature_extractor"):
            segs, _ = model.transcribe(
                audio_np,
                language="en",
                beam_size=1,
            )
            return " ".join(s.text for s in segs).strip()

        # openai-whisper: WhisperModel accepts float32 numpy array directly
        result = model.transcribe(audio_np, language="en", fp16=False, verbose=False)
        return (result.get("text") or "").strip()

    except Exception as e:
        print(f"  ⚠️ Clue STT transcription error ({role.value}): {e}")
        return ""





EARPHONE_KEYWORDS = [
    "airpod", "earphone", "headphone", "headset", "buds", "bluetooth",
    "external", "sony", "bose", "beats", "jabra", "shure", "sennheiser", "usb"
]


def list_input_devices() -> List[Dict]:
    """Returns list of active input audio devices with earphone/headset detection."""
    devices = []
    try:
        import pyaudio
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    name = info.get("name", "")
                    name_lower = name.lower()
                    is_earphone = any(k in name_lower for k in EARPHONE_KEYWORDS)
                    devices.append({
                        "index": i,
                        "name": name,
                        "is_earphone": is_earphone,
                        "rate": int(info.get("defaultSampleRate", 44100)),
                        "channels": info.get("maxInputChannels", 1),
                    })
            except Exception:
                pass
        p.terminate()
    except Exception:
        pass
    return devices


class LiveAudioCaptureService:
    """
    Continuous Dual-Channel Audio Capture Service for macOS:
    1. Role.ME: Microphone / Earphones capture with native hardware sample rate negotiation
       and in-memory downsampling to 16kHz (eliminating PortAudio AUHAL error -50).
    2. Role.THEM: Native ScreenCaptureKit System Audio capture streaming all system sound
       (Google Meet, Zoom, YouTube, interviewer audio) even when playing through earphones.
    """

    LOOPBACK_NAMES = ["remotepcsound", "blackhole", "soundflower", "loopback", "virtual", "aggregate", "audiotee"]

    def __init__(
        self,
        on_frame_callback: Callable[[Role, bytes, float], None],
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
        mic_device_index: Optional[int] = None,
        loopback_device_index: Optional[int] = None,
    ):
        self.on_frame_callback = on_frame_callback
        self.target_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.target_frame_samples = int(sample_rate * (frame_duration_ms / 1000.0))  # 480 samples @ 16kHz
        self.target_frame_bytes = self.target_frame_samples * 2                     # 960 bytes

        self.mic_device_index = mic_device_index
        self.active_mic_name = "Default Microphone"
        self.loopback_device_index = loopback_device_index

        self._pyaudio = None
        self._mic_stream = None
        self._mic_native_rate = 44100
        self._mic_channels = 1
        self._mic_buffer_size = 1323

        self._sck_proc: Optional[subprocess.Popen] = None
        self._loopback_stream = None
        self._tap_service: Optional[object] = None
        self._tap_accumulator = bytearray()

        self._mic_thread: Optional[threading.Thread] = None
        self._system_audio_thread: Optional[threading.Thread] = None

        self._is_running = False
        self._lock = threading.Lock()

    def start(self) -> Tuple[bool, str]:
        """Start both Microphone (Earphones) and System Audio capture pipelines."""
        with self._lock:
            if self._is_running:
                return True, "Capture already active."

            try:
                import pyaudio
            except ImportError:
                return False, "pyaudio is not installed."

            try:
                self._pyaudio = pyaudio.PyAudio()
                mic_ok, mic_name = self._open_mic_stream()
                if not mic_ok:
                    self._cleanup_audio()
                    return False, f"Could not open microphone: {mic_name}"
                self.active_mic_name = mic_name
            except Exception as e:
                self._cleanup_audio()
                return False, f"Audio initialization error: {e}"

            self._is_running = True

            # 1. Launch Microphone / Earphones Worker
            self._mic_thread = threading.Thread(
                target=self._mic_worker,
                daemon=True,
                name="ClueMicWorker",
            )
            self._mic_thread.start()

            # 2. Launch System Audio Worker (Tier 1: audiotee CATapDescription, Tier 2: ScreenCaptureKit, Tier 3: loopback)
            has_system_audio, sys_type = self._start_system_audio()

            status_msg = f"🎙️ {self.active_mic_name} + 🎧 {sys_type} Active" if has_system_audio else f"🎙️ {self.active_mic_name} Active"
            return True, status_msg

    def _open_mic_stream(self) -> Tuple[bool, str]:
        """
        Open the microphone or earphone device at its native hardware rate and channel count.
        Resampling to 16kHz is performed in Python, preventing AUHAL error -50.
        """
        all_devices = list_input_devices()
        chosen_device = None

        if self.mic_device_index is not None:
            chosen_device = next((d for d in all_devices if d["index"] == self.mic_device_index), None)

        if chosen_device is None:
            # Auto-detect earphones/headset if connected
            earphone_dev = next((d for d in all_devices if d["is_earphone"]), None)
            if earphone_dev:
                chosen_device = earphone_dev
            elif all_devices:
                # Use default input device
                try:
                    def_info = self._pyaudio.get_default_input_device_info()
                    chosen_device = next((d for d in all_devices if d["index"] == def_info["index"]), all_devices[0])
                except Exception:
                    chosen_device = all_devices[0]

        if not chosen_device:
            return False, "No audio input devices found."

        dev_index = chosen_device["index"]
        dev_name = chosen_device["name"]
        native_rate = chosen_device["rate"]
        max_channels = chosen_device["channels"]

        # Determine safe channel count (1 if supported, 2 if stereo only)
        target_channels = 1 if max_channels >= 1 else 2
        buffer_size = int(native_rate * (self.frame_duration_ms / 1000.0))

        # Attempt to open with fallback configurations if hardware demands it
        open_candidates = [
            (native_rate, target_channels, buffer_size),
            (native_rate, min(max_channels, 2), buffer_size),
            (44100, 1, int(44100 * 0.03)),
            (48000, 1, int(48000 * 0.03)),
            (16000, 1, int(16000 * 0.03)),
        ]

        import pyaudio
        last_err = None
        for rate, ch, bsize in open_candidates:
            try:
                self._mic_stream = self._pyaudio.open(
                    format=pyaudio.paInt16,
                    channels=ch,
                    rate=rate,
                    input=True,
                    input_device_index=dev_index,
                    frames_per_buffer=bsize,
                )
                self._mic_native_rate = rate
                self._mic_channels = ch
                self._mic_buffer_size = bsize
                self.mic_device_index = dev_index
                return True, dev_name
            except Exception as e:
                last_err = e

        return False, f"{dev_name} ({last_err})"

    def _start_system_audio(self) -> Tuple[bool, str]:
        """
        Starts System Audio capture:
        Tier 1 (Primary): Cluely's native CoreAudio Process Tap (`audiotee` via `CATapDescription`).
                          Captures Zoom, Google Meet, Teams, YouTube even with AirPods/earphones on.
        Tier 2 (Fallback): Native ScreenCaptureKit audio streamer (`clue_system_audio`).
        Tier 3 (Fallback): PyAudio virtual loopback device (`RemotePCSound`, `BlackHole`).
        """
        # 1. Tier 1: Cluely's CoreAudio Process Tap (audiotee)
        try:
            from clue.core.system_audio_tap import SystemAudioTapService, AudioTapConfig
            self._tap_service = SystemAudioTapService(
                AudioTapConfig(
                    sample_rate=self.target_rate,
                    chunk_duration=self.frame_duration_ms / 1000.0,
                    auto_restart=True,
                )
            )
            if self._tap_service.is_available():
                self._tap_service.add_chunk_callback(self._on_tap_chunk)
                if self._tap_service.start():
                    return True, "CoreAudio Tap"
        except Exception as e:
            print(f"  ⚠️ Clue CoreAudio Tap initialization warning: {e}")

        # 2. Tier 2: ScreenCaptureKit audio streamer
        sck_binary = Path(__file__).resolve().parent.parent.parent / "bin" / "clue_system_audio"
        if sck_binary.exists() and os.access(sck_binary, os.X_OK):
            try:
                self._sck_proc = subprocess.Popen(
                    [str(sck_binary)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                )
                time.sleep(0.08)
                if self._sck_proc.poll() is None:
                    self._system_audio_thread = threading.Thread(
                        target=self._sck_worker,
                        daemon=True,
                        name="ClueSCKSystemAudioWorker",
                    )
                    self._system_audio_thread.start()
                    return True, "ScreenCaptureKit"
            except Exception as e:
                print(f"  ⚠️ ScreenCaptureKit system audio spawn error: {e}")

        # 3. Tier 3: PyAudio virtual loopback device
        lb_index = self.loopback_device_index or self._find_loopback_device_index()
        if lb_index is not None and self._pyaudio:
            try:
                info = self._pyaudio.get_device_info_by_index(lb_index)
                rate = int(info.get("defaultSampleRate", 44100))
                ch = min(info.get("maxInputChannels", 2), 2)
                bsize = int(rate * 0.03)

                import pyaudio
                self._loopback_stream = self._pyaudio.open(
                    format=pyaudio.paInt16,
                    channels=ch,
                    rate=rate,
                    input=True,
                    input_device_index=lb_index,
                    frames_per_buffer=bsize,
                )
                self._system_audio_thread = threading.Thread(
                    target=self._pyaudio_loopback_worker,
                    args=(rate, ch, bsize),
                    daemon=True,
                    name="ClueLoopbackWorker",
                )
                self._system_audio_thread.start()
                return True, "Loopback Audio"
            except Exception as e:
                print(f"  ⚠️ Loopback audio error ({e}), running mic-only.")

        return False, "None"

    def _on_tap_chunk(self, chunk: bytes):
        """Processes chunks delivered by the CoreAudio process tap service."""
        if not self._is_running or not chunk:
            return
        self._tap_accumulator.extend(chunk)

        while len(self._tap_accumulator) >= self.target_frame_bytes:
            frame = bytes(self._tap_accumulator[:self.target_frame_bytes])
            del self._tap_accumulator[:self.target_frame_bytes]

            samples = struct.unpack(f"<{self.target_frame_samples}h", frame)
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / self.target_frame_samples) / 32768.0

            self.on_frame_callback(Role.THEM, frame, rms)

    def _mic_worker(self):
        """
        Reads from hardware microphone / earphones, converts to mono,
        resamples to 16kHz, and chunks into exact 30ms 16-bit PCM frames.
        """
        resample_state = None
        pcm_accumulator = bytearray()

        while self._is_running and self._mic_stream:
            try:
                raw_data = self._mic_stream.read(self._mic_buffer_size, exception_on_overflow=False)
                if not raw_data:
                    continue

                # 1. Convert stereo to mono if needed
                if self._mic_channels == 2:
                    mono_data = audioop.tomono(raw_data, 2, 0.5, 0.5)
                else:
                    mono_data = raw_data

                # 2. Resample to 16kHz if needed
                if self._mic_native_rate != self.target_rate:
                    pcm_16k, resample_state = audioop.ratecv(
                        mono_data, 2, 1, self._mic_native_rate, self.target_rate, resample_state
                    )
                else:
                    pcm_16k = mono_data

                pcm_accumulator.extend(pcm_16k)

                # 3. Emit exact 30ms frames (960 bytes = 480 samples @ 16kHz)
                while len(pcm_accumulator) >= self.target_frame_bytes:
                    frame = bytes(pcm_accumulator[:self.target_frame_bytes])
                    del pcm_accumulator[:self.target_frame_bytes]

                    samples = struct.unpack(f"<{self.target_frame_samples}h", frame)
                    sum_sq = sum(s * s for s in samples)
                    rms = math.sqrt(sum_sq / self.target_frame_samples) / 32768.0

                    self.on_frame_callback(Role.ME, frame, rms)

            except Exception:
                time.sleep(0.01)

    def _sck_worker(self):
        """Reads 16kHz 16-bit mono PCM streamed by ScreenCaptureKit system audio binary."""
        stdout = self._sck_proc.stdout if self._sck_proc else None
        accumulator = bytearray()

        while self._is_running and stdout:
            try:
                data = stdout.read(self.target_frame_bytes)
                if not data:
                    break
                accumulator.extend(data)

                while len(accumulator) >= self.target_frame_bytes:
                    frame = bytes(accumulator[:self.target_frame_bytes])
                    del accumulator[:self.target_frame_bytes]

                    samples = struct.unpack(f"<{self.target_frame_samples}h", frame)
                    sum_sq = sum(s * s for s in samples)
                    rms = math.sqrt(sum_sq / self.target_frame_samples) / 32768.0

                    self.on_frame_callback(Role.THEM, frame, rms)
            except Exception:
                time.sleep(0.01)

    def _pyaudio_loopback_worker(self, native_rate: int, channels: int, buffer_size: int):
        """Fallback worker for virtual loopback devices (e.g. RemotePCSound, BlackHole)."""
        resample_state = None
        accumulator = bytearray()

        while self._is_running and self._loopback_stream:
            try:
                data = self._loopback_stream.read(buffer_size, exception_on_overflow=False)
                if not data:
                    continue

                if channels == 2:
                    mono_data = audioop.tomono(data, 2, 0.5, 0.5)
                else:
                    mono_data = data

                if native_rate != self.target_rate:
                    pcm_16k, resample_state = audioop.ratecv(
                        mono_data, 2, 1, native_rate, self.target_rate, resample_state
                    )
                else:
                    pcm_16k = mono_data

                accumulator.extend(pcm_16k)

                while len(accumulator) >= self.target_frame_bytes:
                    frame = bytes(accumulator[:self.target_frame_bytes])
                    del accumulator[:self.target_frame_bytes]

                    samples = struct.unpack(f"<{self.target_frame_samples}h", frame)
                    sum_sq = sum(s * s for s in samples)
                    rms = math.sqrt(sum_sq / self.target_frame_samples) / 32768.0

                    self.on_frame_callback(Role.THEM, frame, rms)
            except Exception:
                time.sleep(0.01)

    def _find_loopback_device_index(self) -> Optional[int]:
        if not self._pyaudio:
            return None
        try:
            for i in range(self._pyaudio.get_device_count()):
                info = self._pyaudio.get_device_info_by_index(i)
                name = info.get("name", "").lower()
                if any(lb in name for lb in self.LOOPBACK_NAMES) and info.get("maxInputChannels", 0) > 0:
                    return i
        except Exception:
            pass
        return None

    def stop(self):
        """Stop capture streams, terminate system audio tap, and clean up PortAudio."""
        with self._lock:
            self._is_running = False

            if self._tap_service:
                try:
                    self._tap_service.stop()
                except Exception:
                    pass
                self._tap_service = None

            if self._sck_proc:
                try:
                    self._sck_proc.terminate()
                    self._sck_proc.wait(timeout=0.5)
                except Exception:
                    pass
                try:
                    if self._sck_proc.stdout:
                        self._sck_proc.stdout.close()
                    if self._sck_proc.stderr:
                        self._sck_proc.stderr.close()
                except Exception:
                    pass
                self._sck_proc = None

            self._cleanup_audio()

    def _cleanup_audio(self):
        try:
            if self._mic_stream:
                self._mic_stream.stop_stream()
                self._mic_stream.close()
                self._mic_stream = None
        except Exception:
            pass

        try:
            if self._loopback_stream:
                self._loopback_stream.stop_stream()
                self._loopback_stream.close()
                self._loopback_stream = None
        except Exception:
            pass

        try:
            if self._pyaudio:
                self._pyaudio.terminate()
                self._pyaudio = None
        except Exception:
            pass

