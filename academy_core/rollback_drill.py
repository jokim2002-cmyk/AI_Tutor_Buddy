from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Mapping

from .recovery_manager import RecoveryManager
from .release_candidate_models import RollbackDrillResult


class RollbackDrill:
    def __init__(self, recovery_manager: RecoveryManager | None = None) -> None:
        self.recovery = recovery_manager or RecoveryManager()

    def run(self, records: Mapping[str, Mapping[str, object]]) -> RollbackDrillResult:
        started = datetime.now(timezone.utc).isoformat()
        notes = []
        backup_verified = restore_verified = checksum_verified = False
        try:
            manifest, envelope = self.recovery.create_backup(records)
            backup_verified = bool(manifest.checksum and manifest.backup_id)
            restored = self.recovery.restore(envelope)
            restore_verified = restored == {
                key: dict(value) for key, value in records.items()
            }
            parsed = json.loads(envelope)
            checksum_verified = parsed["manifest"]["checksum"] == manifest.checksum
            notes.append("Backup created and restored in isolated memory")
        except Exception as exc:
            notes.append(f"Rollback drill error: {type(exc).__name__}: {exc}")

        completed = datetime.now(timezone.utc).isoformat()
        passed = backup_verified and restore_verified and checksum_verified
        drill_id = "drill_" + sha256(
            f"{started}|{completed}|{passed}".encode("utf-8")
        ).hexdigest()[:16]
        return RollbackDrillResult(
            drill_id=drill_id,
            started_at=started,
            completed_at=completed,
            backup_verified=backup_verified,
            restore_verified=restore_verified,
            checksum_verified=checksum_verified,
            passed=passed,
            notes=tuple(notes),
        )
