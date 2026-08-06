from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

import cloud_sync
from conversation_store import SyncOutboxRecord


class CloudSyncCleanupTests(unittest.TestCase):
    def test_uploaded_payload_reports_synced_without_mutating_outbox_payload(self) -> None:
        event = SyncOutboxRecord(
            event_id="outbox-cleanup-test",
            owner_id="owner-cleanup-test",
            entity_type="message",
            entity_id="message-cleanup-test",
            operation="upsert",
            payload_json=json.dumps(
                {
                    "owner_id": "owner-cleanup-test",
                    "conversation_id": "conversation-cleanup-test",
                    "message_id": "message-cleanup-test",
                    "device_id": "device-cleanup-test",
                    "sync_state": "pending",
                }
            ),
            created_at="2026-08-07T00:00:00+00:00",
            attempt_count=0,
            next_attempt_at="",
            last_error="",
        )

        service_type = next(
            value
            for value in vars(cloud_sync).values()
            if isinstance(value, type) and "_event_document" in value.__dict__
        )

        path, payload = service_type._event_document(
            event,
            owner_id="owner-cleanup-test",
        )

        self.assertEqual(
            "users/owner-cleanup-test/conversations/"
            "conversation-cleanup-test/messages/message-cleanup-test",
            path,
        )
        self.assertEqual("synced", payload["sync_state"])
        self.assertEqual("pending", event.payload["sync_state"])

    def test_logout_resets_stale_tutor_status_before_rebuilding_view(self) -> None:
        ui_path = Path(__file__).resolve().parents[1] / "gyanverse_ui.py"
        tree = ast.parse(ui_path.read_text(encoding="utf-8"))

        logout = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "complete_logout"
        )

        resets_ready = any(
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "status_text"
                and target.attr == "value"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value == "Ready"
            for node in ast.walk(logout)
        )

        self.assertTrue(resets_ready)


if __name__ == "__main__":
    unittest.main()
