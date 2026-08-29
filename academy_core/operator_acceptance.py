from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from .release_candidate_models import (
    AcceptanceDecision,
    OperatorAcceptanceItem,
    OperatorAcceptanceRecord,
)


class OperatorAcceptanceService:
    REQUIRED_KEYS = (
        "tests_passed",
        "rc_audit_passed",
        "rollback_verified",
        "documentation_reviewed",
        "startup_verified",
        "working_tree_clean",
        "windows_packaging_accepted",
        "android_packaging_accepted",
        "physical_device_accepted",
        "curriculum_readiness_accepted",
    )

    def evaluate(
        self,
        *,
        operator_name: str,
        version: str,
        commit: str,
        items: Iterable[OperatorAcceptanceItem],
        notes: str = "",
        required_keys: Sequence[str] | None = None,
    ) -> OperatorAcceptanceRecord:
        if not operator_name.strip():
            raise ValueError("operator_name is required")
        target_keys = tuple(required_keys if required_keys is not None else self.REQUIRED_KEYS)
        supplied = {item.key: item for item in items}
        missing = [key for key in target_keys if key not in supplied]

        has_rejection = any(
            item.key in {"tests_passed", "rc_audit_passed", "working_tree_clean"} and not item.accepted
            for item in supplied.values()
        )

        if has_rejection:
            decision = AcceptanceDecision.REJECTED
        elif missing or any(not item.accepted for item in supplied.values()):
            decision = AcceptanceDecision.PENDING
        else:
            decision = AcceptanceDecision.APPROVED

        return OperatorAcceptanceRecord(
            operator_name=operator_name,
            version=version,
            commit=commit,
            decision=decision,
            items=tuple(supplied[key] for key in sorted(supplied)),
            signed_at=datetime.now(timezone.utc).isoformat(),
            notes=(
                notes
                if not missing
                else f"{notes} Missing required acceptance items: {', '.join(missing)}".strip()
            ),
        )
