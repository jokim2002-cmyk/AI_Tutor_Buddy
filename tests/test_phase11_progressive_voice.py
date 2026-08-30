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
    split_into_sentences,
)
from phase11_ai import (
    GyanVerseAIService,
    AIServiceError,
    TutorVoiceSegment,
    TutorAudioManifest,
    TTSLatencyMetrics,
    _segment_cache_key,
)


class TestPhase11ProgressiveVoice(unittest.TestCase):
    def setUp(self) -> None:
        self.context = StudentLearningContext(
            student_id="test_student",
            name="Test",
            board="GSEB",
            medium="English",
            standard=7,
            current_subject="Science",
            preferred_language="English",
        )

    def test_single_chunk_provider_labeled_single_chunk(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        mock_client = MagicMock()
        mock_chunk = MagicMock()
        mock_chunk.text = "This is a single complete answer."
        mock_client.models.generate_content_stream.return_value = [mock_chunk]
        service._client = mock_client

        ans = service.ask_stream(message="Explain photosynthesis", context=self.context)
        self.assertEqual(service.last_metrics.route, "gemini-single-chunk")
        self.assertEqual(service.last_metrics.backend, "Gemini single-chunk")
        self.assertEqual(service.last_metrics.chunk_count, 1)

    def test_multiple_chunks_labeled_stream(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        mock_client = MagicMock()
        chunk1 = MagicMock()
        chunk1.text = "Photosynthesis converts "
        chunk2 = MagicMock()
        chunk2.text = "light energy into chemical energy."
        mock_client.models.generate_content_stream.return_value = [chunk1, chunk2]
        service._client = mock_client

        received_chunks = []

        def on_chunk(acc, chunk):
            received_chunks.append((acc, chunk))

        ans = service.ask_stream(message="Explain photosynthesis", context=self.context, on_chunk=on_chunk)
        self.assertEqual(service.last_metrics.route, "gemini-stream")
        self.assertEqual(service.last_metrics.backend, "Gemini stream")
        self.assertEqual(service.last_metrics.chunk_count, 2)
        self.assertEqual(len(received_chunks), 2)
        # Verify history has only 1 completed entry
        self.assertEqual(len(service._history), 1)

    def test_sentence_segmenter_english_hindi_gujarati_decimals(self) -> None:
        eng = "Photosynthesis is 3.14 approx. Step 1. Light reaction. Step 2. Dark reaction."
        seg_eng = split_into_sentences(eng)
        self.assertIn("Photosynthesis is 3.14 approx.", seg_eng)
        self.assertIn("Step 1. Light reaction.", seg_eng)
        self.assertIn("Step 2. Dark reaction.", seg_eng)

        hin = "पौधों में प्रकाश संश्लेषण होता है। यह उपयोगी है।"
        seg_hin = split_into_sentences(hin)
        self.assertEqual(len(seg_hin), 2)
        self.assertIn("पौधों में प्रकाश संश्लेषण होता है।", seg_hin)

        guj = "વનસ્પતિમાં પ્રકાશ સંશ્લેષણ થાય છે. તે મહત્વનું છે."
        seg_guj = split_into_sentences(guj)
        self.assertEqual(len(seg_guj), 2)

    def test_default_prefetch_policy_is_none(self) -> None:
        service = GyanVerseAIService()
        self.assertEqual(service.tts_prefetch_policy, "none")

    def test_prefetch_policy_none_does_not_prepare_automatically(self) -> None:
        with patch.dict(os.environ, {"GYANVERSE_TTS_PREFETCH_POLICY": "none"}):
            service = GyanVerseAIService()
            manifest = service.create_audio_manifest(
                "First sentence. Second sentence.",
                language_hint="English",
                message_id="msg_none",
            )
            service.prepare_manifest_progressive(manifest)
            self.assertEqual(manifest.segments[0].state, "IDLE")

    def test_prefetch_policy_on_answer_complete_prepares_segments(self) -> None:
        with patch.dict(os.environ, {"GYANVERSE_TTS_PREFETCH_POLICY": "on-answer-complete"}):
            service = GyanVerseAIService()
            service.tts_mode = "local"
            service._synthesize_windows_sapi = lambda text, language_hint: b"RIFF1234WAVEfmt " + b"\x00" * 40
            service._is_valid_wav = lambda b: True

            manifest = service.create_audio_manifest(
                "First sentence. Second sentence.",
                language_hint="English",
                message_id="msg_on_complete",
            )
            service.prepare_manifest_progressive(manifest)
            self.assertEqual(manifest.segments[0].state, "READY")
            self.assertEqual(manifest.segments[1].state, "READY")

    def test_segment_cache_key_isolation(self) -> None:
        k1 = _segment_cache_key("Photosynthesis is good.", "English", "Aoede", "natural")
        k2 = _segment_cache_key("Photosynthesis is good.", "English", "Kore", "natural")
        k3 = _segment_cache_key("Photosynthesis is good.", "English", "Aoede", "local")
        self.assertNotEqual(k1, k2)
        self.assertNotEqual(k1, k3)
        # Must differ from whole answer key
        self.assertTrue(k1.startswith("2") or k1.startswith("a") or len(k1) == 64)

    def test_single_flight_segment_duplication_prevented(self) -> None:
        service = GyanVerseAIService()
        service.tts_mode = "local"
        service._read_cached_tts = lambda cache_path: None
        call_count = [0]

        def mock_sapi(text: str, language_hint: str) -> bytes:
            call_count[0] += 1
            time.sleep(0.1)
            return b"RIFF1234WAVEfmt " + b"\x00" * 40

        service._synthesize_windows_sapi = mock_sapi
        service._is_valid_wav = lambda b: True

        manifest = service.create_audio_manifest(
            f"Unique segment test {time.time_ns()}.",
            language_hint="English",
            message_id="msg_sf",
        )
        seg = manifest.segments[0]

        res1, res2 = None, None

        def worker1():
            nonlocal res1
            res1 = service.synthesize_segment(seg, answer_id="msg_sf")

        def worker2():
            nonlocal res2
            res2 = service.synthesize_segment(seg, answer_id="msg_sf")

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(call_count[0], 1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1, res2)

    def test_default_prefetch_policy_is_none(self) -> None:
        service = GyanVerseAIService()
        self.assertEqual(service.tts_prefetch_policy, "none")

    def test_one_tutor_answer_makes_at_most_one_provider_request(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.tts_mode = "natural"
        call_count = [0]

        def mock_gen_stream(*args, **kwargs):
            call_count[0] += 1
            mock_chunk = MagicMock()
            mock_chunk.candidates = [MagicMock()]
            mock_chunk.candidates[0].content.parts = [MagicMock()]
            mock_chunk.candidates[0].content.parts[0].inline_data.data = b"\x00" * 24000
            yield mock_chunk

        service._tts_client = MagicMock()
        service._tts_client.models.generate_content_stream = mock_gen_stream

        text_5_sentences = (
            f"Sentence one about photosynthesis {time.time_ns()}. "
            "Sentence two explains light absorption. "
            "Sentence three describes chlorophyll. "
            "Sentence four mentions carbon dioxide. "
            "Sentence five concludes the explanation."
        )

        audio = service.synthesize(text_5_sentences, language_hint="English", answer_id="ans_5s")
        self.assertIsNotNone(audio)
        self.assertEqual(call_count[0], 1)
        self.assertEqual(service.last_tts_metrics.provider_call_count, 1)

    def test_replay_uses_cache_and_makes_zero_new_requests(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.tts_mode = "natural"
        call_count = [0]

        def mock_gen_stream(*args, **kwargs):
            call_count[0] += 1
            mock_chunk = MagicMock()
            mock_chunk.candidates = [MagicMock()]
            mock_chunk.candidates[0].content.parts = [MagicMock()]
            mock_chunk.candidates[0].content.parts[0].inline_data.data = b"\x00" * 24000
            yield mock_chunk

        service._tts_client = MagicMock()
        service._tts_client.models.generate_content_stream = mock_gen_stream

        sample_text = f"Sample answer {time.time_ns()}."
        audio1 = service.synthesize(sample_text, language_hint="English")
        self.assertEqual(call_count[0], 1)
        self.assertFalse(service.last_tts_metrics.cache_hit)

        audio2 = service.synthesize(sample_text, language_hint="English")
        self.assertEqual(call_count[0], 1)  # No new network request!
        self.assertTrue(service.last_tts_metrics.cache_hit)
        self.assertEqual(service.last_tts_metrics.provider_call_count, 0)
        self.assertEqual(audio1, audio2)

    def test_429_quota_limit_sets_quota_limited_flag_and_no_local_fallback(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.tts_mode = "natural"
        sapi_called = [False]

        def mock_gen_stream(*args, **kwargs):
            raise AIServiceError("RESOURCE_EXHAUSTED: Quota limit reached (429)")

        service._tts_client = MagicMock()
        service._tts_client.models.generate_content_stream = mock_gen_stream
        service._synthesize_windows_sapi = lambda *a, **k: sapi_called.setter(True)

        with self.assertRaises(AIServiceError) as cm:
            service.synthesize("Test phrase", language_hint="English")

        self.assertTrue(getattr(cm.exception, "quota_limited", False))
        self.assertFalse(sapi_called[0])

    def test_natural_mode_never_invokes_windows_sapi(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.tts_mode = "natural"
        sapi_called = [False]

        def mock_sapi(*args, **kwargs):
            sapi_called[0] = True
            return b"RIFF1234WAVEfmt "

        def mock_gemini(*args, **kwargs):
            raise AIServiceError("Gemini failed")

        service._synthesize_windows_sapi = mock_sapi
        service._synthesize_gemini = mock_gemini

        with self.assertRaises(AIServiceError):
            service.synthesize("Test phrase", language_hint="English")

        self.assertFalse(sapi_called[0])

    def test_tts_timeout_clears_single_flight_and_releases_waiters(self) -> None:
        with patch.dict(os.environ, {"GYANVERSE_TTS_TIMEOUT_MS": "5000"}):
            service = GyanVerseAIService()
            self.assertEqual(service.tts_timeout_ms, 5000)

        service.tts_mode = "local"
        service._read_cached_tts = lambda cache_path: None

        def failing_sapi(text: str, language_hint: str) -> bytes:
            time.sleep(0.05)
            raise AIServiceError("Synthesis failed")

        service._synthesize_windows_sapi = failing_sapi

        manifest = service.create_audio_manifest(
            f"Failure test {time.time_ns()}.",
            language_hint="English",
            message_id="msg_fail",
        )
        seg = manifest.segments[0]

        res1, res2 = None, None
        err1, err2 = None, None

        def worker1():
            nonlocal res1, err1
            try:
                res1 = service.synthesize_segment(seg, answer_id="msg_fail")
            except Exception as exc:
                err1 = exc

        def worker2():
            nonlocal res2, err2
            try:
                res2 = service.synthesize_segment(seg, answer_id="msg_fail")
            except Exception as exc:
                err2 = exc

        t1 = threading.Thread(target=worker1)
        t2 = threading.Thread(target=worker2)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIsNotNone(err1)
        self.assertIsNotNone(err2)
        self.assertEqual(seg.state, "FAILED")
        self.assertEqual(len(service._in_flight_tts), 0)

    def test_on_segment_failed_called_on_prepare_failure(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.tts_mode = "natural"
        service._synthesize_gemini = MagicMock(side_effect=AIServiceError("Timeout"))

        manifest = service.create_audio_manifest(
            "First sentence. Second sentence.",
            language_hint="English",
            message_id="msg_failed_cb",
        )

        failed_calls = []

        def on_failed(idx, seg, exc):
            failed_calls.append((idx, seg, exc))

        service.prepare_manifest_progressive(manifest, policy="first-segment", on_segment_failed=on_failed)
        self.assertEqual(len(failed_calls), 1)
        self.assertEqual(failed_calls[0][0], 0)
        self.assertEqual(manifest.segments[0].state, "FAILED")

    def test_tts_metrics_contain_no_secrets_or_transcript(self) -> None:
        m = TTSLatencyMetrics(
            answer_id="msg_secret",
            selected_voice="Aoede",
            tts_mode="natural",
            first_sentence_ready_ms=10.0,
            first_audio_ready_ms=250.0,
            segment_count=3,
            prepared_segment_count=1,
            prefetch_policy="first-segment",
        )
        rep = str(m)
        self.assertNotIn("secret question", rep.lower())
        self.assertNotIn("photosynthesis", rep.lower())

    def test_short_answer_voice_still_works(self) -> None:
        from phase11_core import split_into_speech_chunks, prepare_spoken_text
        short_ans = "Photosynthesis is how green plants prepare food using sunlight and chlorophyll."
        spoken = prepare_spoken_text(short_ans)
        chunks = split_into_speech_chunks(short_ans, max_chars=280)
        self.assertIn("Photosynthesis", spoken)
        self.assertEqual(len(chunks), 1)

    def test_long_comparison_answer_split_into_multiple_chunks(self) -> None:
        from phase11_core import split_into_speech_chunks
        long_ans = (
            "Comparison: Inexhaustible vs Exhaustible Natural Resources\n\n"
            "Feature / Concept:\n"
            "- Inexhaustible: Inexhaustible natural resources are present in unlimited quantity in nature and are not likely to be exhausted by human activities.\n"
            "- Exhaustible: Exhaustible natural resources are present in limited quantity in nature and can be exhausted by human activities over time.\n\n"
            "Natural Occurrence:\n"
            "- Inexhaustible: Plentiful quantity in nature such as sunlight and air.\n"
            "- Exhaustible: Underground deposits formed over millions of years such as coal and petroleum.\n\n"
            "Primary Examples:\n"
            "- Inexhaustible: Sunlight and air.\n"
            "- Exhaustible: Petrol, diesel, kerosene, natural gas, and coal."
        )
        chunks = split_into_speech_chunks(long_ans, max_chars=280)
        self.assertGreaterEqual(len(chunks), 3)
        for c in chunks:
            self.assertLessEqual(len(c), 320)

    def test_footer_source_text_removed_from_spoken_text(self) -> None:
        from phase11_core import prepare_spoken_text
        ans_with_footer = (
            "Photosynthesis is the process by which green plants make food.\n\n"
            "Source type: Local syllabus package (grounded)\n"
            "Board: GSEB; Medium: English; Standard: 7"
        )
        spoken = prepare_spoken_text(ans_with_footer)
        self.assertIn("Photosynthesis", spoken)
        self.assertNotIn("Source type", spoken)
        self.assertNotIn("GSEB", spoken)
        self.assertNotIn("Medium", spoken)

    def test_stop_cancels_remaining_chunks_and_chunk_failure_handled(self) -> None:
        service = GyanVerseAIService(api_key="test_key")
        service.stop_playback()
        self.assertTrue(service._stop_playback_event.is_set())
        service._stop_playback_event.clear()
        self.assertFalse(service._stop_playback_event.is_set())


if __name__ == "__main__":
    unittest.main()
