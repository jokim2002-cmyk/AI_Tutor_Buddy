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
        ):
            self.assertIn(marker, UI)

    def test_context_and_syllabus_contracts_exist(self):
        for marker in (
            "LearningContextStore",
            "onboarding_complete",
            "GSEBSyllabusRepository",
            "content_origin",
            "official_coverage_percent",
        ):
            self.assertIn(marker, UI + CORE)

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
            "FAST_REPLY_DEADLINE_SECONDS = 7.0",
            "asyncio.wait_for(",
            "ai_service.offline_answer(",
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


if __name__ == "__main__":
    unittest.main()
