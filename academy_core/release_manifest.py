from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .deployment_models import EnvironmentName, ReleaseManifest, RuntimeConfig


SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?(?:\+(?P<build>[0-9A-Za-z.-]+))?$"
)


class SemanticVersion:
    def __init__(self, value: str) -> None:
        match = SEMVER.match(value)
        if not match:
            raise ValueError(f"Invalid semantic version: {value}")
        self.value = value
        self.major = int(match.group("major"))
        self.minor = int(match.group("minor"))
        self.patch = int(match.group("patch"))
        self.prerelease = match.group("pre")
        self.build = match.group("build")

    def bump_patch(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch + 1}"

    def bump_minor(self) -> str:
        return f"{self.major}.{self.minor + 1}.0"

    def bump_major(self) -> str:
        return f"{self.major + 1}.0.0"

    def __str__(self) -> str:
        return self.value


class ReleaseManifestBuilder:
    def build(
        self,
        config: RuntimeConfig,
        *,
        commit: str,
        artifact_names: Iterable[str],
        test_count: int,
        test_status: str,
    ) -> ReleaseManifest:
        if not commit.strip():
            raise ValueError("commit is required")
        if test_count < 0:
            raise ValueError("test_count cannot be negative")
        SemanticVersion(config.version)
        config_payload = json.dumps(
            {
                "environment": config.environment.value,
                "app_name": config.app_name,
                "version": config.version,
                "debug": config.debug,
                "log_level": config.log_level,
                "host": config.host,
                "port": config.port,
                "data_dir": config.data_dir,
                "metrics_enabled": config.metrics_enabled,
                "health_enabled": config.health_enabled,
                "allowed_origins": config.allowed_origins,
                "required_secret_names": config.required_secret_names,
                "feature_flags": dict(config.feature_flags),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        fingerprint = hashlib.sha256(config_payload.encode("utf-8")).hexdigest()
        generated_at = datetime.now(timezone.utc).isoformat()
        build_id = "build_" + hashlib.sha256(
            f"{commit}|{config.version}|{generated_at}".encode("utf-8")
        ).hexdigest()[:16]
        return ReleaseManifest(
            app_name=config.app_name,
            version=config.version,
            environment=config.environment,
            commit=commit,
            build_id=build_id,
            generated_at=generated_at,
            artifact_names=tuple(sorted(set(artifact_names))),
            config_fingerprint=fingerprint,
            test_count=test_count,
            test_status=test_status,
        )
