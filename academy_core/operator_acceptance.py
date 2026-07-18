from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

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
    )

    def evaluate(
        self,
        *,
        operator_name: str,
        version: str,
        commit: str,
        items: Iterable[OperatorAcceptanceItem],
        notes: str = "",
    ) -> OperatorAcceptanceRecord:
        if not operator_name.strip():
            raise ValueError("operator_name is required")
        supplied = {item.key: item for item in items}
        missing = [key for key in self.REQUIRED_KEYS if key not in supplied]

        if missing:
            decision = AcceptanceDecision.PENDING
        elif any(
            item.required and not item.accepted
            for item in supplied.values()
        ):
            decision = AcceptanceDecision.REJECTED
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
                else f"{notes} Missing required items: {', '.join(missing)}".strip()
            ),
        )
