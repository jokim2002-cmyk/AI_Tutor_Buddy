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
                "GYANVERSE_GOOGLE_REDIRECT_URL", "http://localhost:8550/oauth_callback"
            ).strip(),
        )

    @property
    def firebase_ready(self) -> bool:
        return bool(self.project_id and self.web_api_key)

    @property
    def google_oauth_ready(self) -> bool:
        return bool(self.google_client_id and self.oauth_redirect_url)

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


class ConversationSyncService:
    """Pushes the local durable outbox to owner-isolated Firestore paths."""

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
        cloud_payload["ownerId"] = owner_id
        device_id = str(payload.get("device_id") or "")
        if device_id:
            cloud_payload["deviceId"] = device_id
        return path, cloud_payload
