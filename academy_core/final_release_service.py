from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .documentation_audit import DocumentationAuditor
from .freeze_policy import ReleaseFreezePolicy
from .operator_acceptance import OperatorAcceptanceService
from .rc_audit import ReleaseCandidateAuditor
from .release_packager import ReleasePackager
from .rollback_drill import RollbackDrill


class FinalReleaseService:
    def __init__(self) -> None:
        self.auditor = ReleaseCandidateAuditor()
        self.packager = ReleasePackager()
        self.freeze = ReleaseFreezePolicy()
        self.docs = DocumentationAuditor()
        self.rollback = RollbackDrill()
        self.acceptance = OperatorAcceptanceService()

    def preflight(
        self,
        *,
        root: Path,
        version: str,
        commit: str,
        test_count: int,
        tests_passed: bool,
        working_tree_clean: bool,
    ):
        return self.auditor.audit(
            root=root,
            version=version,
            commit=commit,
            test_count=test_count,
            tests_passed=tests_passed,
            working_tree_clean=working_tree_clean,
        )
