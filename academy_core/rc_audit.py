from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .release_candidate_models import (
    GateStatus,
    ReleaseCandidateAudit,
    ReleaseGateResult,
)


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
    ) -> ReleaseCandidateAudit:
        docs = tuple(required_docs or self.REQUIRED_DOCS)
        gates = []

        gates.append(
            ReleaseGateResult(
                "tests",
                GateStatus.PASS if tests_passed else GateStatus.FAIL,
                f"{test_count} tests passed" if tests_passed else "Regression tests failed",
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
        gates.append(
            ReleaseGateResult(
                "required_documentation",
                GateStatus.PASS if not missing_docs else GateStatus.FAIL,
                "All required documents present"
                if not missing_docs
                else f"Missing: {', '.join(missing_docs)}",
            )
        )
        gates.append(
            ReleaseGateResult(
                "version",
                GateStatus.PASS if version.strip() else GateStatus.FAIL,
                f"Version: {version}" if version.strip() else "Version missing",
            )
        )
        gates.append(
            ReleaseGateResult(
                "commit",
                GateStatus.PASS if commit.strip() else GateStatus.FAIL,
                f"Commit: {commit}" if commit.strip() else "Commit missing",
            )
        )

        blocking_failures = tuple(
            gate.gate for gate in gates if gate.blocking and gate.status == GateStatus.FAIL
        )
        warnings = tuple(
            gate.details for gate in gates if gate.status == GateStatus.WARN
        )
        ready = not blocking_failures
        return ReleaseCandidateAudit(
            version=version,
            commit=commit,
            generated_at=datetime.now(timezone.utc).isoformat(),
            gates=tuple(gates),
            blocking_failures=blocking_failures,
            warnings=warnings,
            release_candidate_ready=ready,
            summary=(
                "All release-candidate audit gates passed."
                if ready
                else "Release candidate blocked by one or more required gates."
            ),
        )
