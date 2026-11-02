"""
Unit Tests for Clue SystemAudioTapService (CoreAudio Process Tap)
Validates native CoreAudio Process Tap (CATapDescription via audiotee) streaming,
chunk distribution, pipeline attachment, and lifecycle management.
"""

import os
import signal
import subprocess
import time
import unittest
from unittest.mock import MagicMock, patch

from clue.core.audio_engine import Role
from clue.core.system_audio_tap import AudioTapConfig, AudioTapStatus, SystemAudioTapService


class TestSystemAudioTapService(unittest.TestCase):

    def setUp(self):
        self.config = AudioTapConfig(
            sample_rate=16000,
            chunk_duration=0.03,
            auto_restart=False,
        )
        self.service = SystemAudioTapService(self.config)

    def tearDown(self):
        if self.service.status == AudioTapStatus.RUNNING:
            self.service.stop()

    def test_config_defaults(self):
        """Validates configuration parameters."""
        cfg = AudioTapConfig()
        self.assertEqual(cfg.sample_rate, 16000)
        self.assertEqual(cfg.chunk_duration, 0.03)
        self.assertFalse(cfg.mute_tapped)
        self.assertEqual(cfg.include_pids, [])
        self.assertEqual(cfg.exclude_pids, [])
        self.assertTrue(cfg.auto_restart)

    def test_binary_resolution(self):
        """Validates that the native audiotee binary is resolved."""
        self.assertIsNotNone(self.service.binary_path)
        self.assertTrue(os.path.isfile(self.service.binary_path))
        self.assertTrue(os.access(self.service.binary_path, os.X_OK))

    def test_status_callbacks(self):
        """Validates that state transitions invoke registered callbacks."""
        statuses = []

        def on_status(status, msg):
            statuses.append(status)

        self.service.add_status_callback(on_status)
        self.service._set_status(AudioTapStatus.STARTING, "Starting")
        self.service._set_status(AudioTapStatus.RUNNING, "Running")
        self.service._set_status(AudioTapStatus.STOPPED, "Stopped")

        self.assertEqual(
            statuses,
            [AudioTapStatus.STARTING, AudioTapStatus.RUNNING, AudioTapStatus.STOPPED]
        )

    def test_chunk_subscribers(self):
        """Validates chunk dispatch to multiple listeners."""
        received_a = []
        received_b = []

        self.service.add_chunk_callback(lambda data: received_a.append(data))
        self.service.add_chunk_callback(lambda data: received_b.append(data))

        test_pcm = b"\x00\x01\x02\x03" * 100
        callbacks = list(self.service._on_chunk_callbacks)
        for cb in callbacks:
            cb(test_pcm)

        self.assertEqual(len(received_a), 1)
        self.assertEqual(len(received_b), 1)
        self.assertEqual(received_a[0], test_pcm)
        self.assertEqual(received_b[0], test_pcm)

    def test_command_line_generation(self):
        """Validates that subprocess arguments match CATapDescription configuration."""
        custom_cfg = AudioTapConfig(
            sample_rate=48000,
            chunk_duration=0.05,
            mute_tapped=True,
            include_pids=[101, 102],
        )
        service = SystemAudioTapService(custom_cfg)

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_proc.stdout.read.return_value = b""
            mock_proc.stderr.readline.return_value = b""
            mock_popen.return_value = mock_proc

            success = service.start()
            self.assertTrue(success)

            call_args = mock_popen.call_args[0][0]
            self.assertIn("--sample-rate", call_args)
            self.assertIn("48000", call_args)
            self.assertIn("--chunk-duration", call_args)
            self.assertIn("0.05", call_args)
            self.assertIn("--mute", call_args)
            self.assertIn("--include-processes", call_args)
            self.assertIn("101", call_args)
            self.assertIn("102", call_args)

            service.stop()

    def test_live_native_tap_capture(self):
        """
        Live integration test: Launches native audiotee, captures real system PCM audio
        for 0.6 seconds, verifies byte receipt and graceful SIGTERM teardown.
        """
        if not self.service.is_available():
            self.skipTest("audiotee binary not available on this platform")

        captured_chunks = []

        def on_chunk(chunk):
            captured_chunks.append(chunk)

        self.service.add_chunk_callback(on_chunk)
        success = self.service.start()
        self.assertTrue(success, "Failed to start live audiotee process")
        self.assertEqual(self.service.status, AudioTapStatus.RUNNING)

        # Allow tap to initialize CoreAudio tap and stream for 0.6 seconds
        time.sleep(0.6)

        metrics = self.service.metrics
        self.service.stop()

        self.assertEqual(self.service.status, AudioTapStatus.STOPPED)
        self.assertGreater(len(captured_chunks), 0, "No audio chunks were captured from live tap")
        self.assertGreater(metrics["bytes_captured"], 0, "No bytes recorded in metrics")


if __name__ == "__main__":
    unittest.main()
