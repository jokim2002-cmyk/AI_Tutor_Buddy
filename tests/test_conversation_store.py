from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_sync import (
    CloudSyncError,
    ConversationSyncService,
    FirebaseAuthREST,
    FirebaseConfig,
    FirebaseSession,
    FirestoreREST,
    JsonHttpClient,
)
from phase11_ai import GyanVerseAIService
from conversation_store import (
    ConversationStore,
    ConversationStoreError,
    DeviceIdentityStore,
    SYNC_FAILED,
    SYNC_PENDING,
    suggest_conversation_title,
)


class FakeHttp(JsonHttpClient):
    def __init__(self, responses=None, error=None):
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def request(self, method, url, *, headers=None, payload=None, timeout=12.0):
        self.calls.append(
            {"method": method, "url": url, "headers": dict(headers or {}), "payload": payload}
        )
        if self.error:
            raise self.error
        return self.responses.pop(0) if self.responses else {}


class ConversationStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        identity = DeviceIdentityStore(self.root / "device_identity.json").load_or_create()
        self.identity = identity
        self.store = ConversationStore(
            self.root / "conversations.db", device_id=identity.device_id
        )
        self.owner = identity.local_owner_id

    def tearDown(self):
        self.tmp.cleanup()

    def create_conversation(self):
        return self.store.get_or_create_active(
            owner_id=self.owner,
            student_id="student-1",
            board="GSEB",
            standard=7,
            subject="Science",
            chapter="Heat",
        )

    def test_device_identity_is_stable_and_non_secret(self):
        second = DeviceIdentityStore(self.root / "device_identity.json").load_or_create()
        self.assertEqual(second, self.identity)
        self.assertTrue(second.local_owner_id.startswith("local:device-"))

    def test_conversation_and_messages_persist_across_reopen(self):
        conversation = self.create_conversation()
        self.store.append_message(
            conversation_id=conversation.conversation_id,
            owner_id=self.owner,
            student_id="student-1",
            role="student",
            text="Why does ice float?",
            language="English",
            board="GSEB",
            standard=7,
            subject="Science",
            chapter="Water",
        )
        tutor = self.store.append_message(
            conversation_id=conversation.conversation_id,
            owner_id=self.owner,
            student_id="student-1",
            role="tutor",
            text="Ice is less dense than liquid water.",
            language="English",
            board="GSEB",
            standard=7,
            subject="Science",
            chapter="Water",
            backend="Gemini stream",
        )
        reopened = ConversationStore(
            self.root / "conversations.db", device_id=self.identity.device_id
        )
        messages = reopened.list_messages(
            conversation_id=conversation.conversation_id, owner_id=self.owner
        )
        self.assertEqual([item.role for item in messages], ["student", "tutor"])
        self.assertEqual(messages[-1], tutor)
        self.assertEqual(messages[-1].backend, "Gemini stream")

    def test_first_student_message_sets_title(self):
        conversation = self.create_conversation()
        self.store.append_message(
            conversation_id=conversation.conversation_id,
            owner_id=self.owner,
            student_id="student-1",
            role="student",
            text="Explain photosynthesis in simple words",
            language="English",
            board="CBSE",
            standard=6,
            subject="Science",
        )
        latest = self.store.list_conversations(owner_id=self.owner)[0]
        self.assertEqual(latest.title, "Explain photosynthesis in simple words")
        self.assertEqual(latest.board, "CBSE")
        self.assertEqual(latest.standard, 6)

    def test_owner_isolation_blocks_cross_owner_access(self):
        conversation = self.create_conversation()
        with self.assertRaises(ConversationStoreError):
            self.store.append_message(
                conversation_id=conversation.conversation_id,
                owner_id="firebase:other-user",
                student_id="student-1",
                role="student",
                text="Unauthorized",
                language="English",
                board="GSEB",
                standard=7,
            )
        self.assertEqual(
            self.store.list_messages(
                conversation_id=conversation.conversation_id,
                owner_id="firebase:other-user",
            ),
            [],
        )

    def test_local_writes_create_durable_outbox(self):
        conversation = self.create_conversation()
        self.store.append_message(
            conversation_id=conversation.conversation_id,
            owner_id=self.owner,
            student_id="student-1",
            role="student",
            text="Hello",
            language="English",
            board="GSEB",
            standard=7,
        )
        events = self.store.pending_outbox(owner_id=self.owner)
        self.assertGreaterEqual(len(events), 3)
        self.assertTrue(all(item.payload["owner_id"] == self.owner for item in events))

    def test_claim_local_owner_rekeys_and_requeues_all_data(self):
        conversation = self.create_conversation()
        self.store.append_message(
            conversation_id=conversation.conversation_id,
            owner_id=self.owner,
            student_id="student-1",
            role="student",
            text="Keep this chat",
            language="English",
            board="GSEB",
            standard=7,
        )
        claimed = self.store.claim_local_owner(
            local_owner_id=self.owner, authenticated_owner_id="firebase-uid-1"
        )
        self.assertEqual(claimed, 1)
        conversations = self.store.list_conversations(owner_id="firebase-uid-1")
        self.assertEqual(len(conversations), 1)
        messages = self.store.list_messages(
            conversation_id=conversation.conversation_id, owner_id="firebase-uid-1"
        )
        self.assertEqual(len(messages), 1)
        self.assertTrue(self.store.pending_outbox(owner_id="firebase-uid-1"))
        self.assertFalse(self.store.pending_outbox(owner_id=self.owner))

    def test_failed_outbox_remains_retryable(self):
        self.create_conversation()
        event = self.store.pending_outbox(owner_id=self.owner)[0]
        self.store.mark_outbox_failed(event.event_id, error_category="network")
        retry = self.store.pending_outbox(owner_id=self.owner)[0]
        self.assertEqual(retry.attempt_count, 1)
        self.assertEqual(retry.last_error, "network")

    def test_title_sanitization_is_bounded(self):
        self.assertEqual(suggest_conversation_title("  hello\nworld "), "hello world")
        self.assertLessEqual(len(suggest_conversation_title("x" * 500)), 80)

    def test_ai_restores_only_bounded_complete_turns(self):
        service = GyanVerseAIService(api_key="", max_history_turns=2)
        service.restore_session_history(
            [("q1", "a1"), ("q2", "a2"), ("q3", "a3"), ("", "ignored")]
        )
        self.assertEqual(service._history, [("q2", "a2"), ("q3", "a3")])


