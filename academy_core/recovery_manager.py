from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Tuple

from .stabilization_models import BackupManifest


class RecoveryManager:
    """Deterministic backup/restore boundary for serializable application data."""

    def create_backup(
        self,
        records_by_student: Mapping[str, Mapping[str, Any]],
        *,
        encrypted: bool = False,
    ) -> Tuple[BackupManifest, str]:
        normalized = {
            student_id: deepcopy(dict(records))
            for student_id, records in sorted(records_by_student.items())
        }
        payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        backup_id = "backup_" + hashlib.sha256(
            f"{created_at}|{checksum}".encode("utf-8")
        ).hexdigest()[:16]
        record_count = sum(len(records) for records in normalized.values())
        manifest = BackupManifest(
            backup_id=backup_id,
            created_at=created_at,
            student_ids=tuple(normalized),
            record_count=record_count,
            checksum=checksum,
            encrypted=encrypted,
        )
        envelope = json.dumps(
            {"manifest": manifest.__dict__, "payload": normalized},
            ensure_ascii=False,
            sort_keys=True,
        )
        return manifest, envelope

    def restore(self, envelope: str) -> Dict[str, Dict[str, Any]]:
        parsed = json.loads(envelope)
        manifest = parsed["manifest"]
        payload = parsed["payload"]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        actual_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if actual_checksum != manifest["checksum"]:
            raise ValueError("Backup checksum mismatch")
        if tuple(sorted(payload)) != tuple(manifest["student_ids"]):
            raise ValueError("Backup student manifest mismatch")
        return {student_id: dict(records) for student_id, records in payload.items()}
