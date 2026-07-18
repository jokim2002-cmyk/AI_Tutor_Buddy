from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Tuple


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class HealthCheckResult:
    component: str
    status: HealthStatus
    details: str
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True)
class SecurityFinding:
    code: str
    title: str
    level: RiskLevel
    evidence: str
    remediation: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["level"] = self.level.value
        return data


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    created_at: str
    student_ids: Tuple[str, ...]
    record_count: int
    checksum: str
    encrypted: bool
    version: int = 1


@dataclass(frozen=True)
class DeletionReceipt:
    request_id: str
    student_id: str
    deleted_categories: Tuple[str, ...]
    deleted_record_count: int
    completed_at: str
    irreversible: bool = True


@dataclass(frozen=True)
class StabilizationReport:
    generated_at: str
    overall_status: HealthStatus
    health_checks: Tuple[HealthCheckResult, ...]
    security_findings: Tuple[SecurityFinding, ...]
    recovery_ready: bool
    deletion_ready: bool
    rate_limit_ready: bool
    release_candidate_ready: bool
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["overall_status"] = self.overall_status.value
        data["health_checks"] = [item.to_dict() for item in self.health_checks]
        data["security_findings"] = [item.to_dict() for item in self.security_findings]
        return data
