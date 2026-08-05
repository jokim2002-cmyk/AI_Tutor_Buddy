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
        self.assertIn("transcript_height = max(260.0, min(640.0, viewport_height - 245.0))", UI)
        self.assertIn("transcript_bottom_spacer = ft.Container(height=24)", UI)
        self.assertIn("transcript = ft.Column(", UI)
        self.assertIn("height=transcript_height", UI)
        self.assertIn("horizontal_alignment=ft.CrossAxisAlignment.STRETCH", UI)
        self.assertIn("scroll=ft.ScrollMode.AUTO", UI)
        self.assertIn("auto_scroll=True", UI)
        self.assertIn("auto_scroll_animation=0", UI)
        self.assertIn("controls=[transcript_bottom_spacer]", UI)
        self.assertIn("transcript_surface = ft.Container(", UI)
        self.assertIn("content=transcript", UI)
        self.assertIn("            [context_banner, transcript_surface],", UI)
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
        self.assertIn("text_size=14", composer_block)
        self.assertIn("composer_slot = ft.Container(content=composer, expand=True)", composer_block)
        self.assertIn("composer.on_change = handle_composer_change", UI)
        self.assertIn("composer.on_submit = send", UI)
        self.assertIn("def estimated_composer_lines() -> int:", UI)
        self.assertIn("composer_height = 52.0 + ((line_count - 1) * 18.0) + attachment_extra", UI)
        self.assertIn("attachment_extra = 34.0 if selected_attachments else 0.0", UI)
        self.assertIn("current_page_height - (193.0 + composer_height)", UI)
        mode_block = UI.split("mode_dropdown = ft.Dropdown(", 1)[1].split("attachment_preview = ft.Row(", 1)[0]
        self.assertIn("width=132", mode_block)
        self.assertIn("text_size=12", mode_block)
        shell_block = UI.split("composer_shell = ft.Container(", 1)[1].split("context_banner = ft.Container(", 1)[0]
        self.assertIn("height=52", shell_block)
        self.assertIn("padding=ft.Padding(left=6, top=2, right=4, bottom=2)", shell_block)
        self.assertIn("border_radius=18", shell_block)
        self.assertIn("                            attach_button,", shell_block)
        self.assertIn("                            busy,\n                            speak_button,\n                            mic_button,", shell_block)
        self.assertIn("                        spacing=2,", shell_block)
        self.assertIn("attachment_preview.visible = bool(selected_attachments)", UI)
        self.assertNotIn("Enter sends • Shift+Enter adds a new line", shell_block)
        banner_block = UI.split("context_banner = ft.Container(", 1)[1].split("conversation_area = ft.Column(", 1)[0]
        self.assertIn("                    mode_dropdown,", banner_block)
        self.assertIn("                        expand=True,", banner_block)
        self.assertIn("alignment=ft.MainAxisAlignment.SPACE_BETWEEN", UI)
        self.assertIn("conversation_area = ft.Column(", UI)
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
            "FAST_REPLY_DEADLINE_SECONDS = 30.0",
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

    def test_send_flow_duplicate_submission_protection_for_online_and_offline(self):
        self.assertIn('set_busy(True, "Thinking...")', UI)
        self.assertIn('set_busy(True, "Using local tutor...")', UI)
        self.assertIn('finally:\n                busy.visible = False', UI)


if __name__ == "__main__":
    unittest.main()
