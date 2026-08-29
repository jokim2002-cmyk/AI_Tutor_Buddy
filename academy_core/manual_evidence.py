from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict


def classify_artifact(path: str | Path) -> str:
    artifact_path = Path(path)
    if not artifact_path.exists():
        return "missing"
    suffix = artifact_path.suffix.lower()
    if suffix == ".exe":
        return "windows_app_artifact"
    if suffix in {".apk", ".aab"}:
        return "android_app_artifact"
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(artifact_path, "r") as zf:
                names = zf.namelist()
                non_docs = [
                    name
                    for name in names
                    if not name.lower().endswith((".md", ".json", ".txt", ".freeze", "/"))
                ]
                if not non_docs:
                    return "documentation_bundle"
                return "generic_zip"
        except zipfile.BadZipFile:
            return "invalid"
    return "unknown"


@dataclass(frozen=True)
class ManualAcceptanceEvidence:
    schema_version: int
    version: str
    platform: str
    artifact_identifier: str
    artifact_sha256: str
    test_datetime: str
    operator_identity: str
    checklist_results: Dict[str, str]
    notes: str
    provenance: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def create_template(cls, version: str, platform: str = "cross_platform") -> "ManualAcceptanceEvidence":
        return cls(
            schema_version=1,
            version=version,
            platform=platform,
            artifact_identifier="",
            artifact_sha256="",
            test_datetime="",
            operator_identity="",
            checklist_results={
                "packaging_verification": "pending",
                "startup_smoke_test": "pending",
                "manual_workflow_test": "pending",
                "physical_device_test": "pending",
            },
            notes="Template evidence file. Operator must complete evidence before approval.",
            provenance="",
        )

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        *,
        target_version: str,
        artifact_path: Path | None = None,
    ) -> "ManualAcceptanceEvidence":
        schema_version = int(data.get("schema_version", 1))
        version = str(data.get("version", "")).strip()
        if version != target_version:
            raise ValueError(
                f"Manual evidence version '{version}' does not match target version '{target_version}'"
            )
        platform = str(data.get("platform", "")).strip().lower()
        if platform not in {"windows", "android", "emulator", "cross_platform"}:
            raise ValueError(f"Unsupported platform in manual evidence: '{platform}'")

        artifact_id = str(data.get("artifact_identifier", "")).strip()
        artifact_hash = str(data.get("artifact_sha256", "")).strip().lower()

        if artifact_path and artifact_path.exists():
            actual_hash = hashlib.sha256(artifact_path.read_bytes()).hexdigest().lower()
            if artifact_hash and artifact_hash != actual_hash:
                raise ValueError(
                    f"Manual evidence SHA-256 '{artifact_hash}' does not match actual artifact SHA-256 '{actual_hash}'"
                )

        test_dt = str(data.get("test_datetime", "")).strip()
        operator = str(data.get("operator_identity", "")).strip()
        if not operator:
            raise ValueError("Operator identity is required in manual evidence")

        checklist = data.get("checklist_results", {})
        if not isinstance(checklist, dict):
            raise ValueError("checklist_results must be a dictionary")

        cleaned_checklist = {}
        for k, v in checklist.items():
            status_val = str(v).lower().strip()
            if status_val not in {"pass", "fail", "pending"}:
                raise ValueError(
                    f"Invalid checklist status '{v}' for item '{k}'. Allowed: pass, fail, pending"
                )
            cleaned_checklist[k] = status_val

        notes = str(data.get("notes", "")).strip()
        provenance = str(data.get("provenance", "")).strip()

        return cls(
            schema_version=schema_version,
            version=version,
            platform=platform,
            artifact_identifier=artifact_id,
            artifact_sha256=artifact_hash,
            test_datetime=test_dt,
            operator_identity=operator,
            checklist_results=cleaned_checklist,
            notes=notes,
            provenance=provenance,
        )

    def is_passing(self) -> bool:
        if not self.operator_identity or not self.test_datetime:
            return False
        if not self.checklist_results:
            return False
        return all(status == "pass" for status in self.checklist_results.values())
