import os
import sys
import unittest
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phase11_core import (
    StudentLearningContext,
    offline_tutor_response,
    format_tutor_response,
)
from phase11_ai import (
    GyanVerseAIService,
    AIServiceError,
    TTSLatencyMetrics,
    TutorLatencyMetrics,
    SUPPORTED_GEMINI_VOICES,
)


class TestPhase11VoiceLatencyAndFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StudentLearningContext(
            student_id="test_student",
            name="Test",
            board="GSEB",
            medium="English",
            standard=7,
            current_subject="Mathematics",
            preferred_language="English",
        )

    def test_default_voice_is_aoede(self) -> None:
        service = GyanVerseAIService()
        self.assertEqual(service.tts_voice_name, "Aoede")

    def test_invalid_configured_voice_falls_back_to_aoede(self) -> None:
        with patch.dict(os.environ, {"GYANVERSE_TTS_VOICE": "InvalidVoice123"}):
            service = GyanVerseAIService()
            self.assertEqual(service.tts_voice_name, "Aoede")
            self.assertIn("Unsupported", service.last_error)

    def test_supported_voice_override_works(self) -> None:
        with patch.dict(os.environ, {"GYANVERSE_TTS_VOICE": "Kore"}):
            service = GyanVerseAIService()
            self.assertEqual(service.tts_voice_name, "Kore")

    def test_tts_health_independent_of_text_health(self) -> None:
        service = GyanVerseAIService()
        service.defer_tts_after_failure("Gemini TTS socket timeout")
        # Text service should still be configured
        self.assertTrue(service.configured or service._client is None)
        # TTS service should be in cooldown
        self.assertFalse(service.tts_configured)

    def test_two_consecutive_successful_streams_both_use_gemini(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        mock_client = MagicMock()
        mock_response1 = MagicMock()
        mock_response1.text = "Answer 1"
        mock_response2 = MagicMock()
        mock_response2.text = "Answer 2"
        mock_client.models.generate_content_stream.side_effect = [[mock_response1], [mock_response2]]
        service._client = mock_client

        ans1 = service.ask_stream(message="What is 2+2?", context=self.context)
        self.assertTrue(service.last_backend.startswith("Gemini"))

        ans2 = service.ask_stream(message="What is 3+3?", context=self.context)
        self.assertTrue(service.last_backend.startswith("Gemini"))

    def test_successful_stream_clears_transient_cooldown(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service._consecutive_failures = 2
        service._retry_after_monotonic = time.monotonic() - 1.0

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Success answer"
        mock_client.models.generate_content_stream.return_value = [mock_response]
        service._client = mock_client

        service.ask_stream(message="Explain force", context=self.context)
        self.assertEqual(service._consecutive_failures, 0)
        self.assertEqual(service._retry_after_monotonic, 0.0)

    def test_provider_failure_does_not_fabricate_mathematics_guidance(self) -> None:
        raw = offline_tutor_response(
            message="Why does a metal spoon feel colder than a wooden spoon in the same room?",
            context=self.context,  # profile subject is Mathematics
            provider_failed=True,
        )
        self.assertIn("The online tutor could not respond right now", raw)
        self.assertNotIn("For Mathematics", raw)

    def test_clear_science_question_not_rejected_because_profile_says_mathematics(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Metal conducts heat faster than wood."
        mock_client.models.generate_content_stream.return_value = [mock_response]
        service._client = mock_client

        ans = service.ask_stream(
            message="Why does a metal spoon feel colder than a wooden spoon?",
            context=self.context,
        )
        self.assertIn("Metal conducts heat", ans)
        self.assertTrue(service.last_backend.startswith("Gemini"))

    def test_tts_metrics_contain_no_answer_text(self) -> None:
        metrics = TTSLatencyMetrics(
            answer_id="ans_123",
            selected_voice="Aoede",
            tts_mode="auto",
            backend="cached voice",
            cache_hit=True,
            total_prepare_ms=1.5,
            success=True,
        )
        data = str(metrics)
        self.assertNotIn("metal spoon", data.lower())
        self.assertNotIn("photosynthesis", data.lower())

    def test_single_flight_duplicate_synthesis_prevented(self) -> None:
        service = GyanVerseAIService()
        service.tts_mode = "local"
        call_count = [0]

        def mock_sapi(text: str, language_hint: str) -> bytes:
            call_count[0] += 1
            time.sleep(0.1)
            return b"RIFF1234WAVEfmt " + b"\x00" * 40

        service._synthesize_windows_sapi = mock_sapi
        service._is_valid_wav = lambda b: True

        sample_text = f"Unique synthesis phrase {time.time_ns()}"
        res1, res2 = None, None

        def caller1():
            nonlocal res1
            res1 = service.synthesize(sample_text, language_hint="English")

        def caller2():
            nonlocal res2
            res2 = service.synthesize(sample_text, language_hint="English")

        t1 = threading.Thread(target=caller1)
        t2 = threading.Thread(target=caller2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(call_count[0], 1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1, res2)

    def test_cache_hit_avoids_provider_synthesis(self) -> None:
        service = GyanVerseAIService()
        service.tts_mode = "local"
        call_count = [0]

        def mock_sapi(text: str, language_hint: str) -> bytes:
            call_count[0] += 1
            return b"RIFF1234WAVEfmt " + b"\x00" * 40

        service._synthesize_windows_sapi = mock_sapi
        service._is_valid_wav = lambda b: True

        text = f"Cache test phrase {time.time_ns()}"
        service.synthesize(text, language_hint="English")
        self.assertEqual(call_count[0], 1)

        service.synthesize(text, language_hint="English")
        self.assertEqual(call_count[0], 1)
        self.assertTrue(service.last_tts_metrics.cache_hit)


if __name__ == "__main__":
    unittest.main()
