import tempfile
import unittest
from pathlib import Path

from academy_core import (
    AcceptanceDecision,
    DocumentationAuditor,
    FinalReleaseService,
    GateStatus,
    OperatorAcceptanceItem,
    OperatorAcceptanceService,
    ReleaseCandidateAuditor,
    ReleaseFreezePolicy,
    ReleasePackager,
    RollbackDrill,
)


class FinalReleaseCandidateTests(unittest.TestCase):
    def make_docs(self, root: Path):
        for name in ReleaseCandidateAuditor.REQUIRED_DOCS:
            (root / name).write_text(f"{name} version 1.0.0", encoding="utf-8")

    def test_rc_audit_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n', encoding="utf-8")
            self.make_docs(root)
            win_exe = root / "app.exe"
            win_exe.write_bytes(b"exe")
            apk = root / "app.apk"
            apk.write_bytes(b"apk")
            audit = ReleaseCandidateAuditor().audit(
                root=root,
                version="1.1.0",
                commit="abc123",
                test_count=166,
                tests_passed=True,
                working_tree_clean=True,
                startup_verified=True,
                documentation_reviewed=True,
                windows_artifact=win_exe,
                android_artifact=apk,
                physical_android_device_verified=True,
                curriculum_readiness_verified=True,
            )
            self.assertTrue(audit.release_candidate_ready)

    def test_rc_audit_blocks_failed_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_docs(root)
            audit = ReleaseCandidateAuditor().audit(
                root=root,
                version="1.0.0",
                commit="abc123",
                test_count=166,
                tests_passed=False,
                working_tree_clean=True,
            )
            self.assertIn("tests", audit.blocking_failures)

    def test_rc_audit_blocks_dirty_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_docs(root)
            audit = ReleaseCandidateAuditor().audit(
                root=root,
                version="1.0.0",
                commit="abc123",
                test_count=166,
                tests_passed=True,
                working_tree_clean=False,
            )
            self.assertFalse(audit.release_candidate_ready)

    def test_rc_audit_blocks_missing_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = ReleaseCandidateAuditor().audit(
                root=Path(tmp),
                version="1.0.0",
                commit="abc123",
                test_count=166,
                tests_passed=True,
                working_tree_clean=True,
            )
            self.assertIn("required_documentation", audit.blocking_failures)

    def test_rc_audit_serializes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_docs(root)
            payload = ReleaseCandidateAuditor().audit(
                root=root,
                version="1.0.0",
                commit="abc123",
                test_count=166,
                tests_passed=True,
                working_tree_clean=True,
            ).to_dict()
            self.assertEqual(payload["gates"][0]["status"], "pass")

    def test_packager_manifest_and_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("alpha", encoding="utf-8")
            manifest = ReleasePackager().build_manifest(
                root=root,
                relative_files=("a.txt",),
                version="1.0.0",
                commit="abc",
                build_id="build1",
                test_count=166,
                test_status="passed",
                frozen=True,
            )
            self.assertTrue(ReleasePackager().verify(root, manifest))

    def test_packager_detects_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.txt").write_text("alpha", encoding="utf-8")
            packager = ReleasePackager()
            manifest = packager.build_manifest(
                root=root,
                relative_files=("a.txt",),
                version="1.0.0",
                commit="abc",
                build_id="build1",
                test_count=166,
                test_status="passed",
                frozen=True,
            )
            (root / "a.txt").write_text("changed", encoding="utf-8")
            self.assertFalse(packager.verify(root, manifest))

    def test_packager_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                ReleasePackager().build_manifest(
                    root=Path(tmp),
                    relative_files=("missing.txt",),
                    version="1.0.0",
                    commit="abc",
                    build_id="build1",
                    test_count=166,
                    test_status="passed",
                    frozen=True,
                )

    def test_freeze_allows_docs(self):
        decision = ReleaseFreezePolicy().evaluate(
            ("docs/release.md", "README.md"),
            frozen=True,
        )
        self.assertTrue(decision.allowed)

    def test_freeze_blocks_code(self):
        decision = ReleaseFreezePolicy().evaluate(
            ("academy_core/core.py",),
            frozen=True,
        )
        self.assertFalse(decision.allowed)

    def test_freeze_inactive_allows_anything(self):
        decision = ReleaseFreezePolicy().evaluate(
            ("academy_core/core.py",),
            frozen=False,
        )
        self.assertTrue(decision.allowed)

    def test_documentation_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = DocumentationAuditor().find_missing(
                Path(tmp), ("README.md",)
            )
            self.assertEqual(missing, ("README.md",))

    def test_documentation_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("", encoding="utf-8")
            self.assertEqual(
                DocumentationAuditor().find_empty(root, ("README.md",)),
                ("README.md",),
            )

    def test_documentation_version_mentions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("Release 1.0.0", encoding="utf-8")
            result = DocumentationAuditor().validate_version_mentions(
                root, "1.0.0", ("README.md",)
            )
            self.assertTrue(result["README.md"])

    def test_rollback_drill_passes(self):
        result = RollbackDrill().run({"s1": {"memory": [1, 2]}})
        self.assertTrue(result.passed)

    def test_acceptance_approved(self):
        items = tuple(
            OperatorAcceptanceItem(key, key, True, True, "verified")
            for key in OperatorAcceptanceService.REQUIRED_KEYS
        )
        record = OperatorAcceptanceService().evaluate(
            operator_name="Jokim",
            version="1.0.0",
            commit="abc",
            items=items,
        )
        self.assertEqual(record.decision, AcceptanceDecision.APPROVED)

    def test_acceptance_rejected(self):
        items = tuple(
            OperatorAcceptanceItem(
                key, key, True, key != "tests_passed", "checked"
            )
            for key in OperatorAcceptanceService.REQUIRED_KEYS
        )
        record = OperatorAcceptanceService().evaluate(
            operator_name="Jokim",
            version="1.0.0",
            commit="abc",
            items=items,
        )
        self.assertEqual(record.decision, AcceptanceDecision.REJECTED)

    def test_acceptance_pending_when_missing(self):
        record = OperatorAcceptanceService().evaluate(
            operator_name="Jokim",
            version="1.0.0",
            commit="abc",
            items=(),
        )
        self.assertEqual(record.decision, AcceptanceDecision.PENDING)

    def test_acceptance_requires_operator(self):
        with self.assertRaises(ValueError):
            OperatorAcceptanceService().evaluate(
                operator_name="",
                version="1.0.0",
                commit="abc",
                items=(),
            )

    def test_final_service_preflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_docs(root)
            audit = FinalReleaseService().preflight(
                root=root,
                version="1.0.0",
                commit="abc",
                test_count=166,
                tests_passed=True,
                working_tree_clean=True,
            )
            self.assertEqual(audit.gates[0].status, GateStatus.PASS)


if __name__ == "__main__":
    unittest.main()
