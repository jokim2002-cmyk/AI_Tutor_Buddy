import ast
import struct
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = (ROOT / "gyanverse_ui.py").read_text(encoding="utf-8")
CORE = (ROOT / "phase11_core.py").read_text(encoding="utf-8")


class Phase11UIContractTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for name in ("main.py", "gyanverse_ui.py", "phase11_core.py", "phase11_ai.py", "scripts/launch_gyanverse_hidden.pyw"):
            ast.parse((ROOT / name).read_text(encoding="utf-8"), filename=name)

    def test_hidden_drawer_replaces_permanent_rail(self):
        self.assertIn("ft.NavigationDrawer(", UI)
        self.assertIn("page.show_drawer()", UI)
        self.assertIn("page.close_drawer()", UI)
        self.assertNotIn("NavigationRail(", UI)

    def test_tutor_composer_attachment_and_voice_contracts_exist(self):
        for marker in (
            "multiline=True",
            "ft.FilePicker().pick_files",
            "with_data=True",
            "AudioRecorder",
            "has_permission()",
            "stop_recording()",
            "AudioEncoder.WAV",
            "output_path=str(voice_capture_path)",
            "is_supported_encoder",
            "Voice text ready — edit it before sending",
            "LearningMode.HOMEWORK",
            "Read last tutor answer",
            "SPOKEN_ANSWER_DEADLINE_SECONDS = 95.0",
            "SPOKEN_PLAYBACK_DEADLINE_SECONDS = 300.0",
            "active_audio = None",
            "await active_audio.release()",
            "page.services.append(audio)",
            "await asyncio.sleep(0.15)",
            "await asyncio.wait_for(audio.play(), timeout=20.0)",
            "on_state_change=handle_audio_state",
            "ai_service.native_playback_available",
            "asyncio.to_thread(ai_service.play_wav_bytes, audio_bytes)",
            "ai_service.last_tts_backend",
        ):
            self.assertIn(marker, UI)


    def test_tutor_transcript_uses_fixed_height_non_lazy_column(self):
        self.assertIn("viewport_height = float(getattr(page, \"height\", 0) or 760)", UI)
        self.assertIn("transcript_height = max(260.0, viewport_height - 210.0)", UI)
        self.assertIn("transcript_bottom_spacer = ft.Container(height=48)", UI)
        self.assertIn("transcript = ft.Column(", UI)
        self.assertIn("height=transcript_height", UI)
        self.assertIn("horizontal_alignment=ft.CrossAxisAlignment.STRETCH", UI)
        self.assertIn("scroll=ft.ScrollMode.AUTO", UI)
        self.assertIn("auto_scroll=True", UI)
        self.assertIn("auto_scroll_animation=0", UI)
        self.assertIn("controls=[transcript_bottom_spacer]", UI)
        self.assertIn("transcript_surface = ft.Container(", UI)
        self.assertIn("content=transcript", UI)
        self.assertIn("[context_banner, transcript_surface]", UI)
        self.assertIn("page.on_resize = handle_tutor_resize", UI)
        self.assertIn("transcript_surface.height = resized_height", UI)
        self.assertIn("transcript_surface.update()", UI)
        self.assertIn("transcript.controls.insert(", UI)
        self.assertNotIn("transcript = ft.ListView(", UI)
        self.assertNotIn("build_controls_on_demand", UI)
        self.assertNotIn("cache_extent", UI)
        self.assertNotIn("await transcript.scroll_to(", UI)
        transcript_block = UI.split("transcript = ft.Column(", 1)[1].split("composer = ft.TextField(", 1)[0]
        self.assertNotIn("expand=True", transcript_block)


    def test_tutor_layout_uses_auto_growing_ultra_compact_composer(self):
        composer_block = UI.split("composer = ft.TextField(", 1)[1].split("mode_dropdown = ft.Dropdown(", 1)[0]
        self.assertIn("multiline=True", composer_block)
        self.assertIn("min_lines=1", composer_block)
        self.assertIn("max_lines=4", composer_block)
        self.assertIn("shift_enter=True", composer_block)
        self.assertIn("dense=True", composer_block)
        self.assertIn("content_padding=ft.Padding(left=0, top=4, right=0, bottom=4)", composer_block)
        self.assertIn("text_size=16", composer_block)
        self.assertIn("composer_slot = ft.Container(content=composer, expand=True)", composer_block)
        self.assertIn("composer.on_change = handle_composer_change", UI)
        self.assertIn("composer.on_submit = send", UI)
        self.assertIn("def estimated_composer_lines() -> int:", UI)
        self.assertIn("composer_height = 52.0 + ((line_count - 1) * 18.0) + attachment_extra", UI)
        self.assertIn("attachment_extra = 34.0 if selected_attachments else 0.0", UI)
        self.assertIn("current_page_height - (160.0 + composer_height)", UI)
        mode_block = UI.split("mode_dropdown = ft.Dropdown(", 1)[1].split("attachment_preview = ft.Row(", 1)[0]
        self.assertIn("width=140", mode_block)
        self.assertIn("text_size=13", mode_block)
        shell_block = UI.split("composer_shell = ft.Container(", 1)[1].split("context_banner = ft.Container(", 1)[0]
        self.assertIn("height=52", shell_block)
        self.assertIn("padding=ft.Padding(left=6, top=2, right=4, bottom=2)", shell_block)
        self.assertIn("border_radius=18", shell_block)
        self.assertIn("                            attach_button,", shell_block)
        self.assertIn("                            busy,\n                            speak_button,\n                            mic_button,", shell_block)
        self.assertIn("                        spacing=2,", shell_block)
        self.assertIn("attachment_preview.visible = bool(selected_attachments)", UI)
        self.assertNotIn("Enter sends • Shift+Enter adds a new line", shell_block)
        banner_block = UI.split("context_banner = ft.Container(", 1)[1].split("conversation_area = ft.Container(", 1)[0]
        self.assertIn("                    mode_dropdown,", banner_block)
        self.assertIn("                        expand=True,", banner_block)
        self.assertIn("alignment=ft.MainAxisAlignment.SPACE_BETWEEN", UI)
        self.assertIn("conversation_area = ft.Container(", UI)
        self.assertNotIn("                        transcript,\n                        composer_shell,", UI)

    def test_async_composer_focus_is_awaited(self):
        self.assertIn("await composer.focus()", UI)
        self.assertNotIn("\n                    composer.focus()", UI)
    def test_context_and_syllabus_contracts_exist(self):
        for marker in (
            "LearningContextStore",
            "onboarding_complete",
            "SyllabusRepository",
            "content_origin",
            "official_coverage_percent",
        ):
            self.assertIn(marker, UI + CORE)

    def test_ui_board_and_standard_dropdown_options(self):
        self.assertIn('options=[ft.dropdown.Option(item) for item in ("GSEB", "CBSE")]', UI)
        self.assertIn('options=[ft.dropdown.Option(str(item)) for item in range(1, 11)]', UI)
        self.assertNotIn('options=[ft.dropdown.Option(item) for item in ("GSEB", "CBSE", "ICSE", "Other")]', UI)

    def test_mobile_width_and_assets(self):
        self.assertIn("page.window.min_width = 360", UI)
        expected = {
            "icon.png": (1024, 1024),
            "icon_android.png": (1024, 1024),
            "icon_web.png": (512, 512),
            "icon_windows.png": (512, 512),
            "splash.png": (1080, 1920),
            "logo_mark.png": (512, 512),
        }
        for name, dimensions in expected.items():
            path = ROOT / "assets" / name
            self.assertTrue(path.exists(), name)
            with path.open("rb") as stream:
                self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n")
                length = struct.unpack(">I", stream.read(4))[0]
                self.assertEqual(stream.read(4), b"IHDR")
                width, height = struct.unpack(">II", stream.read(8))
            self.assertGreaterEqual(length, 13)
            self.assertEqual((width, height), dimensions)

    def test_packaging_configuration_preserves_android_gate(self):
        config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["tool"]["flet"]["android"]["min_sdk_version"], 24)
        permissions = config["tool"]["flet"]["android"]["permission"]
        self.assertTrue(permissions["android.permission.RECORD_AUDIO"])
        self.assertTrue(permissions["android.permission.CAMERA"])
        dependencies = config["project"]["dependencies"]
        self.assertTrue(any(item.startswith("flet-audio-recorder") for item in dependencies))
        self.assertTrue(any(item.startswith("SpeechRecognition") for item in dependencies))
        self.assertFalse(any(item.startswith("sounddevice") for item in dependencies))


    def test_hidden_desktop_launcher_contract(self):
        launcher = (ROOT / "scripts" / "launch_gyanverse_hidden.pyw").read_text(encoding="utf-8")
        runner = (ROOT / "scripts" / "run_phase11_app.ps1").read_text(encoding="utf-8")
        self.assertIn("data", launcher)
        self.assertIn("logs", launcher)
        self.assertIn("pythonw.exe", runner)
        self.assertIn("-WindowStyle Hidden", runner)
        self.assertNotIn("flet run main.py", runner)


    def test_tutor_reply_has_hard_deadline_and_nonblocking_analytics(self):
        for marker in (
            "FAST_REPLY_DEADLINE_SECONDS = 15.0",
            "asyncio.wait_for(",
            "ai_service.offline_answer(",
            "ai_service.defer_online_after_failure(",
            "ai_service.status_label",
            "Learning analytics must never block the visible tutor reply",
            "Ready • {elapsed:.1f}s",
        ):
            self.assertIn(marker, UI)

    def test_context_updates_skip_redundant_disk_and_database_writes(self):
        self.assertIn("meaningful_fields = (", UI)
        self.assertIn("if all(getattr(context, field) == getattr(validated, field)", UI)
        self.assertIn("if requested_mode != context.learning_mode", UI)

    def test_no_obsolete_project_drive_hardcoding_in_runtime_files(self):
        runtime = "\n".join(
            (ROOT / name).read_text(encoding="utf-8")
            for name in ("main.py", "gyanverse_ui.py", "phase11_core.py", "phase11_ai.py")
        )
        self.assertNotIn("D:\\Ai_Tutor_Buddy", runtime)
        self.assertNotIn("C:\\Ai_Tutor_Buddy", runtime)
        self.assertNotIn("E:\\Ai_Tutor_Buddy", runtime)

    def test_ui_button_wiring_and_contrast_contracts(self):
        self.assertIn('COLOR_BACKGROUND = "#F8F9FA"', UI)
        self.assertIn('COLOR_TEXT = "#0F172A"', UI)
        self.assertIn('COLOR_MUTED = "#334155"', UI)
        self.assertIn('COLOR_USER = "#E0EBFF"', UI)
        self.assertIn("send_button.on_click = send", UI)
        self.assertIn("attach_button.on_click = pick_files", UI)
        self.assertIn("mic_button.on_click = toggle_recording", UI)
        self.assertIn("speak_button.on_click = speak_last", UI)
        self.assertIn("board_field.on_change = profile_scope_changed", UI)
        self.assertIn("subject_field.on_change = subject_changed", UI)
        self.assertIn("chapter_field.on_change = chapter_changed", UI)
        self.assertIn("save_profile", UI)
        self.assertIn("retry_question", UI)

    def test_profile_dropdown_cascade_logic(self):
        from phase11_core import GSEBSyllabusRepository
        repo = GSEBSyllabusRepository(ROOT / "syllabus")
        syllabi = repo.all(board="GSEB")
        g8_eng = [s for s in syllabi if s.medium.casefold() == "english" and s.standard == 8]
        subjects = sorted({s.subject for s in g8_eng})
        self.assertIn("Mathematics", subjects)
        self.assertIn("Science & Technology", subjects)
        self.assertIn("Social Science", subjects)

        math_syllabus = next(s for s in g8_eng if s.subject == "Mathematics")
        chapters = [c.title for c in math_syllabus.chapters]
        self.assertTrue(len(chapters) >= 1)
        self.assertIn("Chapter 1 - Rational Numbers", chapters[0])

        topics = [t.title for t in math_syllabus.chapters[0].topics]
        self.assertTrue(len(topics) >= 1)

    def test_ui_readability_and_chatgpt_layout_contracts(self):
        self.assertIn('COLOR_TEXT = "#0F172A"', UI)
        self.assertIn('title_text = ft.Text("Tutor", size=24, weight=ft.FontWeight.BOLD', UI)
        self.assertIn("size=17", UI)
        self.assertNotIn("line_height", UI)
        self.assertIn("text_size=16", UI)
        self.assertIn("shared_conversation_width = max(340.0, min(1200.0, viewport_width - 32.0))", UI)
        self.assertIn("horizontal_alignment=ft.CrossAxisAlignment.CENTER", UI)
        self.assertIn("alignment=ft.alignment.Alignment(0, -1)", UI)
        self.assertNotIn("top_center", UI)
        self.assertIn("target_bubble_width = max(320.0, min(760.0 if is_student else 960.0, shared_w - 24.0))", UI)
        self.assertIn("tutor_bubble_width = max(320.0, min(960.0, shared_w - 24.0))", UI)
        self.assertIn("ft.Icons.COPY", UI)
        self.assertIn("page.set_clipboard(", UI)
        self.assertIn("transcript_bottom_spacer = ft.Container(height=48)", UI)
        self.assertIn("scroll=ft.ScrollMode.AUTO", UI)
        self.assertIn("height=520", UI)

    def test_app_launch_smoke_test_catches_unsupported_flet_kwargs(self):
        import flet as ft
        import gyanverse_ui
        from unittest.mock import MagicMock

        mock_page = MagicMock(spec=ft.Page)
        mock_page.window = MagicMock()
        mock_page.controls = []
        mock_page.drawer = None
        mock_page.update = MagicMock()
        mock_page.add = MagicMock()
        mock_page.run_task = MagicMock()

        try:
            gyanverse_ui.main(mock_page)
        except Exception as exc:
            self.fail(f"App launch failed due to unsupported control attribute or argument: {exc}")


if __name__ == "__main__":
    unittest.main()
