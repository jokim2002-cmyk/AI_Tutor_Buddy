#!/usr/bin/env python3
"""
Unit tests for Phase 1 Batch 4B: Academic Response Streaming & Natural Female Teacher Voice.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase11_core import StudentLearningContext
from phase11_ai import GyanVerseAIService, AIServiceError, TutorLatencyMetrics, pcm_to_wav_bytes



class TestPhase11StreamingAndNaturalVoice(unittest.TestCase):

    def setUp(self) -> None:
        self.context = StudentLearningContext(
            name="StreamingStudent",
            standard=7,
            board="GSEB",
            preferred_language="English",
        )

    def test_latency_metrics_contains_streaming_fields(self) -> None:
        metrics = TutorLatencyMetrics()
        self.assertTrue(hasattr(metrics, "request_start_ms"))
        self.assertTrue(hasattr(metrics, "provider_first_chunk_ms"))
        self.assertTrue(hasattr(metrics, "ui_first_visible_ms"))
        self.assertTrue(hasattr(metrics, "provider_complete_ms"))
        self.assertTrue(hasattr(metrics, "final_render_ms"))
        self.assertTrue(hasattr(metrics, "stream_used"))
        self.assertTrue(hasattr(metrics, "chunk_count"))

    def test_ask_stream_instant_greeting_routing(self) -> None:
        service = GyanVerseAIService(api_key="")
        chunks_received: list[tuple[str, str]] = []

        def on_chunk(accumulated: str, chunk: str) -> None:
            chunks_received.append((accumulated, chunk))

        answer = service.ask_stream(
            message="hello",
            context=self.context,
            on_chunk=on_chunk,
        )
        self.assertIn("GyanVerse", answer)
        self.assertEqual(service.last_metrics.route, "instant-local")
        self.assertFalse(service.last_metrics.stream_used)

    def test_ask_stream_mock_stream_accumulation(self) -> None:
        service = GyanVerseAIService(api_key="mock_key")
        service._client = MagicMock()
        mock_chunks = [
            MagicMock(text="Photosynthesis is "),
            MagicMock(text="the process by which plants "),
            MagicMock(text="make food using sunlight."),
        ]
        service._client.models.generate_content_stream.return_value = mock_chunks

        chunks_received: list[tuple[str, str]] = []
        first_visible_times: list[float] = []

        def on_chunk(accumulated: str, chunk: str) -> None:
            chunks_received.append((accumulated, chunk))

        def on_first_visible(ms: float) -> None:
            first_visible_times.append(ms)

        answer = service.ask_stream(
            message="What is photosynthesis?",
            context=self.context,
            on_chunk=on_chunk,
            on_first_visible=on_first_visible,
        )

        self.assertIn("Photosynthesis is", answer)
        self.assertEqual(len(chunks_received), 3)
        self.assertEqual(chunks_received[0][0], "Photosynthesis is ")
        self.assertEqual(chunks_received[-1][0], "Photosynthesis is the process by which plants make food using sunlight.")
        self.assertTrue(service.last_metrics.stream_used)
        self.assertEqual(service.last_metrics.chunk_count, 3)
        self.assertEqual(len(first_visible_times), 1)

    def test_ask_stream_interrupted_preserves_partial_text(self) -> None:
        service = GyanVerseAIService(api_key="mock_key")
        service._client = MagicMock()

        def stream_generator():
            yield MagicMock(text="Photosynthesis converts ")
            yield MagicMock(text="light into chemical energy.")
            raise RuntimeError("Connection reset by peer")

        service._client.models.generate_content_stream.side_effect = lambda **kwargs: stream_generator()

        answer = service.ask_stream(
            message="Explain photosynthesis in detail.",
            context=self.context,
        )

        self.assertIn("Photosynthesis converts light into chemical energy.", answer)
        self.assertIn("interrupted", answer.lower())
        self.assertTrue(service.last_metrics.fallback_used)
        self.assertTrue(service.last_metrics.stream_used)

    def test_default_voice_is_aoede(self) -> None:
        if "GYANVERSE_TTS_VOICE" in os.environ:
            del os.environ["GYANVERSE_TTS_VOICE"]
        service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_voice_name, "Aoede")
        with patch.object(GyanVerseAIService, "tts_configured", new_callable=PropertyMock, return_value=True):
            self.assertIn("Aoede", service.tts_backend_label)

    def test_environment_override_changes_selected_voice(self) -> None:
        os.environ["GYANVERSE_TTS_VOICE"] = "Kore"
        service_kore = GyanVerseAIService(api_key="")
        self.assertEqual(service_kore.tts_voice_name, "Kore")

        os.environ["GYANVERSE_TTS_VOICE"] = "   "
        service_fallback = GyanVerseAIService(api_key="")
        self.assertEqual(service_fallback.tts_voice_name, "Aoede")
        del os.environ["GYANVERSE_TTS_VOICE"]

    def test_selected_voice_changes_cache_key(self) -> None:
        service = GyanVerseAIService(api_key="", tts_voice_name="Aoede", tts_mode="auto")
        path_aoede = service._tts_cache_path("Hello student", "English", voice_name="Aoede")
        path_kore = service._tts_cache_path("Hello student", "English", voice_name="Kore")
        path_leda = service._tts_cache_path("Hello student", "English", voice_name="Leda")
        self.assertNotEqual(path_aoede, path_kore)
        self.assertNotEqual(path_aoede, path_leda)
        self.assertNotEqual(path_kore, path_leda)

    def test_auto_mode_prefers_aoede_natural_tts(self) -> None:
        service = GyanVerseAIService(api_key="mock_key", tts_mode="auto")
        with patch.object(service, "_read_cached_tts", return_value=None):
            with patch.object(service, "_synthesize_gemini", return_value=b"RIFF....WAVEheaderdata") as mock_gemini:
                with patch.object(service, "_is_valid_wav", return_value=True):
                    audio = service.synthesize("Unique test question phrase for Aoede.", language_hint="English")
                    mock_gemini.assert_called_once()
                    self.assertIn("Aoede", mock_gemini.call_args[1].get("voice_name", "Aoede"))
                    self.assertIn("Natural voice • Aoede", service.last_tts_backend)

    def test_natural_mode_does_not_silently_use_local_tts(self) -> None:
        service = GyanVerseAIService(api_key="", tts_mode="natural")
        with self.assertRaises(AIServiceError) as ctx:
            service.synthesize("Test text", voice_name="Aoede")
        self.assertIn("natural voice mode", str(ctx.exception).lower())

    def test_local_mode_does_not_invoke_online_tts(self) -> None:
        service = GyanVerseAIService(api_key="mock_key", tts_mode="local")
        with patch.object(service, "_read_cached_tts", return_value=None):
            with patch.object(service, "_synthesize_windows_sapi", return_value=b"RIFF....WAVEheaderdata") as mock_local:
                with patch.object(service, "_synthesize_gemini") as mock_gemini:
                    with patch.object(service, "_is_valid_wav", return_value=True):
                        service.synthesize("Unique test text for local mode", language_hint="English")
                        mock_local.assert_called_once()
                        mock_gemini.assert_not_called()
                        self.assertEqual(service.last_tts_backend, "local desktop voice")


    def test_audition_files_do_not_change_runtime_default(self) -> None:
        audition_dir = ROOT / ".local_voice_auditions"
        audition_dir.mkdir(parents=True, exist_ok=True)
        (audition_dir / "tutor_audition_Kore.wav").write_bytes(b"dummy kore audio")
        (audition_dir / "tutor_audition_Leda.wav").write_bytes(b"dummy leda audio")

        if "GYANVERSE_TTS_VOICE" in os.environ:
            del os.environ["GYANVERSE_TTS_VOICE"]
        service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_voice_name, "Aoede")

    def test_existing_play_stop_replay_behavior_intact(self) -> None:
        service = GyanVerseAIService(api_key="")
        pcm = b"\x00\x00" * 4800
        valid_wav = pcm_to_wav_bytes(pcm)
        with patch("winsound.PlaySound") as mock_play:
            service.play_wav_bytes(valid_wav)
            mock_play.assert_called()

        with patch("winsound.PlaySound") as mock_stop:
            service.stop_playback()
            mock_stop.assert_called()


if __name__ == "__main__":
    unittest.main()
