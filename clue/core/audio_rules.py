"""
Clue Core — Audio Rules Engine & Simultaneous Ingestion Manager
Implements continuous 24/7 audio capture while simultaneously generating AI answers.
"""

import threading
import time
from enum import Enum
from typing import Callable, List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

from clue.config import Config
from clue.core.audio_engine import (
    CrossTalkSuppressor,
    LiveAudioCaptureService,
    RealtimeVAD,
    Role,
    TranscriptEntry,
    TranscriptStatus,
    TranscriptStore,
    default_transcribe_audio,
)

# Cap concurrent STT threads — prevents PortAudio/audioop bus error under load
_STT_SEMAPHORE = threading.Semaphore(3)


class AudioSessionState(str, Enum):
    IDLE = "idle"                                    # Not capturing audio
    LISTENING = "listening"                          # Continuous listening active
    LISTENING_AND_GENERATING = "listening_and_generating" # Generating AI response while STILL listening


QUESTION_PATTERNS = [
    "?", "how", "what", "why", "when", "where", "which", "who", "whom",
    "can you", "could you", "would you", "can we", "could we", "explain", "implement",
    "write a", "write", "solve", "find", "optimize", "complexity", "approach",
    "difference between", "design", "tell me about", "tell me", "walk me through", "tradeoff",
    "algorithm", "array", "string", "tree", "graph", "dynamic programming",
    "binary search", "hash map", "two sum", "linked list", "stack", "queue",
    "heap", "priority queue", "recursion", "backtracking", "sort", "reverse"
]

IGNORE_FILLERS = {
    "yes", "no", "yeah", "yep", "nope", "okay", "ok", "cool", "got it", "sure",
    "thanks", "thank you", "uh", "um", "hmm", "hm", "right", "alright", "hello",
    "hi", "bye", "goodbye", "sounds good", "make sense", "makes sense"
}


