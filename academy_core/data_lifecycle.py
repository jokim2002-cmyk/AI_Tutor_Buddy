from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Dict, Iterable, MutableMapping, Tuple

from .stabilization_models import DeletionReceipt


class DataLifecycleManager:
    """Explicit student deletion boundary across registered data stores."""

    def delete_student(
        self,
        student_id: str,
        stores: MutableMapping[str, MutableMapping[str, object]],
    ) -> DeletionReceipt:
        if not student_id.strip():
            raise ValueError("student_id is required")

        deleted_categories = []
        deleted_count = 0

        for category, store in stores.items():
            if student_id in store:
                value = store.pop(student_id)
                deleted_categories.append(category)
                if isinstance(value, (list, tuple, set, dict)):
                    deleted_count += len(value)
                else:
                    deleted_count += 1

        completed_at = datetime.now(timezone.utc).isoformat()
        request_id = "delete_" + sha256(
            f"{student_id}|{completed_at}".encode("utf-8")
        ).hexdigest()[:16]
        return DeletionReceipt(
            request_id=request_id,
            student_id=student_id,
            deleted_categories=tuple(sorted(deleted_categories)),
            deleted_record_count=deleted_count,
            completed_at=completed_at,
        )
