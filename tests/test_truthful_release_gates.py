import json
import tempfile
import unittest
from pathlib import Path

from academy_core import (
    AcceptanceDecision,
    BoardSyllabus,
    GateStatus,
    ManualAcceptanceEvidence,
    OperatorAcceptanceItem,
    OperatorAcceptanceService,
    ReleaseCandidateAuditor,
    ReleaseExecutionService,
    SyllabusRepository,
    classify_artifact,
    get_project_version,
)
from scripts.run_final_release import run_real_regression


class TruthfulReleaseGatesTests(unittest.TestCase):
    def test_version_read_from_pyproject(self):
        root = Path(__file__).resolve().parents[1]
        version = get_project_version(root)
        self.assertEqual(version, "1.1.0")

    def test_invalid_missing_pyproject_version_fails_safely(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with self.assertRaises(ValueError):
                get_project_version(tmp_path)

            (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                get_project_version(tmp_path)

    def test_real_passing_regression_produces_pass_and_nonzero_dynamic_count(self):
        import os
        if os.environ.get("_REAL_REGRESSION_RUNNING") == "1":
            self.skipTest("Prevent nested regression recursion.")
        root = Path(__file__).resolve().parents[1]
        result = run_real_regression(root)
        self.assertTrue(result.passed)
        self.assertGreater(result.test_count, 0)
        self.assertIn("Ran", result.output_snippet)

    def test_failed_mocked_regression_produces_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("readme", encoding="utf-8")
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=50,
                tests_passed=False,
                working_tree_clean=True,
            )
            self.assertIn("tests", audit.blocking_failures)
            self.assertFalse(audit.release_candidate_ready)

    def test_zero_discovered_tests_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=0,
                tests_passed=True,
                working_tree_clean=True,
            )
            self.assertIn("tests", audit.blocking_failures)
            self.assertFalse(audit.release_candidate_ready)

    def test_missing_startup_evidence_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                startup_verified=False,
            )
            startup_gate = next(g for g in audit.gates if g.gate == "startup_smoke_verification")
            self.assertEqual(startup_gate.status, GateStatus.PENDING)

    def test_missing_documentation_review_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                documentation_reviewed=False,
            )
            doc_gate = next(g for g in audit.gates if g.gate == "documentation_review")
            self.assertEqual(doc_gate.status, GateStatus.PENDING)

    def test_missing_windows_artifact_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                windows_artifact=None,
            )
            win_gate = next(g for g in audit.gates if g.gate == "windows_packaging")
            self.assertEqual(win_gate.status, GateStatus.PENDING)

    def test_missing_android_artifact_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                android_artifact=None,
            )
            apk_gate = next(g for g in audit.gates if g.gate == "android_packaging")
            self.assertEqual(apk_gate.status, GateStatus.PENDING)

    def test_missing_physical_device_evidence_remains_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                physical_android_device_verified=False,
            )
            dev_gate = next(g for g in audit.gates if g.gate == "physical_android_device")
            self.assertEqual(dev_gate.status, GateStatus.PENDING)

    def test_mandatory_pending_gate_prevents_approved(self):
        service = OperatorAcceptanceService()
        items = [
            OperatorAcceptanceItem("tests_passed", "tests", True, True),
            OperatorAcceptanceItem("working_tree_clean", "clean", True, True),
            OperatorAcceptanceItem("startup_verified", "startup", True, False),  # pending/unaccepted
        ]
        record = service.evaluate(
            operator_name="Auditor",
            version="1.1.0",
            commit="abc",
            items=items,
        )
        self.assertEqual(record.decision, AcceptanceDecision.PENDING)

    def test_mandatory_fail_gate_prevents_approved(self):
        service = OperatorAcceptanceService()
        items = [
            OperatorAcceptanceItem("tests_passed", "tests", True, False),  # failed
            OperatorAcceptanceItem("working_tree_clean", "clean", True, True),
        ]
        record = service.evaluate(
            operator_name="Auditor",
            version="1.1.0",
            commit="abc",
            items=items,
        )
        self.assertEqual(record.decision, AcceptanceDecision.REJECTED)

    def test_all_mandatory_mocked_pass_gates_produce_approval(self):
        service = OperatorAcceptanceService()
        items = [
            OperatorAcceptanceItem(key, key, True, True)
            for key in OperatorAcceptanceService.REQUIRED_KEYS
        ]
        record = service.evaluate(
            operator_name="Auditor",
            version="1.1.0",
            commit="abc",
            items=items,
        )
        self.assertEqual(record.decision, AcceptanceDecision.APPROVED)

    def test_documentation_only_zip_cannot_satisfy_exe_or_apk_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            doc_zip = Path(tmp) / "docs.zip"
            import zipfile
            with zipfile.ZipFile(doc_zip, "w") as zf:
                zf.writestr("README.md", "docs only")
                zf.writestr("release.json", "{}")

            self.assertEqual(classify_artifact(doc_zip), "documentation_bundle")

            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=Path(tmp),
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                windows_artifact=doc_zip,
                android_artifact=doc_zip,
            )
            win_gate = next(g for g in audit.gates if g.gate == "windows_packaging")
            apk_gate = next(g for g in audit.gates if g.gate == "android_packaging")
            self.assertEqual(win_gate.status, GateStatus.FAIL)
            self.assertEqual(apk_gate.status, GateStatus.FAIL)

    def test_artifact_sha256_calculated_and_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "app.exe"
            art.write_bytes(b"exe-bytes-content")
            import hashlib
            correct_hash = hashlib.sha256(b"exe-bytes-content").hexdigest()

            evidence_data = {
                "schema_version": 1,
                "version": "1.1.0",
                "platform": "windows",
                "artifact_identifier": "app.exe",
                "artifact_sha256": correct_hash,
                "test_datetime": "2026-08-06T00:00:00Z",
                "operator_identity": "Operator",
                "checklist_results": {"test": "pass"},
                "notes": "",
                "provenance": "",
            }
            ev = ManualAcceptanceEvidence.from_dict(evidence_data, target_version="1.1.0", artifact_path=art)
            self.assertEqual(ev.artifact_sha256, correct_hash)

            bad_data = dict(evidence_data)
            bad_data["artifact_sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
            with self.assertRaises(ValueError):
                ManualAcceptanceEvidence.from_dict(bad_data, target_version="1.1.0", artifact_path=art)

    def test_wrong_version_manual_evidence_rejected(self):
        evidence_data = {
            "schema_version": 1,
            "version": "1.0.0",  # wrong version
            "platform": "windows",
            "artifact_identifier": "app.exe",
            "artifact_sha256": "",
            "test_datetime": "2026-08-06T00:00:00Z",
            "operator_identity": "Operator",
            "checklist_results": {"test": "pass"},
            "notes": "",
            "provenance": "",
        }
        with self.assertRaises(ValueError):
            ManualAcceptanceEvidence.from_dict(evidence_data, target_version="1.1.0")

    def test_wrong_artifact_manual_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "wrong.exe"
            art.write_bytes(b"different-bytes")
            evidence_data = {
                "schema_version": 1,
                "version": "1.1.0",
                "platform": "windows",
                "artifact_identifier": "wrong.exe",
                "artifact_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "test_datetime": "2026-08-06T00:00:00Z",
                "operator_identity": "Operator",
                "checklist_results": {"test": "pass"},
                "notes": "",
                "provenance": "",
            }
            with self.assertRaises(ValueError):
                ManualAcceptanceEvidence.from_dict(evidence_data, target_version="1.1.0", artifact_path=art)

    def test_templates_never_default_to_pass(self):
        tmpl = ManualAcceptanceEvidence.create_template(version="1.1.0")
        self.assertFalse(tmpl.is_passing())
        self.assertIn("pending", tmpl.checklist_results.values())

    def test_evaluation_only_mode_does_not_generate_final_release_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n', encoding="utf-8")
            for doc in ReleaseCandidateAuditor.REQUIRED_DOCS:
                (root / doc).write_text("doc content", encoding="utf-8")
            rel_dir = root / "release"
            service = ReleaseExecutionService()
            result = service.evaluate_only(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=200,
                tests_passed=True,
                working_tree_clean=True,
            )
            self.assertEqual(result.acceptance_decision, "pending")
            self.assertFalse(rel_dir.exists())

    def test_explicit_generation_refuses_incomplete_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n', encoding="utf-8")
            rel_dir = root / "release"
            service = ReleaseExecutionService()
            with self.assertRaises(RuntimeError):
                service.execute(
                    root=root,
                    release_dir=rel_dir,
                    version="1.1.0",
                    commit="abc",
                    test_count=200,
                    tests_passed=True,
                    working_tree_clean=True,
                    dry_run=False,
                )

    def test_historical_evidence_is_not_silently_overwritten(self):
        root = Path(__file__).resolve().parents[1]
        release_dir = root / "release"
        historical_file = release_dir / "operator_acceptance.json"
        if historical_file.exists():
            content_before = historical_file.read_text(encoding="utf-8")
            service = ReleaseExecutionService()
            service.evaluate_only(root=root)
            content_after = historical_file.read_text(encoding="utf-8")
            self.assertEqual(content_before, content_after)

    def test_curriculum_readiness_not_inferred_from_repository_class(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = SyllabusRepository(root / "syllabus")
            self.assertEqual(len(repo.all()), 0)

            auditor = ReleaseCandidateAuditor()
            audit = auditor.audit(
                root=root,
                version="1.1.0",
                commit="abc",
                test_count=100,
                tests_passed=True,
                working_tree_clean=True,
                curriculum_readiness_verified=False,
            )
            curr_gate = next(g for g in audit.gates if g.gate == "curriculum_readiness")
            self.assertEqual(curr_gate.status, GateStatus.PENDING)

    def test_gseb_and_cbse_syllabus_coverage_remains_board_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = SyllabusRepository(Path(tmp))
            gseb_payload = {
                "schema_version": 1,
                "board": "GSEB",
                "medium": "Gujarati",
                "standard": 7,
                "subject": "Math",
                "textbook": "GSEB Math",
                "source": {"title": "GSEB Source", "official": False, "publisher": "P", "edition": "2026"},
                "chapters": [{"chapter_id": "c1", "number": "1", "title": "Ch1", "topics": [{"topic_id": "t1", "title": "T1", "explanation": "x", "content_origin": "teacher_authored"}]}],
            }
            cbse_payload = {
                "schema_version": 1,
                "board": "CBSE",
                "medium": "English",
                "standard": 7,
                "subject": "Math",
                "textbook": "CBSE Math",
                "source": {"title": "CBSE Source", "official": False, "publisher": "P", "edition": "2026"},
                "chapters": [{"chapter_id": "c1", "number": "1", "title": "Ch1", "topics": [{"topic_id": "t1", "title": "T1", "explanation": "y", "content_origin": "teacher_authored"}]}],
            }
            repo.install_payload(gseb_payload)
            repo.install_payload(cbse_payload)

            gseb_cov = repo.overall_coverage(board="GSEB")
            cbse_cov = repo.overall_coverage(board="CBSE")

            self.assertEqual(gseb_cov["syllabi"], 1)
            self.assertEqual(cbse_cov["syllabi"], 1)
            self.assertEqual(gseb_cov["topics"], 1)
            self.assertEqual(cbse_cov["topics"], 1)


if __name__ == "__main__":
    unittest.main()
