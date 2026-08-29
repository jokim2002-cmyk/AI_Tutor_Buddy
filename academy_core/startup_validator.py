from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .deployment_models import (
    EnvironmentName,
    RuntimeConfig,
    StartupCheck,
    StartupStatus,
    StartupValidationReport,
)


class StartupValidator:
    def validate(
        self,
        config: RuntimeConfig,
        *,
        environ: Mapping[str, str] | None = None,
        create_data_dir: bool = False,
    ) -> StartupValidationReport:
        source = os.environ if environ is None else environ
        checks = []

        try:
            config.validate()
            checks.append(StartupCheck("runtime_config", True, "Configuration is valid"))
        except Exception as exc:
            checks.append(StartupCheck("runtime_config", False, str(exc)))

        missing = [name for name in config.required_secret_names if not source.get(name)]
        checks.append(
            StartupCheck(
                "required_secrets",
                not missing,
                "All required secrets are present" if not missing else f"Missing: {', '.join(missing)}",
            )
        )

        data_path = Path(config.data_dir)
        if create_data_dir:
            try:
                data_path.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        writable = data_path.exists() and data_path.is_dir() and os.access(data_path, os.W_OK)
        checks.append(
            StartupCheck(
                "data_directory",
                writable,
                f"Writable data directory: {data_path}" if writable else f"Data directory unavailable: {data_path}",
            )
        )

        prod_safe = not (
            config.environment == EnvironmentName.PRODUCTION and config.debug
        )
        checks.append(
            StartupCheck(
                "production_debug",
                prod_safe,
                "Production debug policy passed" if prod_safe else "Debug is enabled in production",
            )
        )

        blocking_failures = [check for check in checks if check.blocking and not check.passed]
        nonblocking_failures = [check for check in checks if not check.blocking and not check.passed]
        if blocking_failures:
            status = StartupStatus.BLOCKED
            summary = "Startup blocked by required validation checks."
        elif nonblocking_failures:
            status = StartupStatus.DEGRADED
            summary = "Startup permitted with degraded optional capabilities."
        else:
            status = StartupStatus.READY
            summary = "All startup validation checks passed."

        return StartupValidationReport(
            status=status,
            environment=config.environment,
            checks=tuple(checks),
            generated_at=datetime.now(timezone.utc).isoformat(),
            summary=summary,
        )
