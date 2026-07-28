import io
import json
import tempfile
import unittest
import wave
from unittest.mock import PropertyMock, patch
from dataclasses import replace
from pathlib import Path

import phase11_ai
from phase11_ai import GyanVerseAIService, pcm_to_wav_bytes
from phase11_core import (
    GSEBSyllabus,
    GSEBSyllabusRepository,
    HomeworkAttachmentStore,
    LearningContextStore,
    LearningMode,
    offline_tutor_response,
    Phase11Error,
    StudentLearningContext,
    detect_context_from_message,
)


def sample_syllabus(*, origin="metadata_only", official=False, explanation=""):
    return {
        "schema_version": 1,
        "board": "GSEB",
        "medium": "Gujarati",
        "standard": 7,
        "subject": "Mathematics",
        "textbook": "Standard 7 Mathematics",
        "source": {
            "title": "Source title",
            "publisher": "Publisher",
            "edition": "2026",
            "official": official,
        },
        "chapters": [
            {
                "chapter_id": "c1",
                "number": "1",
                "title": "Integers",
                "topics": [
                    {
                        "topic_id": "t1",
                        "title": "Addition",
                        "learning_objectives": ["Add integers"],
                        "explanation": explanation,
                        "examples": [],
                        "exercises": [],
                        "solutions": [],
                        "practice_questions": [],
                        "marks_pattern": "",
                        "content_origin": origin,
                    }
                ],
            }
        ],
    }


