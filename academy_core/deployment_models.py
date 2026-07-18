from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Tuple


class EnvironmentName(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class StartupStatus(str, Enum):
    READY = "ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class RuntimeConfig:
    environment: EnvironmentName
    app_name: str
    version: str
    debug: bool
    log_level: str
    host: str
    port: int
    data_dir: str
    metrics_enabled: bool
    health_enabled: bool
    allowed_origins: Tuple[str, ...] = ()
    required_secret_names: Tuple[str, ...] = ()
    feature_flags: Mapping[str, bool] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.app_name.strip():
            raise ValueError("app_name is required")
        if not self.version.strip():
            raise ValueError("version is required")
        if not self.host.strip():
            raise ValueError("host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.environment == EnvironmentName.PRODUCTION and self.debug:
            raise ValueError("debug must be disabled in production")
        if self.environment == EnvironmentName.PRODUCTION and not self.allowed_origins:
            raise ValueError("production requires allowed_origins")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("unsupported log level")


@dataclass(frozen=True)
class StartupCheck:
    name: str
    passed: bool
    details: str
    blocking: bool = True


@dataclass(frozen=True)
class StartupValidationReport:
    status: StartupStatus
    environment: EnvironmentName
    checks: Tuple[StartupCheck, ...]
    generated_at: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["environment"] = self.environment.value
        return data


@dataclass(frozen=True)
class ReleaseManifest:
    app_name: str
    version: str
    environment: EnvironmentName
    commit: str
    build_id: str
    generated_at: str
    artifact_names: Tuple[str, ...]
    config_fingerprint: str
    test_count: int
    test_status: str
    schema_version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["environment"] = self.environment.value
        return data
