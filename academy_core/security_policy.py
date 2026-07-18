from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Iterable, Tuple

from .stabilization_models import RiskLevel, SecurityFinding


class SecurityPolicy:
    SECRET_PATTERNS = (
        re.compile(r"(?i)api[_-]?key\s*=\s*['\"][^'\"]+"),
        re.compile(r"(?i)secret\s*=\s*['\"][^'\"]+"),
        re.compile(r"(?i)password\s*=\s*['\"][^'\"]+"),
        re.compile(r"sk-[A-Za-z0-9]{12,}"),
    )

    FORBIDDEN_FILES = (".env", "credentials.json", "service-account.json")

    def scan_text(self, text: str, *, source: str = "<memory>") -> Tuple[SecurityFinding, ...]:
        findings = []
        for pattern in self.SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(
                    SecurityFinding(
                        code="SECRET_EXPOSURE",
                        title="Potential hard-coded secret",
                        level=RiskLevel.CRITICAL,
                        evidence=f"Potential secret detected in {source}",
                        remediation="Remove the value, rotate the secret, and load it from an approved secret store.",
                    )
                )
        return tuple(findings)

    def scan_paths(self, paths: Iterable[Path]) -> Tuple[SecurityFinding, ...]:
        findings = []
        for path in paths:
            if path.name.lower() in self.FORBIDDEN_FILES:
                findings.append(
                    SecurityFinding(
                        code="FORBIDDEN_SECRET_FILE",
                        title="Secret-bearing file detected",
                        level=RiskLevel.HIGH,
                        evidence=str(path),
                        remediation="Keep secret files outside version control and use environment-specific secret injection.",
                    )
                )
            if path.is_file() and path.suffix.lower() in {".py", ".md", ".json", ".txt"}:
                try:
                    findings.extend(self.scan_text(path.read_text(encoding="utf-8"), source=str(path)))
                except UnicodeDecodeError:
                    continue
        return tuple(findings)

    @staticmethod
    def validate_environment(required_names: Iterable[str]) -> Tuple[SecurityFinding, ...]:
        findings = []
        for name in required_names:
            if not os.environ.get(name):
                findings.append(
                    SecurityFinding(
                        code="MISSING_SECRET",
                        title="Required secret is unavailable",
                        level=RiskLevel.MEDIUM,
                        evidence=f"Environment variable {name} is not set",
                        remediation="Configure the secret in the deployment environment before enabling the dependent service.",
                    )
                )
        return tuple(findings)
