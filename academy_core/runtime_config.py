from __future__ import annotations

import os
from dataclasses import replace
from typing import Mapping

from .deployment_models import EnvironmentName, RuntimeConfig


class RuntimeConfigManager:
    PREFIX = "GYANVERSE_"

    DEFAULTS = {
        EnvironmentName.DEVELOPMENT: RuntimeConfig(
            environment=EnvironmentName.DEVELOPMENT,
            app_name="GyanVerse Academy",
            version="0.9.0",
            debug=True,
            log_level="DEBUG",
            host="127.0.0.1",
            port=8000,
            data_dir="data",
            metrics_enabled=True,
            health_enabled=True,
            allowed_origins=("http://localhost:3000",),
            required_secret_names=(),
            feature_flags={"parent_reports": True, "exam_readiness": True},
        ),
        EnvironmentName.STAGING: RuntimeConfig(
            environment=EnvironmentName.STAGING,
            app_name="GyanVerse Academy",
            version="0.9.0",
            debug=False,
            log_level="INFO",
            host="0.0.0.0",
            port=8000,
            data_dir="/var/lib/gyanverse",
            metrics_enabled=True,
            health_enabled=True,
            allowed_origins=("https://staging.gyanverse.example",),
            required_secret_names=("GYANVERSE_APP_SECRET",),
            feature_flags={"parent_reports": True, "exam_readiness": True},
        ),
        EnvironmentName.PRODUCTION: RuntimeConfig(
            environment=EnvironmentName.PRODUCTION,
            app_name="GyanVerse Academy",
            version="0.9.0",
            debug=False,
            log_level="INFO",
            host="0.0.0.0",
            port=8000,
            data_dir="/var/lib/gyanverse",
            metrics_enabled=True,
            health_enabled=True,
            allowed_origins=("https://app.gyanverse.example",),
            required_secret_names=("GYANVERSE_APP_SECRET",),
            feature_flags={"parent_reports": True, "exam_readiness": True},
        ),
    }

    def load(
        self,
        environment: EnvironmentName | str | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> RuntimeConfig:
        source = dict(os.environ if environ is None else environ)
        env_value = environment or source.get(
            f"{self.PREFIX}ENVIRONMENT", EnvironmentName.DEVELOPMENT.value
        )
        env_name = (
            env_value
            if isinstance(env_value, EnvironmentName)
            else EnvironmentName(str(env_value).lower())
        )
        config = self.DEFAULTS[env_name]

        allowed_origins = source.get(f"{self.PREFIX}ALLOWED_ORIGINS")
        required_secrets = source.get(f"{self.PREFIX}REQUIRED_SECRETS")
        feature_flags = dict(config.feature_flags)

        for key, value in source.items():
            prefix = f"{self.PREFIX}FEATURE_"
            if key.startswith(prefix):
                feature = key[len(prefix):].lower()
                feature_flags[feature] = self._bool(value)

        config = replace(
            config,
            version=source.get(f"{self.PREFIX}VERSION", config.version),
            debug=self._bool(source.get(f"{self.PREFIX}DEBUG", str(config.debug))),
            log_level=source.get(f"{self.PREFIX}LOG_LEVEL", config.log_level).upper(),
            host=source.get(f"{self.PREFIX}HOST", config.host),
            port=int(source.get(f"{self.PREFIX}PORT", config.port)),
            data_dir=source.get(f"{self.PREFIX}DATA_DIR", config.data_dir),
            metrics_enabled=self._bool(
                source.get(f"{self.PREFIX}METRICS_ENABLED", str(config.metrics_enabled))
            ),
            health_enabled=self._bool(
                source.get(f"{self.PREFIX}HEALTH_ENABLED", str(config.health_enabled))
            ),
            allowed_origins=(
                self._csv(allowed_origins) if allowed_origins is not None else config.allowed_origins
            ),
            required_secret_names=(
                self._csv(required_secrets)
                if required_secrets is not None
                else config.required_secret_names
            ),
            feature_flags=feature_flags,
        )
        config.validate()
        return config

    @staticmethod
    def _bool(value: str) -> bool:
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Invalid boolean: {value}")

    @staticmethod
    def _csv(value: str) -> tuple[str, ...]:
        return tuple(item.strip() for item in value.split(",") if item.strip())
