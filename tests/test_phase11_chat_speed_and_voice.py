from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from phase11_core import (
    AttachmentRecord,
    StudentLearningContext,
    classify_instant_intent,
    instant_tutor_response,
    INSTANT_INTENT_GREETING,
    INSTANT_INTENT_THANKS,
    INSTANT_INTENT_BYE,
    INSTANT_INTENT_HELP,
)
from phase11_ai import (
    GyanVerseAIService,
    TutorLatencyMetrics,
    AIServiceError,
    pcm_to_wav_bytes,
)


class TestPhase11ChatSpeedAndVoice(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="gyanverse_test_speed_voice_")
        self.context = StudentLearningContext(
            name="Aarav",
            standard=7,
            board="GSEB",
            preferred_language="English",
            current_subject="Mathematics",
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_classify_instant_intent(self):
        self.assertEqual(classify_instant_intent("hello"), INSTANT_INTENT_GREETING)
        self.assertEqual(classify_instant_intent("hi there!"), INSTANT_INTENT_GREETING)
        self.assertEqual(classify_instant_intent("namaste ji"), INSTANT_INTENT_GREETING)
        self.assertEqual(classify_instant_intent("thanks a lot"), INSTANT_INTENT_THANKS)
        self.assertEqual(classify_instant_intent("bye tutor"), INSTANT_INTENT_BYE)
        self.assertEqual(classify_instant_intent("help"), INSTANT_INTENT_HELP)

        # Academic questions must NOT be classified as instant greetings
        self.assertIsNone(classify_instant_intent("hello explain photosynthesis"))
        self.assertIsNone(classify_instant_intent("hi what is 2+2"))
        self.assertIsNone(classify_instant_intent("good morning solve x^2 = 4"))
        self.assertIsNone(classify_instant_intent("thanks for explaining fractions"))

    def test_instant_tutor_response_multilingual(self):
        ctx_en = StudentLearningContext(name="Aarav", preferred_language="English", standard=7)
        resp_en = instant_tutor_response(INSTANT_INTENT_GREETING, ctx_en)
        self.assertIn("Aarav", resp_en)
        self.assertIn("GyanVerse tutor", resp_en)

        ctx_gu = StudentLearningContext(name="Aarav", preferred_language="Gujarati", standard=7)
        resp_gu = instant_tutor_response(INSTANT_INTENT_GREETING, ctx_gu)
        self.assertIn("નમસ્તે", resp_gu)

        ctx_hi = StudentLearningContext(name="Aarav", preferred_language="Hindi", standard=7)
        resp_hi = instant_tutor_response(INSTANT_INTENT_GREETING, ctx_hi)
        self.assertIn("नमस्ते", resp_hi)

    def test_instant_routing_bypasses_provider(self):
        service = GyanVerseAIService(
            api_key=None,
            tts_cache_dir=Path(self.test_dir) / "tts_cache",
        )
        answer = service.ask(message="hello", context=self.context)
        self.assertEqual(service.last_backend, "instant-local")
        self.assertEqual(service.last_metrics.route, "instant-local")
        self.assertFalse(service.last_metrics.fallback_used)
        self.assertIn("Aarav", answer)

    def test_attachments_bypass_instant_routing(self):
        service = GyanVerseAIService(
            api_key="",
            tts_cache_dir=Path(self.test_dir) / "tts_cache",
        )
        fake_file = Path(self.test_dir) / "homework.txt"
        fake_file.write_text("Homework question 1", encoding="utf-8")

        att = AttachmentRecord(
            attachment_id="att-1",
            student_id="student-1",
            session_id="session-1",
            original_name="homework.txt",
            stored_name="homework.txt",
            mime_type="text/plain",
            size_bytes=20,
            sha256="abc",
            stored_path=str(fake_file),
            created_at="2026-08-06T00:00:00Z",
        )
        answer = service.ask(message="hello", context=self.context, attachments=[att])
        self.assertNotEqual(service.last_backend, "instant-local")
        self.assertIn("offline", service.last_backend)


    def test_latency_metrics_privacy_and_structure(self):
        service = GyanVerseAIService(
            api_key=None,
            tts_cache_dir=Path(self.test_dir) / "tts_cache",
        )
        service.ask(message="hi", context=self.context)
        metrics = service.last_metrics
        self.assertIsInstance(metrics, TutorLatencyMetrics)
        self.assertGreaterEqual(metrics.total_ms, 0.0)
        self.assertFalse(hasattr(metrics, "student_text"))
        self.assertFalse(hasattr(metrics, "tutor_text"))

    def test_timeout_bounds_enforcement(self):
        os.environ["GYANVERSE_AI_TIMEOUT_MS"] = "2000"
        service1 = GyanVerseAIService(api_key=None)
        self.assertEqual(service1.request_timeout_ms, 5_000)

        os.environ["GYANVERSE_AI_TIMEOUT_MS"] = "99000"
        service2 = GyanVerseAIService(api_key=None)
        self.assertEqual(service2.request_timeout_ms, 20_000)
        os.environ.pop("GYANVERSE_AI_TIMEOUT_MS", None)

    def test_tts_cache_and_pruning(self):
        cache_dir = Path(self.test_dir) / "tts_cache"
        service = GyanVerseAIService(
            api_key=None,
            tts_cache_dir=cache_dir,
            tts_backend="local-only",
        )
        pcm = b"\x00\x00" * 4800
        valid_wav = pcm_to_wav_bytes(pcm)

        cache_path = service._tts_cache_path("Test text answer", "English")
        service._write_tts_cache(cache_path, valid_wav)

        cached = service._read_cached_tts(cache_path)
        self.assertEqual(cached, valid_wav)
        self.assertEqual(service.last_tts_backend, "cached voice")

        # Corrupt file test
        corrupt_path = cache_dir / "corrupt.wav"
        corrupt_path.write_bytes(b"bad wave header")
        self.assertIsNone(service._read_cached_tts(corrupt_path))
        self.assertFalse(corrupt_path.exists())

    def test_playback_stop_and_nonblocking(self):
        service = GyanVerseAIService(api_key=None)
        if service.native_playback_available:
            pcm = b"\x00\x00" * 2400
            valid_wav = pcm_to_wav_bytes(pcm)
            service.play_wav_bytes(valid_wav)
            service.stop_playback()


if __name__ == "__main__":
    unittest.main()