class FirebaseFoundationTests(unittest.TestCase):
    def setUp(self):
        self.config = FirebaseConfig(
            project_id="gyanverse-test",
            web_api_key="public-web-api-key",
            google_client_id="client.apps.googleusercontent.com",
        )

    def test_google_id_token_exchange_uses_firebase_endpoint(self):
        http = FakeHttp(
            responses=[
                {
                    "localId": "uid-1",
                    "idToken": "firebase-id-token",
                    "refreshToken": "refresh-token",
                    "expiresIn": "3600",
                    "email": "parent@example.com",
                    "displayName": "Parent",
                }
            ]
        )
        session = FirebaseAuthREST(self.config, http=http).exchange_google_id_token(
            "google-id-token"
        )
        self.assertEqual(session.uid, "uid-1")
        self.assertEqual(session.email, "parent@example.com")
        self.assertIn("accounts:signInWithIdp", http.calls[0]["url"])
        post_body = http.calls[0]["payload"]["postBody"]
        self.assertIn("providerId=google.com", post_body)
        self.assertNotIn("firebase-id-token", json.dumps(http.calls[0]["payload"]))

    def test_google_access_token_exchange_is_supported_for_flet(self):
        http = FakeHttp(
            responses=[
                {
                    "localId": "uid-2",
                    "idToken": "firebase-id-token",
                    "refreshToken": "refresh-token",
                    "expiresIn": "3600",
                }
            ]
        )
        session = FirebaseAuthREST(self.config, http=http).exchange_google_access_token(
            "google-access-token"
        )
        self.assertEqual(session.uid, "uid-2")
        post_body = http.calls[0]["payload"]["postBody"]
        self.assertIn("access_token=google-access-token", post_body)
        self.assertIn("providerId=google.com", post_body)

    def test_missing_firebase_config_fails_without_network(self):
        with self.assertRaises(CloudSyncError):
            FirebaseAuthREST(FirebaseConfig("", "")).exchange_google_id_token("token")

    def test_firestore_uses_firebase_bearer_token_and_owner_path(self):
        http = FakeHttp([{}])
        client = FirestoreREST(self.config, http=http)
        session = FirebaseSession(
            uid="uid-1",
            id_token="firebase-id-token",
            refresh_token="refresh",
            expires_at=9999999999,
        )
        client.upsert_document(
            session=session,
            document_path="users/uid-1/conversations/c1",
            data={"ownerId": "uid-1", "title": "Chat"},
        )
        call = http.calls[0]
        self.assertEqual(call["headers"]["Authorization"], "Bearer firebase-id-token")
        self.assertIn("/users/uid-1/conversations/c1", call["url"])
        self.assertEqual(call["payload"]["fields"]["ownerId"], {"stringValue": "uid-1"})

    def test_sync_pushes_outbox_to_owner_isolated_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = DeviceIdentityStore(root / "device.json").load_or_create()
            store = ConversationStore(root / "chat.db", device_id=identity.device_id)
            local = identity.local_owner_id
            conversation = store.create_conversation(
                owner_id=local,
                student_id="student-1",
                board="GSEB",
                standard=7,
            )
            store.append_message(
                conversation_id=conversation.conversation_id,
                owner_id=local,
                student_id="student-1",
                role="student",
                text="Hello",
                language="English",
                board="GSEB",
                standard=7,
            )
            store.claim_local_owner(local_owner_id=local, authenticated_owner_id="uid-1")
            http = FakeHttp([{} for _ in range(10)])
            firestore = FirestoreREST(self.config, http=http)
            result = ConversationSyncService(store, firestore).push_pending(
                session=FirebaseSession(
                    uid="uid-1",
                    id_token="firebase-token",
                    refresh_token="refresh",
                    expires_at=9999999999,
                )
            )
            self.assertGreaterEqual(result.synced, 2)
            self.assertEqual(result.failed, 0)
            self.assertTrue(
                all("/users/uid-1/conversations/" in call["url"] for call in http.calls)
            )
            self.assertFalse(store.pending_outbox(owner_id="uid-1"))

    def test_sync_failure_stays_in_outbox_and_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identity = DeviceIdentityStore(root / "device.json").load_or_create()
            store = ConversationStore(root / "chat.db", device_id=identity.device_id)
            store.create_conversation(
                owner_id="uid-1", student_id="student-1", board="GSEB", standard=7
            )
            firestore = FirestoreREST(
                self.config,
                http=FakeHttp(error=CloudSyncError("secret details", category="network", retryable=True)),
            )
            result = ConversationSyncService(store, firestore).push_pending(
                session=FirebaseSession(
                    uid="uid-1",
                    id_token="firebase-token",
                    refresh_token="refresh",
                    expires_at=9999999999,
                )
            )
            self.assertEqual(result.failed, 1)
            event = store.pending_outbox(owner_id="uid-1")[0]
            self.assertEqual(event.last_error, "network")
            self.assertNotIn("secret details", event.last_error)


