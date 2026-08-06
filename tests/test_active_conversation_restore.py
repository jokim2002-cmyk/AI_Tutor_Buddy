from __future__ import annotations

import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from conversation_store import ConversationStore


class ActiveConversationRestoreTests(unittest.TestCase):
    def test_message_conversation_is_preferred_over_newer_empty_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "conversations.db"
            store = ConversationStore(
                database_path,
                device_id="device_restore_test",
            )

            filled = store.create_conversation(
                owner_id="owner_restore_test",
                student_id="student_restore_test",
                board="GSEB",
                standard=7,
                subject="Mathematics",
                title="Conversation with messages",
            )
            empty = store.create_conversation(
                owner_id="owner_restore_test",
                student_id="student_restore_test",
                board="GSEB",
                standard=7,
                subject="Mathematics",
                title="Newer empty conversation",
            )

            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute(
                    "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
                    ("2026-08-07T03:00:00+00:00", filled.conversation_id),
                )
                connection.execute(
                    "UPDATE conversations SET updated_at=? WHERE conversation_id=?",
                    ("2026-08-07T04:00:00+00:00", empty.conversation_id),
                )
                connection.execute(
                    "INSERT INTO messages("
                    "message_id, conversation_id, owner_id, student_id, "
                    "device_id, role, text, language, board, standard, "
                    "subject, chapter, backend, created_at, updated_at, "
                    "revision, sync_state, deleted_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        "message_restore_test",
                        filled.conversation_id,
                        "owner_restore_test",
                        "student_restore_test",
                        "device_restore_test",
                        "student",
                        "restore marker",
                        "English",
                        "GSEB",
                        7,
                        "Mathematics",
                        "",
                        "local",
                        "2026-08-07T03:00:00+00:00",
                        "2026-08-07T03:00:00+00:00",
                        1,
                        "synced",
                        "",
                    ),
                )
                connection.commit()

            active = store.get_or_create_active(
                owner_id="owner_restore_test",
                student_id="student_restore_test",
                board="GSEB",
                standard=7,
                subject="Mathematics",
            )

            self.assertEqual(filled.conversation_id, active.conversation_id)


if __name__ == "__main__":
    unittest.main()