class ContinuousAudioRulesEngine(QObject):
    """
    Manages continuous audio capture, VAD state, utterance chunking rules,
    and concurrent answer generation signals.
    """

    # Signals for Qt UI
    audio_energy_updated = pyqtSignal(float)             # Normalized RMS [0.0 - 1.0]
    speech_started = pyqtSignal(str)                     # Role ("me" or "them")
    utterance_transcribed = pyqtSignal(str, str, str)    # (role, text, timestamp)
    question_ready_for_answer = pyqtSignal(str, str)     # (question_text, full_transcript)
    speech_detected_during_answer = pyqtSignal(str, str) # (speaker, text) — speech while previous answer is displayed
    status_changed = pyqtSignal(str)                     # UI status message

    def __init__(
        self,
        auto_answer_questions: bool = True,
        transcribe_fn: Optional[Callable[[bytes, Role], str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.auto_answer = auto_answer_questions
        self.transcribe_fn = transcribe_fn or default_transcribe_audio

        self.state = AudioSessionState.IDLE
        self.transcript_store = TranscriptStore()

        self.vad_me = RealtimeVAD(
            sample_rate=Config.SAMPLE_RATE,
            frame_duration_ms=Config.FRAME_DURATION_MS,
            energy_threshold=Config.VAD_ENERGY_THRESHOLD,
            redemption_ms=int(Config.SILENCE_TIMEOUT * 1000),
            min_speech_ms=int(Config.MIN_SPEECH_DURATION * 1000),
            max_utterance_ms=int(Config.MAX_UTTERANCE_DURATION * 1000),
        )
        self.vad_them = RealtimeVAD(
            sample_rate=Config.SAMPLE_RATE,
            frame_duration_ms=Config.FRAME_DURATION_MS,
            energy_threshold=Config.VAD_ENERGY_THRESHOLD,
            redemption_ms=int(Config.SILENCE_TIMEOUT * 1000),
            min_speech_ms=int(Config.MIN_SPEECH_DURATION * 1000),
            max_utterance_ms=int(Config.MAX_UTTERANCE_DURATION * 1000),
        )

        self.suppressor = CrossTalkSuppressor(ducking_factor=Config.CROSS_TALK_DUCKING)
        self.capture_service = LiveAudioCaptureService(on_frame_callback=self._handle_pcm_frame)

        self._them_speaking = False
        self._me_speaking = False
        self._is_generating_answer = False
        self._last_processed_entry_id: Optional[str] = None
        self._lock = threading.Lock()

    # ── 1. SESSION LIFECYCLE (RULE 1: CONTINUOUS LISTENING) ───────────────────
    def start_listening(self) -> tuple[bool, str]:
        """Start the continuous audio ingestion loop."""
        if self.state != AudioSessionState.IDLE:
            return True, "Already listening"

        ok, msg = self.capture_service.start()
        if ok:
            self.state = AudioSessionState.LISTENING
            self.status_changed.emit("🎙️ Listening continuously to Interviewer & Mic...")
        else:
            self.state = AudioSessionState.IDLE
            self.status_changed.emit(f"⚠️ Audio error: {msg}")
        return ok, msg

    def stop_listening(self):
        """Stop audio capture."""
        self.state = AudioSessionState.IDLE
        self.capture_service.stop()
        self.status_changed.emit("Audio capture paused.")

    def list_devices(self) -> List[dict]:
        """List active input devices (microphones/earphones)."""
        from clue.core.audio_engine import list_input_devices
        return list_input_devices()

    def set_mic_device(self, device_index: int):
        """Switch active microphone/earphone device dynamically."""
        restart = (self.state != AudioSessionState.IDLE)
        if restart:
            self.stop_listening()
        self.capture_service.mic_device_index = device_index
        if restart:
            self.start_listening()

    def set_generating_state(self, is_generating: bool):
        """
        Notify the engine that an answer is being generated or displayed.
        CRITICAL RULE: The audio capture loop NEVER stops during generation!
        """
        self._is_generating_answer = is_generating
        if self.state != AudioSessionState.IDLE:
            self.state = (
                AudioSessionState.LISTENING_AND_GENERATING
                if is_generating
                else AudioSessionState.LISTENING
            )

    # ── 2. REAL-TIME FRAME INGESTION & RULES CHECK ───────────────────────────
    def _handle_pcm_frame(self, role: Role, pcm_frame: bytes, rms_energy: float):
        """Process incoming 30ms PCM frame according to VAD and time rules."""
        if self.state == AudioSessionState.IDLE:
            return

        # Emit energy for live UI waveform
        self.audio_energy_updated.emit(rms_energy)

        if role == Role.THEM:
            is_active, completed_wav, rms = self.vad_them.process_frame(pcm_frame)
            if is_active and not self._them_speaking:
                self._them_speaking = True
                self.speech_started.emit("them")
            elif not is_active and self._them_speaking:
                self._them_speaking = False

            if completed_wav:
                self._dispatch_transcription(Role.THEM, completed_wav)

        elif role == Role.ME:
            # Acoustic Echo Suppression: duck mic if interviewer is talking
            clean_pcm = self.suppressor.process_mic_chunk(pcm_frame, self._them_speaking)
            is_active, completed_wav, rms = self.vad_me.process_frame(clean_pcm)
            if is_active and not self._me_speaking:
                self._me_speaking = True
                self.speech_started.emit("me")
            elif not is_active and self._me_speaking:
                self._me_speaking = False

            if completed_wav:
                self._dispatch_transcription(Role.ME, completed_wav)

    # ── 3. ASYNC TRANSCRIPTION WORKER (RULE 6: PRODUCER-CONSUMER) ────────────
    def _dispatch_transcription(self, role: Role, wav_bytes: bytes):
        # If 3 STT workers are already running, drop this frame (prevents bus error crash)
        if not _STT_SEMAPHORE.acquire(blocking=False):
            return
        entry = self.transcript_store.add_entry(role, wav_bytes)
        threading.Thread(
            target=self._transcribe_worker,
            args=(entry.id, wav_bytes, role),
            daemon=True,
        ).start()

    def _transcribe_worker(self, entry_id: str, wav_bytes: bytes, role: Role):
        try:
            text = self.transcribe_fn(wav_bytes, role)
            if not text or not text.strip():
                self.transcript_store.update_text(entry_id, "")
                return

            print(f"  📝 [STT {role.value}] {text}")
            self.transcript_store.update_text(entry_id, text)
            time_str = time.strftime("%M:%S", time.localtime())
            self.utterance_transcribed.emit(role.value, text, time_str)

            # Evaluate Question Triggers
            self._evaluate_question_turn(entry_id, role, text)

        except Exception as e:
            print(f"  ⚠️ Clue STT recognize error ({role.value}): {e}")
            self.transcript_store.update_text(entry_id, "")
        finally:
            _STT_SEMAPHORE.release()   # always release, even on error


    # ── 4. QUESTION EVALUATION & BACKGROUND NOTIFICATION (RULES 3 & 7) ────────
    def _evaluate_question_turn(self, entry_id: str, role: Role, text: str):
        with self._lock:
            # Check if this speech occurred WHILE the previous answer was being generated/displayed
            if self._is_generating_answer:
                speaker = "Interviewer" if role == Role.THEM else "You"
                print(f"  🎙️ [Background Speech] {speaker}: {text}")
                self.speech_detected_during_answer.emit(speaker, text)

            clean = text.strip().lower().rstrip(".,!?")
            if not clean or clean in IGNORE_FILLERS:
                return

            words = clean.split()
            # If only 1 word, only treat as question if it matches a recognized question keyword
            if len(words) == 1 and not any(kw in clean for kw in QUESTION_PATTERNS):
                return

            # In auto-answer mode, any substantive query triggers fast AI generation
            if self.auto_answer and not self._is_generating_answer:
                print(f"  ✦ [Question Detected] \"{text}\" -> Asking Antigravity...")
                self._last_processed_entry_id = entry_id
                full_transcript = self.transcript_store.get_formatted_transcript(last_n=30)
                self.question_ready_for_answer.emit(text, full_transcript)

    # ── 5. MANUAL INSTANT TRIGGER (RULE 5: ZERO-WAIT CUTOFF) ──────────────────
    def trigger_instant_ask(self, manual_query: Optional[str] = None):
        """
        Instantly cuts off in-flight speech without waiting for pause,
        flushes partial audio, and immediately emits question_ready_for_answer.
        """
        # Cut off any in-flight speech right now
        in_flight_me = self.vad_me.flush_in_flight()
        in_flight_them = self.vad_them.flush_in_flight()

        # If user typed an explicit query, prioritize that
        query = (manual_query or "").strip()

        # Otherwise pull latest from transcript or in-flight audio
        if not query:
            query = self.transcript_store.get_latest_question() or "Help me solve the problem discussed on screen/audio."

        full_transcript = self.transcript_store.get_formatted_transcript(last_n=30)
        self.question_ready_for_answer.emit(query, full_transcript)
