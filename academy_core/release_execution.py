from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence

from .manual_evidence import ManualAcceptanceEvidence
from .operator_acceptance import OperatorAcceptanceService
from .rc_audit import ReleaseCandidateAuditor
from .release_candidate_models import OperatorAcceptanceItem
from .release_packager import ReleasePackager
from .rollback_drill import RollbackDrill
from .version_utils import get_project_version


@dataclass(frozen=True)
class ReleaseExecutionResult:
    version: str
    commit: str
    generated_at: str
    rc_ready: bool
    rollback_passed: bool
    bundle_verified: bool
    acceptance_decision: str
    release_dir: str
    artifact_paths: tuple[str, ...]

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class ReleaseExecutionService:
    DEFAULT_BUNDLE_FILES = (
        "README.md",
        "ROADMAP.md",
        "VISION.md",
        "GYANVERSE_CONSTITUTION.md",
        "PRODUCTION_PLATFORM_DEPLOYMENT.md",
        "PERFORMANCE_SAFETY_STABILIZATION.md",
        "FINAL_RELEASE_CANDIDATE.md",
        "RELEASE_NOTES.md",
    )

    def __init__(self) -> None:
        self.auditor = ReleaseCandidateAuditor()
        self.packager = ReleasePackager()
        self.rollback = RollbackDrill()
        self.acceptance = OperatorAcceptanceService()

    def evaluate_only(
        self,
        *,
        root: Path,
        version: str | None = None,
        commit: str | None = None,
        test_count: int = 0,
        tests_passed: bool = False,
        working_tree_clean: bool = True,
        operator_name: str = "System Auditor",
        startup_verified: bool = False,
        documentation_reviewed: bool = False,
        windows_artifact: Path | str | None = None,
        android_artifact: Path | str | None = None,
        physical_android_device_verified: bool = False,
        curriculum_readiness_verified: bool = False,
        manual_evidence: ManualAcceptanceEvidence | None = None,
    ) -> ReleaseExecutionResult:
        res_version = version or get_project_version(root)
        res_commit = commit or git_commit(root)

        audit = self.auditor.audit(
            root=root,
            version=res_version,
            commit=res_commit,
            test_count=test_count,
            tests_passed=tests_passed,
            working_tree_clean=working_tree_clean,
            startup_verified=startup_verified,
            documentation_reviewed=documentation_reviewed,
            windows_artifact=windows_artifact,
            android_artifact=android_artifact,
            physical_android_device_verified=physical_android_device_verified,
            curriculum_readiness_verified=curriculum_readiness_verified,
            manual_evidence=manual_evidence,
        )

        rollback = self.rollback.run({"release_probe": {"version": res_version, "commit": res_commit}})

        rc_audit_accepted = (not audit.blocking_failures)
        acceptance_items = (
            OperatorAcceptanceItem("tests_passed", "Full regression passed", True, tests_passed and test_count > 0, f"{test_count} tests"),
            OperatorAcceptanceItem("rc_audit_passed", "RC audit passed", True, rc_audit_accepted, audit.summary),
            OperatorAcceptanceItem("rollback_verified", "Rollback drill verified", True, rollback.passed, rollback.drill_id),
            OperatorAcceptanceItem("documentation_reviewed", "Documentation reviewed", True, documentation_reviewed),
            OperatorAcceptanceItem("startup_verified", "Startup verified", True, startup_verified),
            OperatorAcceptanceItem("working_tree_clean", "Working tree clean", True, working_tree_clean),
            OperatorAcceptanceItem("windows_packaging_accepted", "Windows packaging accepted", True, windows_artifact is not None),
            OperatorAcceptanceItem("android_packaging_accepted", "Android packaging accepted", True, android_artifact is not None),
            OperatorAcceptanceItem("physical_device_accepted", "Physical device test accepted", True, physical_android_device_verified),
            OperatorAcceptanceItem("curriculum_readiness_accepted", "Curriculum readiness accepted", True, curriculum_readiness_verified),
        )

        acceptance = self.acceptance.evaluate(
            operator_name=operator_name,
            version=res_version,
            commit=res_commit,
            items=acceptance_items,
            notes="Evaluated by dry-run release service.",
        )

        return ReleaseExecutionResult(
            version=res_version,
            commit=res_commit,
            generated_at=datetime.now(timezone.utc).isoformat(),
            rc_ready=audit.release_candidate_ready,
            rollback_passed=rollback.passed,
            bundle_verified=False,
            acceptance_decision=acceptance.decision.value,
            release_dir="",
            artifact_paths=(),
        )

    def execute(
        self,
        *,
        root: Path,
        release_dir: Path,
        version: str | None = None,
        commit: str | None = None,
        test_count: int = 0,
        tests_passed: bool = False,
        working_tree_clean: bool = True,
        operator_name: str = "System Auditor",
        startup_verified: bool = False,
        documentation_reviewed: bool = False,
        windows_artifact: Path | str | None = None,
        android_artifact: Path | str | None = None,
        physical_android_device_verified: bool = False,
        curriculum_readiness_verified: bool = False,
        manual_evidence: ManualAcceptanceEvidence | None = None,
        bundle_files: Sequence[str] | None = None,
        dry_run: bool = False,
    ) -> ReleaseExecutionResult:
        res_version = version or get_project_version(root)
        res_commit = commit or git_commit(root)

        evaluation = self.evaluate_only(
            root=root,
            version=res_version,
            commit=res_commit,
            test_count=test_count,
            tests_passed=tests_passed,
            working_tree_clean=working_tree_clean,
            operator_name=operator_name,
            startup_verified=startup_verified,
            documentation_reviewed=documentation_reviewed,
            windows_artifact=windows_artifact,
            android_artifact=android_artifact,
            physical_android_device_verified=physical_android_device_verified,
            curriculum_readiness_verified=curriculum_readiness_verified,
            manual_evidence=manual_evidence,
        )

        if dry_run:
            return evaluation

        if not evaluation.rc_ready or evaluation.acceptance_decision != "approved":
            raise RuntimeError(
                f"Release generation refused: Release candidate gates are incomplete or not approved (decision: {evaluation.acceptance_decision})."
            )

        release_dir.mkdir(parents=True, exist_ok=True)

        audit = self.auditor.audit(
            root=root,
            version=res_version,
            commit=res_commit,
            test_count=test_count,
            tests_passed=tests_passed,
            working_tree_clean=working_tree_clean,
            startup_verified=startup_verified,
            documentation_reviewed=documentation_reviewed,
            windows_artifact=windows_artifact,
            android_artifact=android_artifact,
            physical_android_device_verified=physical_android_device_verified,
            curriculum_readiness_verified=curriculum_readiness_verified,
            manual_evidence=manual_evidence,
        )
        audit_path = release_dir / "rc_audit.json"
        audit_path.write_text(
            json.dumps(audit.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        rollback = self.rollback.run({"release_probe": {"version": res_version, "commit": res_commit}})
        rollback_path = release_dir / "rollback_drill.json"
        rollback_path.write_text(
            json.dumps(asdict(rollback), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        selected = tuple(bundle_files or self.DEFAULT_BUNDLE_FILES)
        manifest = self.packager.build_manifest(
            root=root,
            relative_files=selected,
            version=res_version,
            commit=res_commit,
            build_id=f"gyanverse-{res_version}-{res_commit[:12]}",
            test_count=test_count,
            test_status="passed" if tests_passed else "failed",
            frozen=True,
        )
        manifest_path = release_dir / "release_manifest.json"
        manifest_path.write_text(
            json.dumps(asdict(manifest), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        bundle_verified = self.packager.verify(root, manifest)

        rc_audit_accepted = (not audit.blocking_failures)
        acceptance_items = (
            OperatorAcceptanceItem("tests_passed", "Full regression passed", True, tests_passed and test_count > 0, f"{test_count} tests"),
            OperatorAcceptanceItem("rc_audit_passed", "RC audit passed", True, rc_audit_accepted, audit.summary),
            OperatorAcceptanceItem("rollback_verified", "Rollback drill verified", True, rollback.passed, rollback.drill_id),
            OperatorAcceptanceItem("documentation_reviewed", "Documentation reviewed", True, documentation_reviewed),
            OperatorAcceptanceItem("startup_verified", "Startup verified", True, startup_verified),
            OperatorAcceptanceItem("working_tree_clean", "Working tree clean", True, working_tree_clean),
            OperatorAcceptanceItem("windows_packaging_accepted", "Windows packaging accepted", True, windows_artifact is not None),
            OperatorAcceptanceItem("android_packaging_accepted", "Android packaging accepted", True, android_artifact is not None),
            OperatorAcceptanceItem("physical_device_accepted", "Physical device test accepted", True, physical_android_device_verified),
            OperatorAcceptanceItem("curriculum_readiness_accepted", "Curriculum readiness accepted", True, curriculum_readiness_verified),
        )
        acceptance = self.acceptance.evaluate(
            operator_name=operator_name,
            version=res_version,
            commit=res_commit,
            items=acceptance_items,
            notes="Generated by final release execution workflow.",
        )
        acceptance_path = release_dir / "operator_acceptance.json"
        acceptance_path.write_text(
            json.dumps(acceptance.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        freeze_path = release_dir / "RELEASE_FREEZE"
        freeze_path.write_text(
            f"version={res_version}\ncommit={res_commit}\nfrozen_at={datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )

        summary_path = release_dir / "release_execution_summary.json"
        result = ReleaseExecutionResult(
            version=res_version,
            commit=res_commit,
            generated_at=datetime.now(timezone.utc).isoformat(),
            rc_ready=audit.release_candidate_ready,
            rollback_passed=rollback.passed,
            bundle_verified=bundle_verified,
            acceptance_decision=acceptance.decision.value,
            release_dir=str(release_dir),
            artifact_paths=tuple(
                str(path)
                for path in (
                    audit_path,
                    rollback_path,
                    manifest_path,
                    acceptance_path,
                    freeze_path,
                    summary_path,
                )
            ),
        )
        summary_path.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return result


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown_commit"


def git_working_tree_clean(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return not result.stdout.strip()
    except Exception:
        return False