class Phase11ContextTests(unittest.TestCase):
    def test_context_round_trip_and_update(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LearningContextStore(Path(directory) / "student_context.json")
            saved = store.save(
                StudentLearningContext(
                    name="Meera",
                    board="GSEB",
                    medium="Gujarati",
                    standard=8,
                    preferred_language="Gujarati",
                    current_subject="Science",
                    current_chapter="Chapter 3",
                    onboarding_complete=True,
                )
            )
            self.assertEqual(store.load(), saved)
            updated = store.update(current_topic="Heat transfer")
            self.assertEqual(updated.current_topic, "Heat transfer")
            self.assertTrue(updated.onboarding_complete)

    def test_corrupt_context_falls_back_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "student_context.json"
            path.write_text("{bad json", encoding="utf-8")
            loaded = LearningContextStore(path).load()
            self.assertEqual(loaded.board, "GSEB")
            self.assertTrue(path.with_suffix(".json.invalid").exists())

    def test_context_detection_is_conservative(self):
        base = StudentLearningContext().validate()
        updated, detected = detect_context_from_message(
            "Aaj class 8 maths chapter 4 Gujarati me padha", base
        )
        self.assertEqual(updated.standard, 8)
        self.assertEqual(updated.current_subject, "Mathematics")
        self.assertEqual(updated.current_chapter, "Chapter 4")
        self.assertEqual(updated.preferred_language, "Gujarati")
        self.assertEqual(set(detected), {"subject", "chapter", "standard", "language"})

    def test_invalid_standard_and_mode_are_rejected(self):
        with self.assertRaises(Phase11Error):
            StudentLearningContext(standard=13).validate()
        with self.assertRaises(Phase11Error):
            StudentLearningContext(learning_mode="guess").validate()


class Phase11AttachmentTests(unittest.TestCase):
    def test_attachment_history_hash_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HomeworkAttachmentStore(directory)
            item = store.add_bytes(
                student_id="s1",
                session_id="session-1",
                original_name="homework.png",
                data=b"fake-png-content",
                mime_type="image/png",
            )
            self.assertEqual(len(item.sha256), 64)
            self.assertTrue(Path(item.stored_path).exists())
            self.assertEqual(store.list_session(student_id="s1", session_id="session-1"), [item])
            self.assertTrue(store.delete(item.attachment_id, student_id="s1"))
            self.assertFalse(Path(item.stored_path).exists())
            self.assertEqual(store.list_student("s1"), [])

    def test_attachment_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = HomeworkAttachmentStore(directory)
            with self.assertRaises(Phase11Error):
                store.add_bytes(
                    student_id="s1", session_id="x", original_name="script.exe", data=b"x"
                )
            with self.assertRaises(Phase11Error):
                store.add_bytes(
                    student_id="s1", session_id="x", original_name="empty.pdf", data=b""
                )


class Phase11SyllabusTests(unittest.TestCase):
    def test_metadata_only_schema_has_zero_content_coverage(self):
        syllabus = GSEBSyllabus.from_dict(sample_syllabus())
        self.assertEqual(syllabus.coverage()["topics"], 1)
        self.assertEqual(syllabus.coverage()["coverage_percent"], 0.0)
        self.assertEqual(syllabus.coverage()["official_coverage_percent"], 0.0)

    def test_official_content_requires_official_source(self):
        with self.assertRaises(Phase11Error):
            GSEBSyllabus.from_dict(
                sample_syllabus(origin="official", official=False, explanation="Official text")
            )

    def test_metadata_only_cannot_hide_content(self):
        with self.assertRaises(Phase11Error):
            GSEBSyllabus.from_dict(
                sample_syllabus(origin="metadata_only", explanation="Hidden content")
            )

    def test_repository_install_find_and_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = GSEBSyllabusRepository(directory)
            installed = repository.install_payload(
                sample_syllabus(origin="teacher_authored", explanation="Simple explanation")
            )
            found = repository.find(medium="gujarati", standard=7, subject="mathematics")
            self.assertEqual(found, installed)
            self.assertEqual(repository.overall_coverage()["coverage_percent"], 100.0)
            self.assertEqual(repository.overall_coverage()["official_coverage_percent"], 0.0)


class Phase11AIContractTests(unittest.TestCase):
    def test_offline_ai_is_useful_and_mode_aware(self):
        service = GyanVerseAIService(api_key="")
        context = replace(
            StudentLearningContext().validate(),
            learning_mode=LearningMode.HOMEWORK.value,
            current_subject="Mathematics",
            current_chapter="Chapter 4",
        )
        answer = service.ask(message="I am stuck", context=context)
        self.assertIn("hint", answer.lower())
        self.assertIn("Chapter 4", answer)


    def test_voice_web_fallback_returns_editable_text(self):
        wav_bytes = pcm_to_wav_bytes(b"\x00\x00" * 400, sample_rate=16000)

        class FakeAudioFile:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        class FakeRecognizer:
            def record(self, source):
                return b"audio"

            def recognize_google(self, audio, language):
                self.language = language
                return "આજે ગણિતનો પાઠ સમજાવો"

        class FakeSpeechRecognition:
            AudioFile = FakeAudioFile
            Recognizer = FakeRecognizer
            UnknownValueError = RuntimeError
            RequestError = ConnectionError

        with patch.object(phase11_ai, "sr", FakeSpeechRecognition):
            service = GyanVerseAIService(api_key="")
            transcript = service.transcribe(wav_bytes, language_hint="Gujarati")

        self.assertIn("ગણિત", transcript)


    def test_provider_failure_returns_fast_offline_reply(self):
        class FakeModels:
            def generate_content(self, **_):
                raise TimeoutError("provider stalled")

        class FakeClient:
            models = FakeModels()

        class FakeTypes:
            class Part:
                @staticmethod
                def from_bytes(**kwargs):
                    return kwargs

        context = replace(
            StudentLearningContext().validate(),
            current_subject="Science",
            current_chapter="Chapter 2",
        )
        with patch.object(phase11_ai, "types", FakeTypes):
            service = GyanVerseAIService(api_key="")
            service._client = FakeClient()
            answer = service.ask(message="Explain heat", context=context)

        self.assertIn("heat is energy", answer.lower())
        self.assertNotIn("retry the online tutor", answer.lower())
        self.assertEqual(service.last_backend, "offline-fallback")
        self.assertFalse(service.configured)

    def test_offline_tutor_answers_common_question_instead_of_generic_prompt(self):
        context = replace(
            StudentLearningContext().validate(),
            current_subject="Mathematics",
            current_chapter="",
        )
        answer = offline_tutor_response("What is photosynthesis?", context)
        self.assertIn("sunlight", answer.lower())
        self.assertIn("carbon dioxide", answer.lower())
        self.assertNotIn("tell me the exact line", answer.lower())

    def test_offline_tutor_varies_with_the_actual_question(self):
        context = StudentLearningContext().validate()
        first = offline_tutor_response("Explain an unknown topic alpha", context)
        second = offline_tutor_response("Explain an unknown topic beta", context)
        self.assertNotEqual(first, second)
        self.assertIn("alpha", first.lower())
        self.assertIn("beta", second.lower())

    def test_offline_tutor_handles_simple_arithmetic(self):
        context = StudentLearningContext().validate()
        self.assertIn("70", offline_tutor_response("what is 50 + 20?", context))

    def test_online_failure_uses_retry_cooldown_not_permanent_disable(self):
        with patch.object(phase11_ai, "types", object()):
            service = GyanVerseAIService(api_key="")
            service._client = object()
            service.defer_online_after_failure("temporary timeout")
            self.assertFalse(service.configured)
            self.assertGreater(service.retry_after_seconds, 0)
            service._retry_after_monotonic = 0.0
            self.assertTrue(service.configured)


    def test_timeout_configuration_is_bounded_for_real_provider_latency(self):
        with patch.dict("os.environ", {"GYANVERSE_AI_TIMEOUT_MS": "6000"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.request_timeout_ms, 25_000)

        with patch.dict("os.environ", {"GYANVERSE_AI_TIMEOUT_MS": "999999"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.request_timeout_ms, 35_000)



    def test_tts_timeout_configuration_is_separate_and_bounded(self):
        with patch.dict("os.environ", {"GYANVERSE_TTS_TIMEOUT_MS": "1000"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_timeout_ms, 45_000)

        with patch.dict("os.environ", {"GYANVERSE_TTS_TIMEOUT_MS": "999999"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_timeout_ms, 90_000)

    def test_tts_configured_uses_dedicated_voice_client(self):
        with patch.object(phase11_ai, "types", object()):
            service = GyanVerseAIService(api_key="")
            service._client = None
            service._tts_client = object()
            self.assertTrue(service.tts_configured)
            self.assertFalse(service.configured)

    def test_local_tts_is_default_and_cached_for_replay(self):
        wav_bytes = pcm_to_wav_bytes(b"\x00\x00" * 400, sample_rate=24000)
        with tempfile.TemporaryDirectory() as directory:
            service = GyanVerseAIService(
                api_key="",
                tts_cache_dir=Path(directory),
            )
            self.assertEqual(service.tts_backend, "local-first")
            with patch.object(
                GyanVerseAIService,
                "local_tts_available",
                new_callable=PropertyMock,
                return_value=True,
            ), patch.object(
                service,
                "_synthesize_windows_sapi",
                return_value=wav_bytes,
            ) as local_synth:
                first = service.synthesize(
                    "A fraction is part of a whole.",
                    language_hint="English",
                )
                second = service.synthesize(
                    "A fraction is part of a whole.",
                    language_hint="English",
                )

            self.assertEqual(first, wav_bytes)
            self.assertEqual(second, wav_bytes)
            local_synth.assert_called_once()
            self.assertEqual(service.last_tts_backend, "cached voice")

    def test_native_playback_is_windows_only(self):
        service = GyanVerseAIService(api_key="")
        with patch.object(phase11_ai.sys, "platform", "win32"):
            self.assertTrue(service.native_playback_available)
        with patch.object(phase11_ai.sys, "platform", "linux"):
            self.assertFalse(service.native_playback_available)

    def test_pcm_is_wrapped_as_valid_wav(self):
        pcm = b"\x00\x00" * 400
        wav_bytes = pcm_to_wav_bytes(pcm, sample_rate=24000)
        with wave.open(io.BytesIO(wav_bytes), "rb") as audio:
            self.assertEqual(audio.getnchannels(), 1)
            self.assertEqual(audio.getframerate(), 24000)
            self.assertEqual(audio.getsampwidth(), 2)


if __name__ == "__main__":
    unittest.main()
