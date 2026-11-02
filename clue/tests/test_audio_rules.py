"""
Unit tests for Clue's Continuous Audio Rules Engine & VAD
"""

import struct
import unittest
from clue.core.audio_engine import CrossTalkSuppressor, RealtimeVAD, Role
from clue.core.audio_rules import AudioSessionState, ContinuousAudioRulesEngine


def generate_pcm_frame(sample_count: int = 480, amplitude: int = 0) -> bytes:
    """Helper to generate a 16-bit mono PCM frame."""
    return struct.pack(f"<{sample_count}h", *([amplitude] * sample_count))


class TestAudioRulesEngine(unittest.TestCase):

    def test_crosstalk_suppression(self):
        suppressor = CrossTalkSuppressor(ducking_factor=0.05)
        loud_pcm = generate_pcm_frame(480, amplitude=10000)

        # When interviewer is NOT speaking, mic frame remains unaltered
        normal_mic = suppressor.process_mic_chunk(loud_pcm, them_active=False)
        self.assertEqual(normal_mic, loud_pcm)

        # When interviewer IS speaking, mic frame is ducked to 5%
        ducked_mic = suppressor.process_mic_chunk(loud_pcm, them_active=True)
        samples = struct.unpack(f"<480h", ducked_mic)
        self.assertAlmostEqual(samples[0], 500, delta=10)

    def test_vad_speech_detection_and_silence_redemption(self):
        # 30ms frames @ 16kHz = 480 samples
        vad = RealtimeVAD(
            sample_rate=16000,
            frame_duration_ms=30,
            energy_threshold=0.015,
            redemption_ms=60,   # 2 frames
            min_speech_ms=60,   # 2 frames
            max_utterance_ms=3000,
        )

        silent_frame = generate_pcm_frame(480, amplitude=0)
        speech_frame = generate_pcm_frame(480, amplitude=8000)

        # 1. Feed silence — should remain not speaking
        is_active, completed, rms = vad.process_frame(silent_frame)
        self.assertFalse(is_active)
        self.assertIsNone(completed)

        # 2. Feed speech frames (debounce 2 frames)
        vad.process_frame(speech_frame)
        is_active, completed, rms = vad.process_frame(speech_frame)
        self.assertTrue(is_active)
        self.assertIsNone(completed)

        # 3. Feed silence to trigger redemption (2 frames)
        vad.process_frame(silent_frame)
        is_active, completed, rms = vad.process_frame(silent_frame)
        self.assertFalse(is_active)
        self.assertIsNotNone(completed)  # Utterance finalized

    def test_instant_cutoff_flush(self):
        vad = RealtimeVAD(sample_rate=16000, frame_duration_ms=30, min_speech_ms=30)
        speech_frame = generate_pcm_frame(480, amplitude=8000)

        # Start speaking
        vad.process_frame(speech_frame)
        vad.process_frame(speech_frame)
        self.assertTrue(vad.is_speaking)

        # Instant cutoff flush should return audio immediately without waiting
        flushed = vad.flush_in_flight()
        self.assertIsNotNone(flushed)
        self.assertFalse(vad.is_speaking)

    def test_continuous_listening_state_retention(self):
        engine = ContinuousAudioRulesEngine(auto_answer_questions=False)
        self.assertEqual(engine.state, AudioSessionState.IDLE)

        # Start continuous listening
        engine.start_listening()
        self.assertEqual(engine.state, AudioSessionState.LISTENING)

        # When generating, state becomes LISTENING_AND_GENERATING (never stops listening!)
        engine.set_generating_state(True)
        self.assertEqual(engine.state, AudioSessionState.LISTENING_AND_GENERATING)

        # When generation completes, state returns to LISTENING
        engine.set_generating_state(False)
        self.assertEqual(engine.state, AudioSessionState.LISTENING)

        engine.stop_listening()
        self.assertEqual(engine.state, AudioSessionState.IDLE)

    def test_substantive_query_triggering(self):
        engine = ContinuousAudioRulesEngine(auto_answer_questions=True)
        triggered_queries = []
        engine.question_ready_for_answer.connect(lambda q, t: triggered_queries.append(q))

        queries = [
            "two sum problem",
            "reverse a linked list",
            "how to optimize dynamic programming",
            "explain quicksort complexity",
            "lru cache implementation",
        ]
        for q in queries:
            engine._evaluate_question_turn("id-1", Role.ME, q)

        self.assertEqual(len(triggered_queries), 5)
        self.assertEqual(triggered_queries, queries)

    def test_filler_words_suppression(self):
        engine = ContinuousAudioRulesEngine(auto_answer_questions=True)
        triggered = []
        engine.question_ready_for_answer.connect(lambda q, t: triggered.append(q))

        fillers = ["yes", "yeah", "okay", "ok", "cool", "got it", "sure", "uh", "um", "hmm"]
        for f in fillers:
            engine._evaluate_question_turn("id-2", Role.ME, f)

        self.assertEqual(len(triggered), 0)


if __name__ == "__main__":
    unittest.main()

