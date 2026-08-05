import ast
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
    Phase11Error,
    StudentLearningContext,
    build_tutor_system_instruction,
    detect_context_from_message,
    format_tutor_response,
    offline_tutor_response,
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
        with patch.dict("os.environ", {"GYANVERSE_AI_TIMEOUT_MS": "1000"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.request_timeout_ms, 5_000)

        with patch.dict("os.environ", {"GYANVERSE_AI_TIMEOUT_MS": "999999"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.request_timeout_ms, 20_000)

    def test_tts_timeout_configuration_is_separate_and_bounded(self):
        with patch.dict("os.environ", {"GYANVERSE_TTS_TIMEOUT_MS": "1000"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_timeout_ms, 5_000)

        with patch.dict("os.environ", {"GYANVERSE_TTS_TIMEOUT_MS": "999999"}):
            service = GyanVerseAIService(api_key="")
        self.assertEqual(service.tts_timeout_ms, 20_000)

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
            service.tts_mode = "local"
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


class Phase11TutorResponseAndFormatterTests(unittest.TestCase):
    def test_tutor_system_instruction_does_not_fabricate_memory_or_quizzes(self):
        context = StudentLearningContext().validate()
        instruction = build_tutor_system_instruction(context)
        self.assertIn("Do NOT mention previous sessions, memory", instruction)
        self.assertIn("Never ask 'Let's check your understanding' by default", instruction)
        self.assertIn("Never generate quizzes or follow-up questions unless", instruction)

    def test_formatter_removes_unnecessary_leading_filler(self):
        result = format_tutor_response("Hello! Here is the explanation.", student_message="Explain force")
        self.assertEqual(result, "Here is the explanation.")

        result_greeted = format_tutor_response("Hello! Here is the explanation.", student_message="Hi")
        self.assertEqual(result_greeted, "Hello! Here is the explanation.")

    def test_formatter_preserves_meaningful_multiline_steps(self):
        multiline = "Step 1: Identify given values.\nStep 2: Apply formula.\n\nFinal result = 10."
        result = format_tutor_response(multiline, student_message="Solve this")
        self.assertEqual(result, multiline)

    def test_formatter_preserves_gujarati_and_hindi_unicode(self):
        gu_text = "આ ગણિતનો પ્રશ્ન છે:\n1. પ્રથમ પગલું\n2. બીજું પગલું"
        hi_text = "यह गणित का प्रश्न है:\n1. पहला कदम\n2. दूसरा कदम"
        self.assertEqual(format_tutor_response(gu_text, student_message="ઉકેલો"), gu_text)
        self.assertEqual(format_tutor_response(hi_text, student_message="हल करो"), hi_text)

    def test_formatter_does_not_remove_mathematical_meaning(self):
        math_text = "50 + 20 = 70\nx² + y² = z²\np / q, q ≠ 0"
        self.assertEqual(format_tutor_response(math_text, student_message="Solve"), math_text)

    def test_offline_service_applies_formatting(self):
        service = GyanVerseAIService(api_key="")
        context = StudentLearningContext().validate()
        answer = service.offline_answer(message="Explain photosynthesis", context=context)
        self.assertTrue(len(answer) > 0)
        self.assertIn("Photosynthesis is", answer)

    def test_online_service_applies_formatting_using_mocked_provider(self):
        class FakeResponse:
            text = "Hello! Step 1: Plants convert light.\nStep 2: Oxygen is released."

        class FakeModels:
            def generate_content(self, **_):
                return FakeResponse()

        class FakeClient:
            models = FakeModels()

        context = StudentLearningContext().validate()
        with patch.object(phase11_ai, "types", object()):
            service = GyanVerseAIService(api_key="")
            service._client = FakeClient()
            answer = service.ask(message="Explain photosynthesis", context=context)

        self.assertNotIn("Hello!", answer)
        self.assertIn("Step 1: Plants convert light.\nStep 2: Oxygen is released.", answer)

    def test_no_temporary_debug_prints_remain_in_ai_service(self):
        ai_source = Path(phase11_ai.__file__).read_text(encoding="utf-8")
        parsed = ast.parse(ai_source)
        print_calls = [
            node for node in ast.walk(parsed)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print"
        ]
        self.assertEqual(len(print_calls), 0, "No print() calls should remain in production AI service")


class Phase11CanonicalScopeTests(unittest.TestCase):
    def test_accepted_and_rejected_boards_and_standards(self):
        for board in ("GSEB", "CBSE"):
            for std in range(1, 11):
                ctx = StudentLearningContext(board=board, standard=std).validate()
                self.assertEqual(ctx.board, board)
                self.assertEqual(ctx.standard, std)

        for invalid_board in ("ICSE", "Other", "StateBoard", "invalid"):
            with self.assertRaises(Phase11Error):
                StudentLearningContext(board=invalid_board).validate()

        for invalid_std in (0, 11, 12, -1, 99):
            with self.assertRaises(Phase11Error):
                StudentLearningContext(standard=invalid_std).validate()

    def test_invalid_stored_context_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "student_context.json"
            bad_payload = {
                "student_id": "s1",
                "name": "Test",
                "board": "ICSE",
                "medium": "English",
                "standard": 11,
                "preferred_language": "English",
                "current_subject": "Math",
                "current_chapter": "",
                "current_topic": "",
                "learning_mode": "explain",
                "onboarding_complete": True,
                "updated_at": "2026-08-06T00:00:00Z"
            }
            path.write_text(json.dumps(bad_payload), encoding="utf-8")
            loaded = LearningContextStore(path).load()
            self.assertFalse(loaded.onboarding_complete)
            self.assertEqual(loaded.board, "GSEB")
            self.assertEqual(loaded.standard, 7)
            self.assertTrue(path.with_suffix(".json.invalid").exists())

    def test_board_neutral_syllabus_and_repository(self):
        from phase11_core import BoardSyllabus, SyllabusRepository, GSEBSyllabus, GSEBSyllabusRepository
        self.assertIs(GSEBSyllabus, BoardSyllabus)
        self.assertIs(GSEBSyllabusRepository, SyllabusRepository)

        gseb_payload = sample_syllabus(official=True, origin="official", explanation="Official GSEB content")
        gseb_payload["board"] = "GSEB"
        gseb_syllabus = BoardSyllabus.from_dict(gseb_payload)
        self.assertEqual(gseb_syllabus.board, "GSEB")
        self.assertEqual(gseb_syllabus.standard, 7)

        cbse_payload = sample_syllabus(official=True, origin="official", explanation="Official CBSE content")
        cbse_payload["board"] = "CBSE"
        cbse_syllabus = BoardSyllabus.from_dict(cbse_payload)
        self.assertEqual(cbse_syllabus.board, "CBSE")
        self.assertEqual(cbse_syllabus.standard, 7)

        invalid_board_payload = sample_syllabus()
        invalid_board_payload["board"] = "ICSE"
        with self.assertRaises(Phase11Error):
            BoardSyllabus.from_dict(invalid_board_payload)

        invalid_std_payload = sample_syllabus()
        invalid_std_payload["standard"] = 11
        with self.assertRaises(Phase11Error):
            BoardSyllabus.from_dict(invalid_std_payload)

        with tempfile.TemporaryDirectory() as directory:
            repo = SyllabusRepository(directory)
            repo.install_payload(gseb_payload)
            repo.install_payload(cbse_payload)

            self.assertEqual(len(repo.all()), 2)
            self.assertEqual(len(repo.all(board="GSEB")), 1)
            self.assertEqual(len(repo.all(board="CBSE")), 1)
            self.assertEqual(repo.find(board="CBSE", medium="gujarati", standard=7, subject="mathematics"), cbse_syllabus)

    def test_validate_script_contracts(self):
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "validate_phase11.ps1"
        content = script_path.read_text(encoding="utf-8")

        self.assertIn('[string]$ProjectRoot = ""', content)
        self.assertIn('Split-Path -Parent $PSScriptRoot', content)
        self.assertIn('DYNAMIC_TEST_COUNT', content)
        self.assertNotIn('Expected prepared total: 215 tests.', content)
        self.assertIn('Windows EXE, Android APK, and physical-device acceptance remain pending.', content)


if __name__ == "__main__":
    unittest.main()
