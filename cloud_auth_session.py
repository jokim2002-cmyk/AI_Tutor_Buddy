from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Callable

from cloud_sync import FirebaseAuthREST, FirebaseConfig, FirebaseSession


class OAuthTokenStore:
    """Encrypted-at-rest Flet OAuth token persistence.

    Persistence is deliberately disabled when no storage secret is configured.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        secret: str | None = None,
        encrypt_fn: Callable[[str, str], str] | None = None,
        decrypt_fn: Callable[[str, str], str] | None = None,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secret = (secret if secret is not None else os.getenv("GYANVERSE_AUTH_STORAGE_SECRET", "")).strip()
        self._encrypt_fn = encrypt_fn
        self._decrypt_fn = decrypt_fn
        self._lock = threading.RLock()

    @property
    def enabled(self) -> bool:
        return bool(self.secret)

    def _crypto(self) -> tuple[Callable[[str, str], str], Callable[[str, str], str]]:
        if self._encrypt_fn is not None and self._decrypt_fn is not None:
            return self._encrypt_fn, self._decrypt_fn
        from flet.security import decrypt, encrypt

        return encrypt, decrypt

    def save(self, token_json: str) -> bool:
        value = str(token_json or "").strip()
        if not value or not self.enabled:
            return False
        encrypt, _ = self._crypto()
        encrypted = encrypt(value, self.secret)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encrypted)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass
        return True

    def load(self) -> str:
        if not self.enabled or not self.path.exists():
            return ""
        try:
            encrypted = self.path.read_text(encoding="utf-8").strip()
            if not encrypted:
                return ""
            _, decrypt = self._crypto()
            return str(decrypt(encrypted, self.secret) or "").strip()
        except Exception:
            self.clear()
            return ""

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass


class FirebaseSessionManager:
    """Keeps a short-lived Firebase session and refreshes it before cloud calls."""

    def __init__(self, config: FirebaseConfig, *, auth: FirebaseAuthREST | None = None):
        self.config = config
        self.auth = auth or FirebaseAuthREST(config)
        self.session: FirebaseSession | None = None
        self._lock = threading.RLock()

    @property
    def signed_in(self) -> bool:
        return self.session is not None

    def exchange_google_access_token(self, access_token: str) -> FirebaseSession:
        session = self.auth.exchange_google_access_token(access_token)
        with self._lock:
            self.session = session
        return session

    def current(self) -> FirebaseSession:
        with self._lock:
            session = self.session
        if session is None:
            raise RuntimeError("Cloud session is signed out")
        if session.expired:
            session = self.auth.refresh(session.refresh_token)
            with self._lock:
                self.session = session
        return session

    def clear(self) -> None:
        with self._lock:
            self.session = None
