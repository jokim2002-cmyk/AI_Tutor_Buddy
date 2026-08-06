from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from conversation_store import ConversationStore, SyncOutboxRecord


class CloudSyncError(RuntimeError):
    """Sanitized cloud authentication or sync failure."""

    def __init__(self, message: str, *, category: str = "cloud_error", retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class FirebaseConfig:
    project_id: str
    web_api_key: str
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_url: str = "http://localhost:8550/oauth_callback"

    @classmethod
    def from_env(cls) -> "FirebaseConfig":
        return cls(
            project_id=os.getenv("GYANVERSE_FIREBASE_PROJECT_ID", "").strip(),
            web_api_key=os.getenv("GYANVERSE_FIREBASE_WEB_API_KEY", "").strip(),
            google_client_id=os.getenv("GYANVERSE_GOOGLE_CLIENT_ID", "").strip(),
            google_client_secret=os.getenv("GYANVERSE_GOOGLE_CLIENT_SECRET", "").strip(),
            oauth_redirect_url=os.getenv(
                "GYANVERSE_GOOGLE_REDIRECT_URL",
                f"http://localhost:{os.getenv('GYANVERSE_OAUTH_PORT', '8550').strip() or '8550'}/oauth_callback",
            ).strip(),
        )

    @property
    def firebase_ready(self) -> bool:
        return bool(self.project_id and self.web_api_key)

    @property
    def google_oauth_ready(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.oauth_redirect_url
        )

    @property
    def live_sync_ready(self) -> bool:
        return self.firebase_ready and self.google_oauth_ready

    def missing_live_sync_fields(self) -> tuple[str, ...]:
        fields = []
        if not self.project_id:
            fields.append("GYANVERSE_FIREBASE_PROJECT_ID")
        if not self.web_api_key:
            fields.append("GYANVERSE_FIREBASE_WEB_API_KEY")
        if not self.google_client_id:
            fields.append("GYANVERSE_GOOGLE_CLIENT_ID")
        if not self.google_client_secret:
            fields.append("GYANVERSE_GOOGLE_CLIENT_SECRET")
        if not self.oauth_redirect_url:
            fields.append("GYANVERSE_GOOGLE_REDIRECT_URL")
        return tuple(fields)

    def validate_firebase(self) -> None:
        if not self.project_id:
            raise CloudSyncError(
                "Firebase project ID is not configured.", category="configuration"
            )
        if not self.web_api_key:
            raise CloudSyncError(
                "Firebase Web API key is not configured.", category="configuration"
            )


@dataclass(frozen=True)
class FirebaseSession:
    uid: str
    id_token: str
    refresh_token: str
    expires_at: float
    email: str = ""
    display_name: str = ""
    photo_url: str = ""

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - 60.0


@dataclass(frozen=True)
class SyncResult:
    attempted: int
    synced: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class PullResult:
    conversations_seen: int
    conversations_merged: int
    messages_seen: int
    messages_merged: int
    failed: int


class JsonHttpClient:
    """Small injectable HTTPS JSON client; never logs tokens or payloads."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
        timeout: float = 12.0,
    ) -> dict[str, Any]:
        data = None
        request_headers = {"Accept": "application/json", **dict(headers or {})}
        if payload is not None:
            data = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url=url, data=data, headers=request_headers, method=method.upper()
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            category = "permission" if exc.code in {401, 403} else "rate_limit" if exc.code == 429 else "http_error"
            raise CloudSyncError(
                f"Cloud request failed with HTTP {exc.code}.",
                category=category,
                retryable=exc.code in {408, 409, 429, 500, 502, 503, 504},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CloudSyncError(
                "Cloud request could not connect.", category="network", retryable=True
            ) from exc
        if not body:
            return {}
        try:
            value = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CloudSyncError("Cloud returned invalid JSON.", category="invalid_response") from exc
        if not isinstance(value, dict):
            raise CloudSyncError("Cloud returned an unexpected response.", category="invalid_response")
        return value


class FirebaseAuthREST:
    """Exchanges Google OAuth credentials for Firebase user tokens."""

    def __init__(self, config: FirebaseConfig, *, http: JsonHttpClient | None = None):
        self.config = config
        self.http = http or JsonHttpClient()

    def exchange_google_id_token(self, google_id_token: str) -> FirebaseSession:
        self.config.validate_firebase()
        token = str(google_id_token or "").strip()
        if not token:
            raise CloudSyncError("Google ID token is missing.", category="authentication")
        url = (
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key="
            + urllib.parse.quote(self.config.web_api_key, safe="")
        )
        response = self.http.request(
            "POST",
            url,
            payload={
                "postBody": urllib.parse.urlencode(
                    {"id_token": token, "providerId": "google.com"}
                ),
                "requestUri": self.config.oauth_redirect_url or "http://localhost",
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
        )
        return self._session_from_sign_in(response)

    def exchange_google_access_token(self, google_access_token: str) -> FirebaseSession:
        """Exchange the OAuth access token exposed by Flet Google login."""
        self.config.validate_firebase()
        token = str(google_access_token or "").strip()
        if not token:
            raise CloudSyncError("Google access token is missing.", category="authentication")
        url = (
            "https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key="
            + urllib.parse.quote(self.config.web_api_key, safe="")
        )
        response = self.http.request(
            "POST",
            url,
            payload={
                "postBody": urllib.parse.urlencode(
                    {"access_token": token, "providerId": "google.com"}
                ),
                "requestUri": self.config.oauth_redirect_url or "http://localhost",
                "returnIdpCredential": True,
                "returnSecureToken": True,
            },
        )
        return self._session_from_sign_in(response)

    def refresh(self, refresh_token: str) -> FirebaseSession:
        self.config.validate_firebase()
        token = str(refresh_token or "").strip()
        if not token:
            raise CloudSyncError("Firebase refresh token is missing.", category="authentication")
        url = (
            "https://securetoken.googleapis.com/v1/token?key="
            + urllib.parse.quote(self.config.web_api_key, safe="")
        )
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": token}
        ).encode("utf-8")
        request = urllib.request.Request(
            url=url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=12.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CloudSyncError(
                f"Firebase token refresh failed with HTTP {exc.code}.",
                category="authentication",
                retryable=exc.code >= 500,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise CloudSyncError(
                "Firebase token refresh failed.", category="network", retryable=True
            ) from exc
        return FirebaseSession(
            uid=str(payload.get("user_id") or ""),
            id_token=str(payload.get("id_token") or ""),
            refresh_token=str(payload.get("refresh_token") or token),
            expires_at=time.time() + max(60, int(payload.get("expires_in") or 3600)),
        )

    @staticmethod
    def _session_from_sign_in(payload: Mapping[str, Any]) -> FirebaseSession:
        uid = str(payload.get("localId") or "").strip()
        id_token = str(payload.get("idToken") or "").strip()
        refresh_token = str(payload.get("refreshToken") or "").strip()
        if not uid or not id_token or not refresh_token:
            raise CloudSyncError(
                "Firebase sign-in response was incomplete.", category="invalid_response"
            )
        return FirebaseSession(
            uid=uid,
            id_token=id_token,
            refresh_token=refresh_token,
            expires_at=time.time() + max(60, int(payload.get("expiresIn") or 3600)),
            email=str(payload.get("email") or ""),
            display_name=str(payload.get("displayName") or payload.get("fullName") or ""),
            photo_url=str(payload.get("photoUrl") or ""),
        )


def _firestore_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, Mapping):
        return {"mapValue": {"fields": {str(k): _firestore_value(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_firestore_value(item) for item in value]}}
    return {"stringValue": str(value)}


def _from_firestore_value(value: Mapping[str, Any]) -> Any:
    if "nullValue" in value:
        return None
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except (TypeError, ValueError):
            return 0
    if "doubleValue" in value:
        try:
            return float(value["doubleValue"])
        except (TypeError, ValueError):
            return 0.0
    if "stringValue" in value:
        return str(value["stringValue"])
    if "timestampValue" in value:
        return str(value["timestampValue"])
    if "arrayValue" in value:
        raw = value.get("arrayValue") or {}
        return [_from_firestore_value(item) for item in raw.get("values") or []]
    if "mapValue" in value:
        raw = value.get("mapValue") or {}
        return {
            str(key): _from_firestore_value(item)
            for key, item in (raw.get("fields") or {}).items()
        }
    return ""


def _firestore_document_data(document: Mapping[str, Any]) -> dict[str, Any]:
    fields = document.get("fields") or {}
    if not isinstance(fields, Mapping):
        raise CloudSyncError("Firestore document fields were invalid.", category="invalid_response")
    return {str(key): _from_firestore_value(value) for key, value in fields.items()}


class FirestoreREST:
    """User-token Firestore REST client; Firebase Security Rules remain authoritative."""

    def __init__(self, config: FirebaseConfig, *, http: JsonHttpClient | None = None):
        self.config = config
        self.http = http or JsonHttpClient()

    def upsert_document(
        self, *, session: FirebaseSession, document_path: str, data: Mapping[str, Any]
    ) -> None:
        self.config.validate_firebase()
        path = "/".join(
            urllib.parse.quote(part, safe="")
            for part in str(document_path or "").strip("/").split("/")
            if part
        )
        if not path:
            raise CloudSyncError("Firestore document path is missing.", category="configuration")
        url = (
            f"https://firestore.googleapis.com/v1/projects/{urllib.parse.quote(self.config.project_id, safe='')}"
            f"/databases/(default)/documents/{path}"
        )
        self.http.request(
            "PATCH",
            url,
            headers={"Authorization": f"Bearer {session.id_token}"},
            payload={"fields": {str(k): _firestore_value(v) for k, v in data.items()}},
        )

    def list_documents(
        self,
        *,
        session: FirebaseSession,
        collection_path: str,
        page_size: int = 100,
        max_documents: int = 500,
    ) -> list[dict[str, Any]]:
        self.config.validate_firebase()
        parts = [part for part in str(collection_path or "").strip("/").split("/") if part]
        if not parts:
            raise CloudSyncError("Firestore collection path is missing.", category="configuration")
        path = "/".join(urllib.parse.quote(part, safe="") for part in parts)
        page_size = max(1, min(int(page_size), 300))
        max_documents = max(1, min(int(max_documents), 2_000))
        base_url = (
            f"https://firestore.googleapis.com/v1/projects/{urllib.parse.quote(self.config.project_id, safe='')}"
            f"/databases/(default)/documents/{path}"
        )
        documents: list[dict[str, Any]] = []
        page_token = ""
        while len(documents) < max_documents:
            query = {"pageSize": str(min(page_size, max_documents - len(documents)))}
            if page_token:
                query["pageToken"] = page_token
            response = self.http.request(
                "GET",
                base_url + "?" + urllib.parse.urlencode(query),
                headers={"Authorization": f"Bearer {session.id_token}"},
            )
            raw_documents = response.get("documents") or []
            if not isinstance(raw_documents, list):
                raise CloudSyncError("Firestore list response was invalid.", category="invalid_response")
            for document in raw_documents:
                if not isinstance(document, Mapping):
                    continue
                documents.append(_firestore_document_data(document))
                if len(documents) >= max_documents:
                    break
            page_token = str(response.get("nextPageToken") or "")
            if not page_token or not raw_documents:
                break
        return documents


class ConversationSyncService:
    """Pushes local outbox events and pulls owner-isolated Firestore chat records."""

    def __init__(
        self,
        store: ConversationStore,
        firestore: FirestoreREST,
        *,
        retry_time_fn: Callable[[], str] | None = None,
    ):
        self.store = store
        self.firestore = firestore
        self.retry_time_fn = retry_time_fn or (lambda: "")

    def push_pending(self, *, session: FirebaseSession, limit: int = 100) -> SyncResult:
        owner_id = session.uid
        events = self.store.pending_outbox(owner_id=owner_id, limit=limit)
        synced = failed = skipped = 0
        for event in events:
            try:
                path, payload = self._event_document(event, owner_id=owner_id)
                self.firestore.upsert_document(session=session, document_path=path, data=payload)
                self.store.mark_outbox_synced(event.event_id)
                synced += 1
            except CloudSyncError as exc:
                self.store.mark_outbox_failed(
                    event.event_id,
                    error_category=exc.category,
                    next_attempt_at=self.retry_time_fn() if exc.retryable else "",
                )
                failed += 1
            except ValueError:
                self.store.mark_outbox_failed(
                    event.event_id, error_category="invalid_local_payload"
                )
                failed += 1
        return SyncResult(attempted=len(events), synced=synced, failed=failed, skipped=skipped)

    def pull_remote(
        self,
        *,
        session: FirebaseSession,
        conversation_limit: int = 100,
        message_limit_per_conversation: int = 500,
    ) -> PullResult:
        owner_id = session.uid
        conversations = self.firestore.list_documents(
            session=session,
            collection_path=f"users/{owner_id}/conversations",
            max_documents=conversation_limit,
        )
        merged_conversations = merged_messages = messages_seen = failed = 0
        for payload in conversations:
            try:
                conversation_id = str(payload.get("conversation_id") or "").strip()
                if not conversation_id:
                    raise ValueError("missing conversation id")
                if self.store.merge_remote_conversation(owner_id=owner_id, payload=payload):
                    merged_conversations += 1
                messages = self.firestore.list_documents(
                    session=session,
                    collection_path=(
                        f"users/{owner_id}/conversations/{conversation_id}/messages"
                    ),
                    max_documents=message_limit_per_conversation,
                )
                messages_seen += len(messages)
                for message_payload in messages:
                    try:
                        if self.store.merge_remote_message(
                            owner_id=owner_id, payload=message_payload
                        ):
                            merged_messages += 1
                    except (ValueError, CloudSyncError):
                        failed += 1
            except (ValueError, CloudSyncError):
                failed += 1
        return PullResult(
            conversations_seen=len(conversations),
            conversations_merged=merged_conversations,
            messages_seen=messages_seen,
            messages_merged=merged_messages,
            failed=failed,
        )

    def sync_bidirectional(
        self, *, session: FirebaseSession, push_limit: int = 100
    ) -> tuple[SyncResult, PullResult]:
        pushed = self.push_pending(session=session, limit=push_limit)
        pulled = self.pull_remote(session=session)
        return pushed, pulled

    @staticmethod
    def _event_document(
        event: SyncOutboxRecord, *, owner_id: str
    ) -> tuple[str, dict[str, Any]]:
        payload = event.payload
        if str(payload.get("owner_id") or "") != owner_id:
            raise CloudSyncError("Outbox owner mismatch.", category="owner_mismatch")
        conversation_id = str(payload.get("conversation_id") or event.entity_id)
        if event.entity_type == "conversation":
            path = f"users/{owner_id}/conversations/{event.entity_id}"
        elif event.entity_type == "message":
            if not conversation_id:
                raise CloudSyncError("Message conversation is missing.", category="invalid_local_payload")
            path = (
                f"users/{owner_id}/conversations/{conversation_id}/messages/{event.entity_id}"
            )
        else:
            raise CloudSyncError("Unsupported outbox entity.", category="invalid_local_payload")
        cloud_payload = dict(payload)
        cloud_payload["sync_state"] = "synced"
        cloud_payload["ownerId"] = owner_id
        device_id = str(payload.get("device_id") or "")
        if device_id:
            cloud_payload["deviceId"] = device_id
        return path, cloud_payload
