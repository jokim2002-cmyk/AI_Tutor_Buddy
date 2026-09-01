from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EMAIL_RE = re.compile(r"^[A-Z0-9._%+-]+@gmail\.com$", re.IGNORECASE)


@dataclass(frozen=True)
class LocalAuthSession:
    email: str
    created_at: float


class LocalAuthStore:
    """Small local signup/login store for the GyanVerse English V1 pilot.

    This is not Google OAuth and never asks for the user's real Gmail password.
    The password is a GyanVerse app password, stored only as PBKDF2 hash.
    """

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.auth_dir = self.data_dir / "auth"
        self.auth_dir.mkdir(parents=True, exist_ok=True)
        self.users_path = self.auth_dir / "local_users.json"
        self.session_path = self.auth_dir / "local_session.json"
        self.backup_dir = self.data_dir / "local_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_email(email: str) -> str:
        return str(email or "").strip().casefold()

    @staticmethod
    def validate_gmail(email: str) -> str:
        normalized = LocalAuthStore.normalize_email(email)
        if not EMAIL_RE.match(normalized):
            raise ValueError("Enter a valid Gmail address ending with @gmail.com.")
        return normalized

    @staticmethod
    def owner_id_for_email(email: str) -> str:
        email = LocalAuthStore.validate_gmail(email)
        digest = hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]
        return f"local-auth:{digest}"

    @staticmethod
    def validate_password(password: str) -> str:
        password = str(password or "")
        if len(password) < 6:
            raise ValueError("Password must be at least 6 characters.")
        if password.isspace():
            raise ValueError("Password cannot be blank.")
        return password

    def _load_users(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.users_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            return {}

    def _save_users(self, users: dict[str, Any]) -> None:
        self.users_path.write_text(
            json.dumps(users, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    @staticmethod
    def _hash_password(password: str, salt_b64: str | None = None) -> tuple[str, str]:
        salt = base64.b64decode(salt_b64) if salt_b64 else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            160_000,
        )
        return (
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )

    def signup(self, email: str, password: str) -> LocalAuthSession:
        email = self.validate_gmail(email)
        password = self.validate_password(password)
        users = self._load_users()
        if email in users:
            raise ValueError("This Gmail is already registered. Use Login.")
        salt_b64, hash_b64 = self._hash_password(password)
        now = time.time()
        users[email] = {
            "email": email,
            "salt": salt_b64,
            "password_hash": hash_b64,
            "created_at": now,
        }
        self._save_users(users)
        return self._write_session(email, now)

    def login(self, email: str, password: str) -> LocalAuthSession:
        email = self.validate_gmail(email)
        password = self.validate_password(password)
        users = self._load_users()
        user = users.get(email)
        if not isinstance(user, dict):
            raise ValueError("Account not found. Create account first.")
        salt_b64 = str(user.get("salt") or "")
        expected_hash = str(user.get("password_hash") or "")
        _, actual_hash = self._hash_password(password, salt_b64)
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise ValueError("Wrong password.")
        return self._write_session(email, time.time())

    def _write_session(self, email: str, created_at: float) -> LocalAuthSession:
        payload = {"email": email, "created_at": created_at}
        self.session_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return LocalAuthSession(email=email, created_at=created_at)

    def current_session(self) -> LocalAuthSession | None:
        try:
            payload = json.loads(self.session_path.read_text(encoding="utf-8"))
            email = self.validate_gmail(str(payload.get("email") or ""))
            created_at = float(payload.get("created_at") or 0)
            return LocalAuthSession(email=email, created_at=created_at)
        except Exception:
            return None

    def logout(self) -> None:
        try:
            self.session_path.unlink()
        except FileNotFoundError:
            pass

    def cleanup_old_backups(self, *, max_age_seconds: int = 86_400) -> int:
        now = time.time()
        deleted = 0
        for path in self.backup_dir.glob("*.json"):
            try:
                if now - path.stat().st_mtime > max_age_seconds:
                    path.unlink()
                    deleted += 1
            except Exception:
                continue
        return deleted

    def write_daily_backup(self, email: str, extra: dict[str, Any] | None = None) -> Path:
        email = self.validate_gmail(email)
        self.cleanup_old_backups(max_age_seconds=86_400)
        safe_email_hash = hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]
        date_key = time.strftime("%Y%m%d")
        path = self.backup_dir / f"gyanverse_backup_{date_key}_{safe_email_hash}.json"
        payload = {
            "email": email,
            "created_at": time.time(),
            "retention_seconds": 86_400,
            "backup_type": "local-device-1-day",
            "note": "Local backup only. Google Drive backup needs separate Google permission/OAuth.",
            "extra": extra or {},
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return path