class ConversationUIIntegrationContractTests(unittest.TestCase):
    def test_ui_persists_and_restores_chat_without_embedding_tokens(self):
        root = Path(__file__).resolve().parents[1]
        ui = (root / "gyanverse_ui.py").read_text(encoding="utf-8")
        ai = (root / "phase11_ai.py").read_text(encoding="utf-8")
        self.assertIn("ConversationStore", ui)
        self.assertIn('DATA_DIR / "conversations.db"', ui)
        self.assertIn("conversation_store.append_message", ui)
        self.assertIn("conversation_store.list_messages", ui)
        self.assertIn("ai_service.restore_session_history(restored_turns)", ui)
        self.assertIn("def restore_session_history", ai)
        self.assertNotIn("service_account", ui.lower())
        self.assertNotIn("firebase-id-token", ui)

    def test_cloud_templates_are_owner_isolated_and_secret_free(self):
        root = Path(__file__).resolve().parents[1]
        rules = (root / "firebase" / "firestore.rules").read_text(encoding="utf-8")
        config = (root / "firebase" / "firebase_config.env.example").read_text(encoding="utf-8")
        self.assertIn("request.auth.uid == uid", rules)
        self.assertIn("request.resource.data.ownerId == uid", rules)
        self.assertIn("allow read, write: if false", rules)
        self.assertNotIn("PRIVATE KEY", config)


if __name__ == "__main__":
    unittest.main()
