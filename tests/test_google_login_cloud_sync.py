from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cloud_auth_session import FirebaseSessionManager, OAuthTokenStore
from cloud_sync import (
    FirebaseAuthREST,
    FirebaseConfig,
    FirebaseSession,
    FirestoreREST,
    ConversationSyncService,
)
from conversation_store import ConversationStore, DeviceIdentityStore


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, *, headers=None, payload=None, timeout=12.0):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "payload": payload,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0) if self.responses else {}


def fs_doc(**fields):
    encoded = {}
    for key, value in fields.items():
        if isinstance(value, bool):
            encoded[key] = {"booleanValue": value}
        elif isinstance(value, int):
            encoded[key] = {"integerValue": str(value)}
        else:
            encoded[key] = {"stringValue": str(value)}
    return {"fields": encoded}


class GoogleCloudConfigTests(unittest.TestCase):
    def test_live_sync_requires_firebase_and_google_client_secret(self):
        config = FirebaseConfig(
            project_id="p",
            web_api_key="key",
            google_client_id="client.apps.googleusercontent.com",
            google_client_secret="",
        )
        self.assertFalse(config.live_sync_ready)
        self.assertIn("GYANVERSE_GOOGLE_CLIENT_SECRET", config.missing_live_sync_fields())

    def test_redirect_url_uses_configured_oauth_port(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(
            os.environ,
            {"GYANVERSE_OAUTH_PORT": "8666"},
            clear=True,
        ):
            self.assertEqual(
                FirebaseConfig.from_env().oauth_redirect_url,
                "http://localhost:8666/oauth_callback",
            )


class EncryptedOAuthTokenTests(unittest.TestCase):
    def test_missing_secret_disables_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.enc"
            store = OAuthTokenStore(path, secret="")
            self.assertFalse(store.save('{"access_token":"secret"}'))
            self.assertFalse(path.exists())
            self.assertEqual(store.load(), "")

    def test_enabled_store_encrypts_and_restores_without_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token.enc"
            encrypt = lambda value, secret: f"enc:{secret}:{value[::-1]}"
            decrypt = lambda value, secret: value.split(":", 2)[2][::-1]
            store = OAuthTokenStore(
                path,
                secret="local-passphrase",
                encrypt_fn=encrypt,
                decrypt_fn=decrypt,
            )
            token = '{"access_token":"google-token"}'
            self.assertTrue(store.save(token))
            self.assertNotIn("google-token", path.read_text(encoding="utf-8"))
            self.assertEqual(store.load(), token)
            store.clear()
            self.assertFalse(path.exists())


class FirebaseSessionManagerTests(unittest.TestCase):
    def test_expired_session_refreshes_before_sync(self):
        class Auth:
            def refresh(self, refresh_token):
                self.seen = refresh_token
                return FirebaseSession(
                    uid="uid-1",
                    id_token="new-id",
                    refresh_token="new-refresh",
                    expires_at=9999999999,
                )

        auth = Auth()
        manager = FirebaseSessionManager(FirebaseConfig("p", "key"), auth=auth)
        manager.session = FirebaseSession(
            uid="uid-1",
            id_token="old",
            refresh_token="refresh-me",
            expires_at=1,
        )
        self.assertEqual(manager.current().id_token, "new-id")
        self.assertEqual(auth.seen, "refresh-me")


class FirestorePullTests(unittest.TestCase):
    def setUp(self):
        self.config = FirebaseConfig("project", "key")
        self.session = FirebaseSession(
            uid="uid-1",
            id_token="firebase-id",
            refresh_token="refresh",
            expires_at=9999999999,
        )

    def test_list_documents_uses_firebase_bearer_and_decodes_fields(self):
        http = FakeHttp(
            [
                {
                    "documents": [
                        fs_doc(owner_id="uid-1", conversation_id="c1", standard=7)
                    ]
                }
            ]
        )
        documents = FirestoreREST(self.config, http=http).list_documents(
            session=self.session,
            collection_path="users/uid-1/conversations",
        )
        self.assertEqual(documents[0]["standard"], 7)
        self.assertEqual(http.calls[0]["headers"]["Authorization"], "Bearer firebase-id")
        self.assertIn("users/uid-1/conversations", http.calls[0]["url"])

    def test_pull_merges_remote_conversation_and_message_without_outbox(self):
        conversation = fs_doc(
            conversation_id="c-remote",
            owner_id="uid-1",
            ownerId="uid-1",
            student_id="student-1",
            device_id="device-phone",
            title="Phone chat",
            board="CBSE",
            standard=8,
            subject="Science",
            chapter="Light",
            created_at="2026-08-01T10:00:00+00:00",
            updated_at="2026-08-01T10:01:00+00:00",
            revision=2,
            deleted_at="",
        )
        message = fs_doc(
            message_id="m-remote",
            conversation_id="c-remote",
            owner_id="uid-1",
            ownerId="uid-1",
            student_id="student-1",
            device_id="device-phone",
            role="student",
            text="Why is the sky blue?",
            language="English",
            board="CBSE",
            standard=8,
            subject="Science",
            chapter="Light",
            backend="",
            created_at="2026-08-01T10:01:00+00:00",
            updated_at="2026-08-01T10:01:00+00:00",
            revision=1,
            deleted_at="",
        )
        http = FakeHttp([{"documents": [conversation]}, {"documents": [message]}])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = DeviceIdentityStore(root / "device.json").load_or_create()
            store = ConversationStore(root / "chat.db", device_id=device.device_id)
            result = ConversationSyncService(
                store, FirestoreREST(self.config, http=http)
            ).pull_remote(session=self.session)
            self.assertEqual(result.conversations_merged, 1)
            self.assertEqual(result.messages_merged, 1)
            self.assertEqual(
                store.list_messages(conversation_id="c-remote", owner_id="uid-1")[0].text,
                "Why is the sky blue?",
            )
            self.assertEqual(store.pending_outbox_count(owner_id="uid-1"), 0)

    def test_newer_pending_local_record_is_not_overwritten_by_older_remote(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            device = DeviceIdentityStore(root / "device.json").load_or_create()
            store = ConversationStore(root / "chat.db", device_id=device.device_id)
            local = store.create_conversation(
                owner_id="uid-1",
                student_id="student-1",
                board="GSEB",
                standard=7,
                title="Local newest",
                conversation_id="same-id",
            )
            remote = {
                **local.__dict__,
                "title": "Remote old",
                "ownerId": "uid-1",
                "updated_at": "2000-01-01T00:00:00+00:00",
                "revision": 1,
            }
            self.assertFalse(store.merge_remote_conversation(owner_id="uid-1", payload=remote))
            self.assertEqual(
                store.list_conversations(owner_id="uid-1")[0].title,
                "Local newest",
            )


class GoogleCloudUIContractTests(unittest.TestCase):
    def test_ui_has_visible_login_logout_sync_and_owner_switch(self):
        root = Path(__file__).resolve().parents[1]
        ui = (root / "gyanverse_ui.py").read_text(encoding="utf-8")
        self.assertIn("GoogleOAuthProvider", ui)
        self.assertIn('"Sign in with Google"', ui)
        self.assertIn('"Sync now"', ui)
        self.assertIn('"Sign out"', ui)
        self.assertIn("page.on_login = google_login_completed", ui)
        self.assertIn("page.on_logout = google_logout_completed", ui)
        self.assertIn('await page.login(google_provider, scope=["openid", "email", "profile"])', ui)
        self.assertIn("page.run_task(page.login, google_provider, saved_token=saved_oauth_token)", ui)
        self.assertIn("claim_local_owner", ui)
        self.assertIn("current_owner_id", ui)
        self.assertNotIn("service_account", ui.lower())

    def test_launchers_use_fixed_oauth_port(self):
        root = Path(__file__).resolve().parents[1]
        main = (root / "main.py").read_text(encoding="utf-8")
        hidden = (root / "scripts" / "launch_gyanverse_hidden.pyw").read_text(
            encoding="utf-8"
        )
        self.assertIn('GYANVERSE_OAUTH_PORT", "8550"', main)
        self.assertIn("port=oauth_port", main)
        self.assertIn("port=oauth_port", hidden)

    def test_rules_validate_owner_and_document_ids(self):
        root = Path(__file__).resolve().parents[1]
        rules = (root / "firebase" / "firestore.rules").read_text(encoding="utf-8")
        self.assertIn("request.auth.uid == uid", rules)
        self.assertIn("request.resource.data.conversation_id == conversationId", rules)
        self.assertIn("request.resource.data.message_id == messageId", rules)
        self.assertIn("allow read, write: if false", rules)


if __name__ == "__main__":
    unittest.main()
