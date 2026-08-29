from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Tuple


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    PENDING = "pending"
    NOT_APPLICABLE = "not_applicable"


class AcceptanceDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING = "pending"


@dataclass(frozen=True)
class ReleaseGateResult:
    gate: str
    status: GateStatus
    details: str
    blocking: bool = True

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class ReleaseCandidateAudit:
    version: str
    commit: str
    generated_at: str
    gates: Tuple[ReleaseGateResult, ...]
    blocking_failures: Tuple[str, ...]
    pending_gates: Tuple[str, ...]
    warnings: Tuple[str, ...]
    release_candidate_ready: bool
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["gates"] = [gate.to_dict() for gate in self.gates]
        return data


@dataclass(frozen=True)
class ReleaseBundleManifest:
    version: str
    commit: str
    build_id: str
    generated_at: str
    files: Tuple[str, ...]
    checksums: Dict[str, str]
    bundle_checksum: str
    test_count: int
    test_status: str
    frozen: bool
    schema_version: int = 1


@dataclass(frozen=True)
class RollbackDrillResult:
    drill_id: str
    started_at: str
    completed_at: str
    backup_verified: bool
    restore_verified: bool
    checksum_verified: bool
    passed: bool
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class OperatorAcceptanceItem:
    key: str
    label: str
    required: bool
    accepted: bool
    evidence: str = ""


@dataclass(frozen=True)
class OperatorAcceptanceRecord:
    operator_name: str
    version: str
    commit: str
    decision: AcceptanceDecision
    items: Tuple[OperatorAcceptanceItem, ...]
    signed_at: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        return data
