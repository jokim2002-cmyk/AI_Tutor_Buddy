from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from .manual_evidence import ManualAcceptanceEvidence, classify_artifact
from .release_candidate_models import (
    GateStatus,
    ReleaseCandidateAudit,
    ReleaseGateResult,
)
from .version_utils import get_project_version


class ReleaseCandidateAuditor:
    REQUIRED_DOCS = (
        "README.md",
        "ROADMAP.md",
        "VISION.md",
        "GYANVERSE_CONSTITUTION.md",
        "PRODUCTION_PLATFORM_DEPLOYMENT.md",
        "PERFORMANCE_SAFETY_STABILIZATION.md",
    )

    def audit(
        self,
        *,
        root: Path,
        version: str,
        commit: str,
        test_count: int,
        tests_passed: bool,
        working_tree_clean: bool,
        required_docs: Sequence[str] | None = None,
        startup_verified: bool = False,
        documentation_reviewed: bool = False,
        windows_artifact: Path | str | None = None,
        android_artifact: Path | str | None = None,
        physical_windows_device_verified: bool | None = None,
        physical_android_device_verified: bool = False,
        curriculum_readiness_verified: bool = False,
        manual_evidence: ManualAcceptanceEvidence | None = None,
    ) -> ReleaseCandidateAudit:
        docs = tuple(required_docs or self.REQUIRED_DOCS)
        gates: list[ReleaseGateResult] = []

        try:
            expected_version = get_project_version(root)
            version_match = (version.strip() == expected_version)
        except Exception:
            version_match = bool(version.strip())

        gates.append(
            ReleaseGateResult(
                "version",
                GateStatus.PASS if version_match else GateStatus.FAIL,
                f"Version: {version}" if version_match else f"Version mismatch or missing (expected {expected_version if 'expected_version' in locals() else 'valid'})",
            )
        )

        gates.append(
            ReleaseGateResult(
                "commit",
                GateStatus.PASS if commit.strip() else GateStatus.FAIL,
                f"Commit: {commit}" if commit.strip() else "Commit missing",
            )
        )

        gates.append(
            ReleaseGateResult(
                "working_tree",
                GateStatus.PASS if working_tree_clean else GateStatus.FAIL,
                "Working tree clean" if working_tree_clean else "Uncommitted changes detected",
            )
        )

        missing_docs = [name for name in docs if not (root / name).exists()]
        empty_docs = [name for name in docs if (root / name).exists() and (root / name).stat().st_size == 0]
        doc_status = GateStatus.PASS if (not missing_docs and not empty_docs) else GateStatus.FAIL
        doc_details = "All required documents present and non-empty"
        if missing_docs:
            doc_details = f"Missing: {', '.join(missing_docs)}"
        elif empty_docs:
            doc_details = f"Empty: {', '.join(empty_docs)}"
        gates.append(ReleaseGateResult("required_documentation", doc_status, doc_details))

        if not tests_passed:
            test_status = GateStatus.FAIL
            test_details = f"Regression failed ({test_count} tests run)"
        elif test_count <= 0:
            test_status = GateStatus.FAIL
            test_details = "Zero tests discovered (suite must be non-empty)"
        else:
            test_status = GateStatus.PASS
            test_details = f"{test_count} tests passed"
        gates.append(ReleaseGateResult("tests", test_status, test_details))

        startup_pass = startup_verified or (manual_evidence and manual_evidence.checklist_results.get("startup_smoke_test") == "pass")
        gates.append(
            ReleaseGateResult(
                "startup_smoke_verification",
                GateStatus.PASS if startup_pass else GateStatus.PENDING,
                "Startup smoke test verified" if startup_pass else "Startup smoke test pending explicit verification",
            )
        )

        docs_pass = documentation_reviewed or (manual_evidence and manual_evidence.checklist_results.get("documentation_reviewed") == "pass")
        gates.append(
            ReleaseGateResult(
                "documentation_review",
                GateStatus.PASS if docs_pass else GateStatus.PENDING,
                "Documentation review completed" if docs_pass else "Documentation review pending operator review",
            )
        )

        if windows_artifact:
            win_class = classify_artifact(windows_artifact)
            if win_class == "windows_app_artifact":
                win_status = GateStatus.PASS
                win_details = f"Windows EXE artifact verified: {Path(windows_artifact).name}"
            else:
                win_status = GateStatus.FAIL
                win_details = f"Invalid Windows artifact type: {win_class} (expected .exe)"
        else:
            win_status = GateStatus.PENDING
            win_details = "Windows packaged-build (.exe) acceptance pending"
        gates.append(ReleaseGateResult("windows_packaging", win_status, win_details))

        if android_artifact:
            apk_class = classify_artifact(android_artifact)
            if apk_class == "android_app_artifact":
                apk_status = GateStatus.PASS
                apk_details = f"Android APK artifact verified: {Path(android_artifact).name}"
            else:
                apk_status = GateStatus.FAIL
                apk_details = f"Invalid Android artifact type: {apk_class} (expected .apk)"
        else:
            apk_status = GateStatus.PENDING
            apk_details = "Android packaged-build (.apk) acceptance pending"
        gates.append(ReleaseGateResult("android_packaging", apk_status, apk_details))

        if physical_windows_device_verified is False:
            win_dev_status = GateStatus.FAIL
            win_dev_details = "Physical Windows device testing failed"
        elif physical_windows_device_verified is True:
            win_dev_status = GateStatus.PASS
            win_dev_details = "Physical Windows device testing verified"
        else:
            win_dev_status = GateStatus.NOT_APPLICABLE
            win_dev_details = "Physical Windows device acceptance optional / handled via desktop packaging"
        gates.append(ReleaseGateResult("physical_windows_device", win_dev_status, win_dev_details, blocking=False))

        phys_android_pass = physical_android_device_verified or (
            manual_evidence and manual_evidence.checklist_results.get("physical_device_test") == "pass"
        )
        gates.append(
            ReleaseGateResult(
                "physical_android_device",
                GateStatus.PASS if phys_android_pass else GateStatus.PENDING,
                "Physical Android device testing verified" if phys_android_pass else "Physical Android device testing pending real hardware acceptance",
            )
        )

        gates.append(
            ReleaseGateResult(
                "curriculum_readiness",
                GateStatus.PASS if curriculum_readiness_verified else GateStatus.PENDING,
                "Official syllabus dataset installed and verified" if curriculum_readiness_verified else "Curriculum readiness pending official textbook dataset acquisition",
            )
        )

        blocking_failures = tuple(
            gate.gate for gate in gates if gate.blocking and gate.status == GateStatus.FAIL
        )
        pending_gates = tuple(
            gate.gate for gate in gates if gate.blocking and gate.status == GateStatus.PENDING
        )
        warnings = tuple(
            gate.details for gate in gates if gate.status in (GateStatus.WARN, GateStatus.PENDING)
        )
        ready = (len(blocking_failures) == 0) and (len(pending_gates) == 0)

        summary_parts = []
        if ready:
            summary = "All release-candidate audit gates passed."
        else:
            if blocking_failures:
                summary_parts.append(f"Blocking failures: {', '.join(blocking_failures)}")
            if pending_gates:
                summary_parts.append(f"Pending gates: {', '.join(pending_gates)}")
            summary = "Release candidate incomplete/blocked. " + "; ".join(summary_parts)

        return ReleaseCandidateAudit(
            version=version,
            commit=commit,
            generated_at=datetime.now(timezone.utc).isoformat(),
            gates=tuple(gates),
            blocking_failures=blocking_failures,
            pending_gates=pending_gates,
            warnings=warnings,
            release_candidate_ready=ready,
            summary=summary,
        )
