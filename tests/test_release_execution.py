import json
import tempfile
import unittest
from pathlib import Path

from academy_core import ReleaseBundleWriter, ReleaseExecutionService


class ReleaseExecutionTests(unittest.TestCase):
    def prepare_root(self, root: Path):
        (root / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n', encoding="utf-8")
        for name in ReleaseExecutionService.DEFAULT_BUNDLE_FILES:
            (root / name).write_text(f"{name} release 1.1.0", encoding="utf-8")

    def test_execution_generates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_root(root)
            win_exe = root / "app.exe"
            win_exe.write_bytes(b"exe")
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            result = ReleaseExecutionService().execute(
                root=root,
                release_dir=root / "release",
                version="1.1.0",
                commit="abc123",
                test_count=186,
                tests_passed=True,
                working_tree_clean=True,
                operator_name="Jokim",
                startup_verified=True,
                documentation_reviewed=True,
                windows_artifact=win_exe,
                android_artifact=apk,
                physical_android_device_verified=True,
                curriculum_readiness_verified=True,
            )
            self.assertTrue(result.rc_ready)
            self.assertTrue(result.rollback_passed)
            self.assertTrue(result.bundle_verified)
            self.assertEqual(result.acceptance_decision, "approved")
            self.assertTrue((root / "release" / "release_manifest.json").exists())

    def test_execution_rejects_failed_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_root(root)
            result = ReleaseExecutionService().evaluate_only(
                root=root,
                version="1.1.0",
                commit="abc123",
                test_count=186,
                tests_passed=False,
                working_tree_clean=True,
                operator_name="Jokim",
                startup_verified=True,
                documentation_reviewed=True,
            )
            self.assertFalse(result.rc_ready)
            self.assertEqual(result.acceptance_decision, "rejected")

    def test_execution_pending_when_operator_evidence_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_root(root)
            result = ReleaseExecutionService().evaluate_only(
                root=root,
                version="1.1.0",
                commit="abc123",
                test_count=186,
                tests_passed=True,
                working_tree_clean=True,
                operator_name="Jokim",
                startup_verified=False,
                documentation_reviewed=True,
            )
            self.assertEqual(result.acceptance_decision, "pending")

    def test_summary_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.prepare_root(root)
            win_exe = root / "app.exe"
            win_exe.write_bytes(b"exe")
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            ReleaseExecutionService().execute(
                root=root,
                release_dir=root / "release",
                version="1.1.0",
                commit="abc123",
                test_count=186,
                tests_passed=True,
                working_tree_clean=True,
                operator_name="Jokim",
                startup_verified=True,
                documentation_reviewed=True,
                windows_artifact=win_exe,
                android_artifact=apk,
                physical_android_device_verified=True,
                curriculum_readiness_verified=True,
            )
            payload = json.loads(
                (root / "release" / "release_execution_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(payload["version"], "1.1.0")

    def test_bundle_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("alpha", encoding="utf-8")
            output = root / "bundle.zip"
            writer = ReleaseBundleWriter()
            writer.write(root=root, output_zip=output, relative_files=("a.txt",))
            self.assertTrue(writer.verify_readable(output))

    def test_bundle_writer_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                ReleaseBundleWriter().write(
                    root=root,
                    output_zip=root / "bundle.zip",
                    relative_files=("missing.txt",),
                )

    def test_bundle_writer_detects_corrupt_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.zip"
            path.write_bytes(b"not a zip")
            self.assertFalse(ReleaseBundleWriter().verify_readable(path))


if __name__ == "__main__":
    unittest.main()
