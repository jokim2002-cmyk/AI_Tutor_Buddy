from __future__ import annotations

import json
from contextlib import contextmanager
import os
import re
import sqlite3
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class ConversationStoreError(ValueError):
    """Raised when local conversation data is invalid or cannot be persisted."""


SYNC_PENDING = "pending"
SYNC_SYNCED = "synced"
SYNC_FAILED = "failed"
VALID_SYNC_STATES = {SYNC_PENDING, SYNC_SYNCED, SYNC_FAILED}
VALID_ROLES = {"student", "tutor"}
MAX_MESSAGE_CHARS = 40_000
MAX_TITLE_CHARS = 80


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, *, max_length: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:max_length]


def _safe_owner_id(value: object) -> str:
    owner_id = _clean_text(value, max_length=160)
    if not owner_id:
        raise ConversationStoreError("owner_id is required")
    return owner_id


def _safe_id(value: object, *, prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "-", str(value or "")).strip("-.")
    return cleaned[:180] or f"{prefix}-{uuid.uuid4().hex}"



def _remote_version_key(*, updated_at: object, revision: object, device_id: object) -> tuple[str, int, str]:
    try:
        resolved_revision = max(1, int(revision))
    except (TypeError, ValueError):
        resolved_revision = 1
    return (
        _clean_text(updated_at, max_length=80),
        resolved_revision,
        _safe_id(device_id, prefix="device"),
    )

def suggest_conversation_title(text: object) -> str:
    title = _clean_text(text, max_length=MAX_TITLE_CHARS)
    if not title:
        return "New conversation"
    return title if len(title) < MAX_TITLE_CHARS else title[: MAX_TITLE_CHARS - 1].rstrip() + "…"


@dataclass(frozen=True)
class DeviceIdentity:
    device_id: str
    created_at: str

    @property
    def local_owner_id(self) -> str:
        return f"local:{self.device_id}"


class DeviceIdentityStore:
    """Creates a stable non-secret device identifier for offline ownership."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load_or_create(self) -> DeviceIdentity:
        with self._lock:
            if self.path.exists():
                try:
                    payload = json.loads(self.path.read_text(encoding="utf-8"))
                    device_id = _safe_id(payload.get("device_id"), prefix="device")
                    created_at = _clean_text(payload.get("created_at"), max_length=80) or utc_now()
                    return DeviceIdentity(device_id=device_id, created_at=created_at)
                except (OSError, json.JSONDecodeError, TypeError, ConversationStoreError):
                    backup = self.path.with_suffix(self.path.suffix + ".invalid")
                    try:
                        self.path.replace(backup)
                    except OSError:
                        pass
            identity = DeviceIdentity(device_id=f"device-{uuid.uuid4().hex}", created_at=utc_now())
            self._atomic_write({"schema_version": self.SCHEMA_VERSION, **asdict(identity)})
            return identity

    def _atomic_write(self, payload: Mapping[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


@dataclass(frozen=True)
class ConversationRecord:
    conversation_id: str
    owner_id: str
    student_id: str
    device_id: str
    title: str
    board: str
    standard: int
    subject: str
    chapter: str
    created_at: str
    updated_at: str
    revision: int
    sync_state: str
    deleted_at: str = ""


@dataclass(frozen=True)
class ChatMessageRecord:
    message_id: str
    conversation_id: str
    owner_id: str
    student_id: str
    device_id: str
    role: str
    text: str
    language: str
    board: str
    standard: int
    subject: str
    chapter: str
    backend: str
    created_at: str
    updated_at: str
    revision: int
    sync_state: str
    deleted_at: str = ""


@dataclass(frozen=True)
class SyncOutboxRecord:
    event_id: str
    owner_id: str
    entity_type: str
    entity_id: str
    operation: str
    payload_json: str
    created_at: str
    attempt_count: int
    next_attempt_at: str
    last_error: str

    @property
    def payload(self) -> dict[str, Any]:
        try:
            value = json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise ConversationStoreError("Outbox payload is not valid JSON") from exc
        if not isinstance(value, dict):
            raise ConversationStoreError("Outbox payload must be an object")
        return value


class ConversationStore:
    """Offline-first SQLite chat store with a durable cloud-sync outbox."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, device_id: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.device_id = _safe_id(device_id, prefix="device")
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    board TEXT NOT NULL,
                    standard INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    sync_state TEXT NOT NULL,
                    deleted_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_conversations_owner_student_updated
                    ON conversations(owner_id, student_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT NOT NULL,
                    board TEXT NOT NULL,
                    standard INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    backend TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    sync_state TEXT NOT NULL,
                    deleted_at TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(conversation_id) REFERENCES conversations(conversation_id)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
                    ON messages(conversation_id, created_at, message_id);
                CREATE TABLE IF NOT EXISTS sync_outbox (
                    event_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_outbox_owner_created
                    ON sync_outbox(owner_id, created_at, event_id);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', ?)",
                (str(self.SCHEMA_VERSION),),
            )

    def get_or_create_active(
        self,
        *,
        owner_id: str,
        student_id: str,
        board: str,
        standard: int,
        subject: str = "",
        chapter: str = "",
    ) -> ConversationRecord:
        owner_id = _safe_owner_id(owner_id)
        student_id = _safe_id(student_id, prefix="student")
        try:
            standard = int(standard)
        except (TypeError, ValueError) as exc:
            raise ConversationStoreError("standard must be a number") from exc
        board = _clean_text(board, max_length=40).upper()
        subject = _clean_text(subject, max_length=120)
        chapter = _clean_text(chapter, max_length=180)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.* FROM conversations AS c
                WHERE c.owner_id=? AND c.student_id=? AND c.board=? AND c.standard=?
                  AND c.subject=? AND c.chapter=? AND c.deleted_at=''
                ORDER BY
                    EXISTS(
                        SELECT 1
                        FROM messages AS m
                        WHERE m.conversation_id=c.conversation_id
                          AND m.owner_id=c.owner_id
                          AND m.deleted_at=''
                    ) DESC,
                    c.updated_at DESC,
                    c.conversation_id DESC
                LIMIT 1
                """,
                (owner_id, student_id, board, standard, subject, chapter),
            ).fetchone()
            if row is not None:
                return self._conversation_from_row(row)
        return self.create_conversation(
            owner_id=owner_id,
            student_id=student_id,
            board=board,
            standard=standard,
            subject=subject,
            chapter=chapter,
        )

    def create_conversation(
        self,
        *,
        owner_id: str,
        student_id: str,
        board: str,
        standard: int,
        subject: str = "",
        chapter: str = "",
        title: str = "New conversation",
        conversation_id: str | None = None,
    ) -> ConversationRecord:
        owner_id = _safe_owner_id(owner_id)
        student_id = _safe_id(student_id, prefix="student")
        try:
            standard = int(standard)
        except (TypeError, ValueError) as exc:
            raise ConversationStoreError("standard must be a number") from exc
        if standard < 1 or standard > 10:
            raise ConversationStoreError("standard must be between 1 and 10")
        now = utc_now()
        record = ConversationRecord(
            conversation_id=_safe_id(conversation_id, prefix="conversation"),
            owner_id=owner_id,
            student_id=student_id,
            device_id=self.device_id,
            title=_clean_text(title, max_length=MAX_TITLE_CHARS) or "New conversation",
            board=_clean_text(board, max_length=40).upper(),
            standard=standard,
            subject=_clean_text(subject, max_length=120),
            chapter=_clean_text(chapter, max_length=180),
            created_at=now,
            updated_at=now,
            revision=1,
            sync_state=SYNC_PENDING,
        )
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO conversations(
                    conversation_id, owner_id, student_id, device_id, title, board, standard,
                    subject, chapter, created_at, updated_at, revision, sync_state, deleted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                self._conversation_values(record),
            )
            self._enqueue(connection, "conversation", record.conversation_id, "upsert", asdict(record))
        return record

    def append_message(
        self,
        *,
        conversation_id: str,
        owner_id: str,
        student_id: str,
        role: str,
        text: str,
        language: str,
        board: str,
        standard: int,
        subject: str = "",
        chapter: str = "",
        backend: str = "",
        message_id: str | None = None,
        created_at: str | None = None,
    ) -> ChatMessageRecord:
        owner_id = _safe_owner_id(owner_id)
        conversation_id = _safe_id(conversation_id, prefix="conversation")
        student_id = _safe_id(student_id, prefix="student")
        role = _clean_text(role, max_length=20).lower()
        if role not in VALID_ROLES:
            raise ConversationStoreError(f"Unsupported chat role: {role}")
        cleaned_text = str(text or "").strip()[:MAX_MESSAGE_CHARS]
        if not cleaned_text:
            raise ConversationStoreError("message text is required")
        try:
            standard = int(standard)
        except (TypeError, ValueError) as exc:
            raise ConversationStoreError("standard must be a number") from exc
        now = created_at or utc_now()
        record = ChatMessageRecord(
            message_id=_safe_id(message_id, prefix="message"),
            conversation_id=conversation_id,
            owner_id=owner_id,
            student_id=student_id,
            device_id=self.device_id,
            role=role,
            text=cleaned_text,
            language=_clean_text(language, max_length=40),
            board=_clean_text(board, max_length=40).upper(),
            standard=standard,
            subject=_clean_text(subject, max_length=120),
            chapter=_clean_text(chapter, max_length=180),
            backend=_clean_text(backend, max_length=100),
            created_at=now,
            updated_at=now,
            revision=1,
            sync_state=SYNC_PENDING,
        )
        with self._lock, self._connection() as connection:
            conversation_row = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id=? AND owner_id=? AND deleted_at=''",
                (conversation_id, owner_id),
            ).fetchone()
            if conversation_row is None:
                raise ConversationStoreError("Conversation is unavailable for this owner")
            connection.execute(
                """
                INSERT INTO messages(
                    message_id, conversation_id, owner_id, student_id, device_id, role, text,
                    language, board, standard, subject, chapter, backend, created_at,
                    updated_at, revision, sync_state, deleted_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                self._message_values(record),
            )
            title = str(conversation_row["title"])
            if role == "student" and title == "New conversation":
                title = suggest_conversation_title(cleaned_text)
            conversation_revision = int(conversation_row["revision"]) + 1
            connection.execute(
                """
                UPDATE conversations
                SET title=?, board=?, standard=?, subject=?, chapter=?, updated_at=?,
                    revision=?, sync_state=?
                WHERE conversation_id=? AND owner_id=?
                """,
                (
                    title,
                    record.board,
                    record.standard,
                    record.subject,
                    record.chapter,
                    now,
                    conversation_revision,
                    SYNC_PENDING,
                    conversation_id,
                    owner_id,
                ),
            )
            updated_conversation = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
            ).fetchone()
            self._enqueue(connection, "message", record.message_id, "upsert", asdict(record))
            if updated_conversation is not None:
                self._enqueue(
                    connection,
                    "conversation",
                    conversation_id,
                    "upsert",
                    asdict(self._conversation_from_row(updated_conversation)),
                )
        return record

    def list_messages(
        self, *, conversation_id: str, owner_id: str, limit: int = 500
    ) -> list[ChatMessageRecord]:
        owner_id = _safe_owner_id(owner_id)
        limit = max(1, min(int(limit), 2_000))
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id=? AND owner_id=? AND deleted_at=''
                ORDER BY created_at ASC, message_id ASC
                LIMIT ?
                """,
                (_safe_id(conversation_id, prefix="conversation"), owner_id, limit),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def list_conversations(
        self, *, owner_id: str, student_id: str | None = None, limit: int = 100
    ) -> list[ConversationRecord]:
        owner_id = _safe_owner_id(owner_id)
        limit = max(1, min(int(limit), 500))
        sql = "SELECT * FROM conversations WHERE owner_id=? AND deleted_at=''"
        args: list[Any] = [owner_id]
        if student_id:
            sql += " AND student_id=?"
            args.append(_safe_id(student_id, prefix="student"))
        sql += " ORDER BY updated_at DESC, conversation_id DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connection() as connection:
            rows = connection.execute(sql, args).fetchall()
        return [self._conversation_from_row(row) for row in rows]

    def pending_outbox(self, *, owner_id: str, limit: int = 100) -> list[SyncOutboxRecord]:
        owner_id = _safe_owner_id(owner_id)
        limit = max(1, min(int(limit), 500))
        now = utc_now()
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM sync_outbox
                WHERE owner_id=? AND (next_attempt_at='' OR next_attempt_at<=?)
                ORDER BY created_at ASC, event_id ASC
                LIMIT ?
                """,
                (owner_id, now, limit),
            ).fetchall()
        return [SyncOutboxRecord(**dict(row)) for row in rows]

    def pending_outbox_count(self, *, owner_id: str) -> int:
        owner_id = _safe_owner_id(owner_id)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM sync_outbox WHERE owner_id=?",
                (owner_id,),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def merge_remote_conversation(
        self, *, owner_id: str, payload: Mapping[str, Any]
    ) -> bool:
        """Merge one owner-validated Firestore conversation without creating an outbox event."""
        owner_id = _safe_owner_id(owner_id)
        payload_owner = str(payload.get("owner_id") or payload.get("ownerId") or "").strip()
        if payload_owner != owner_id:
            raise ConversationStoreError("Remote conversation owner mismatch")
        conversation_id = _safe_id(payload.get("conversation_id"), prefix="conversation")
        student_id = _safe_id(payload.get("student_id"), prefix="student")
        try:
            standard = int(payload.get("standard"))
        except (TypeError, ValueError) as exc:
            raise ConversationStoreError("Remote standard must be a number") from exc
        if standard < 1 or standard > 10:
            raise ConversationStoreError("Remote standard must be between 1 and 10")
        created_at = _clean_text(payload.get("created_at"), max_length=80) or utc_now()
        updated_at = _clean_text(payload.get("updated_at"), max_length=80) or created_at
        try:
            revision = max(1, int(payload.get("revision") or 1))
        except (TypeError, ValueError):
            revision = 1
        record = ConversationRecord(
            conversation_id=conversation_id,
            owner_id=owner_id,
            student_id=student_id,
            device_id=_safe_id(payload.get("device_id") or payload.get("deviceId"), prefix="device"),
            title=_clean_text(payload.get("title"), max_length=MAX_TITLE_CHARS) or "New conversation",
            board=_clean_text(payload.get("board"), max_length=40).upper(),
            standard=standard,
            subject=_clean_text(payload.get("subject"), max_length=120),
            chapter=_clean_text(payload.get("chapter"), max_length=180),
            created_at=created_at,
            updated_at=updated_at,
            revision=revision,
            sync_state=SYNC_SYNCED,
            deleted_at=_clean_text(payload.get("deleted_at"), max_length=80),
        )
        with self._lock, self._connection() as connection:
            existing = connection.execute(
                "SELECT * FROM conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["owner_id"]) != owner_id:
                    raise ConversationStoreError("Remote conversation conflicts with another owner")
                local_key = _remote_version_key(
                    updated_at=existing["updated_at"],
                    revision=existing["revision"],
                    device_id=existing["device_id"],
                )
                remote_key = _remote_version_key(
                    updated_at=record.updated_at, revision=record.revision, device_id=record.device_id
                )
                if str(existing["sync_state"]) in {SYNC_PENDING, SYNC_FAILED} and local_key >= remote_key:
                    return False
                if remote_key <= local_key:
                    return False
                connection.execute(
                    """
                    UPDATE conversations
                    SET owner_id=?, student_id=?, device_id=?, title=?, board=?, standard=?,
                        subject=?, chapter=?, created_at=?, updated_at=?, revision=?,
                        sync_state=?, deleted_at=?
                    WHERE conversation_id=?
                    """,
                    (*self._conversation_values(record)[1:], conversation_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO conversations(
                        conversation_id, owner_id, student_id, device_id, title, board, standard,
                        subject, chapter, created_at, updated_at, revision, sync_state, deleted_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    self._conversation_values(record),
                )
        return True

    def merge_remote_message(self, *, owner_id: str, payload: Mapping[str, Any]) -> bool:
        """Merge one owner-validated Firestore message without creating an outbox event."""
        owner_id = _safe_owner_id(owner_id)
        payload_owner = str(payload.get("owner_id") or payload.get("ownerId") or "").strip()
        if payload_owner != owner_id:
            raise ConversationStoreError("Remote message owner mismatch")
        message_id = _safe_id(payload.get("message_id"), prefix="message")
        conversation_id = _safe_id(payload.get("conversation_id"), prefix="conversation")
        student_id = _safe_id(payload.get("student_id"), prefix="student")
        role = _clean_text(payload.get("role"), max_length=20).lower()
        if role not in VALID_ROLES:
            raise ConversationStoreError("Remote message role is invalid")
        text = str(payload.get("text") or "").strip()[:MAX_MESSAGE_CHARS]
        if not text:
            raise ConversationStoreError("Remote message text is required")
        try:
            standard = int(payload.get("standard"))
        except (TypeError, ValueError) as exc:
            raise ConversationStoreError("Remote standard must be a number") from exc
        if standard < 1 or standard > 10:
            raise ConversationStoreError("Remote standard must be between 1 and 10")
        created_at = _clean_text(payload.get("created_at"), max_length=80) or utc_now()
        updated_at = _clean_text(payload.get("updated_at"), max_length=80) or created_at
        try:
            revision = max(1, int(payload.get("revision") or 1))
        except (TypeError, ValueError):
            revision = 1
        record = ChatMessageRecord(
            message_id=message_id,
            conversation_id=conversation_id,
            owner_id=owner_id,
            student_id=student_id,
            device_id=_safe_id(payload.get("device_id") or payload.get("deviceId"), prefix="device"),
            role=role,
            text=text,
            language=_clean_text(payload.get("language"), max_length=40),
            board=_clean_text(payload.get("board"), max_length=40).upper(),
            standard=standard,
            subject=_clean_text(payload.get("subject"), max_length=120),
            chapter=_clean_text(payload.get("chapter"), max_length=180),
            backend=_clean_text(payload.get("backend"), max_length=100),
            created_at=created_at,
            updated_at=updated_at,
            revision=revision,
            sync_state=SYNC_SYNCED,
            deleted_at=_clean_text(payload.get("deleted_at"), max_length=80),
        )
        with self._lock, self._connection() as connection:
            parent = connection.execute(
                "SELECT owner_id FROM conversations WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()
            if parent is None or str(parent["owner_id"]) != owner_id:
                raise ConversationStoreError("Remote message conversation is unavailable")
            existing = connection.execute(
                "SELECT * FROM messages WHERE message_id=?", (message_id,)
            ).fetchone()
            if existing is not None:
                if str(existing["owner_id"]) != owner_id:
                    raise ConversationStoreError("Remote message conflicts with another owner")
                local_key = _remote_version_key(
                    updated_at=existing["updated_at"],
                    revision=existing["revision"],
                    device_id=existing["device_id"],
                )
                remote_key = _remote_version_key(
                    updated_at=record.updated_at, revision=record.revision, device_id=record.device_id
                )
                if str(existing["sync_state"]) in {SYNC_PENDING, SYNC_FAILED} and local_key >= remote_key:
                    return False
                if remote_key <= local_key:
                    return False
                connection.execute(
                    """
                    UPDATE messages
                    SET conversation_id=?, owner_id=?, student_id=?, device_id=?, role=?, text=?,
                        language=?, board=?, standard=?, subject=?, chapter=?, backend=?, created_at=?,
                        updated_at=?, revision=?, sync_state=?, deleted_at=?
                    WHERE message_id=?
                    """,
                    (*self._message_values(record)[1:], message_id),
                )
            else:
                connection.execute(
                    """
                    INSERT INTO messages(
                        message_id, conversation_id, owner_id, student_id, device_id, role, text,
                        language, board, standard, subject, chapter, backend, created_at,
                        updated_at, revision, sync_state, deleted_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    self._message_values(record),
                )
        return True

    def mark_outbox_synced(self, event_id: str) -> None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT entity_type, entity_id FROM sync_outbox WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute("DELETE FROM sync_outbox WHERE event_id=?", (event_id,))
            table = "conversations" if row["entity_type"] == "conversation" else "messages"
            id_column = "conversation_id" if table == "conversations" else "message_id"
            remaining = connection.execute(
                "SELECT 1 FROM sync_outbox WHERE entity_type=? AND entity_id=? LIMIT 1",
                (row["entity_type"], row["entity_id"]),
            ).fetchone()
            if remaining is None:
                connection.execute(
                    f"UPDATE {table} SET sync_state=? WHERE {id_column}=?",
                    (SYNC_SYNCED, row["entity_id"]),
                )

    def mark_outbox_failed(
        self, event_id: str, *, error_category: str, next_attempt_at: str = ""
    ) -> None:
        error = _clean_text(error_category, max_length=160)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT entity_type, entity_id FROM sync_outbox WHERE event_id=?",
                (event_id,),
            ).fetchone()
            if row is None:
                return
            connection.execute(
                """
                UPDATE sync_outbox
                SET attempt_count=attempt_count+1, next_attempt_at=?, last_error=?
                WHERE event_id=?
                """,
                (next_attempt_at, error, event_id),
            )
            table = "conversations" if row["entity_type"] == "conversation" else "messages"
            id_column = "conversation_id" if table == "conversations" else "message_id"
            connection.execute(
                f"UPDATE {table} SET sync_state=? WHERE {id_column}=?",
                (SYNC_FAILED, row["entity_id"]),
            )

    def claim_local_owner(self, *, local_owner_id: str, authenticated_owner_id: str) -> int:
        """Re-keys local data after explicit sign-in so it can be uploaded safely."""
        local_owner_id = _safe_owner_id(local_owner_id)
        authenticated_owner_id = _safe_owner_id(authenticated_owner_id)
        if local_owner_id == authenticated_owner_id:
            return 0
        with self._lock, self._connection() as connection:
            conversations = connection.execute(
                "SELECT * FROM conversations WHERE owner_id=?", (local_owner_id,)
            ).fetchall()
            connection.execute(
                "UPDATE conversations SET owner_id=?, sync_state=? WHERE owner_id=?",
                (authenticated_owner_id, SYNC_PENDING, local_owner_id),
            )
            connection.execute(
                "UPDATE messages SET owner_id=?, sync_state=? WHERE owner_id=?",
                (authenticated_owner_id, SYNC_PENDING, local_owner_id),
            )
            connection.execute("DELETE FROM sync_outbox WHERE owner_id=?", (local_owner_id,))
            for row in conversations:
                conversation_id = str(row["conversation_id"])
                updated = connection.execute(
                    "SELECT * FROM conversations WHERE conversation_id=?", (conversation_id,)
                ).fetchone()
                if updated is not None:
                    self._enqueue(
                        connection,
                        "conversation",
                        conversation_id,
                        "upsert",
                        asdict(self._conversation_from_row(updated)),
                        owner_id=authenticated_owner_id,
                    )
                message_rows = connection.execute(
                    "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at, message_id",
                    (conversation_id,),
                ).fetchall()
                for message_row in message_rows:
                    record = self._message_from_row(message_row)
                    self._enqueue(
                        connection,
                        "message",
                        record.message_id,
                        "upsert",
                        asdict(record),
                        owner_id=authenticated_owner_id,
                    )
        return len(conversations)

    def _enqueue(
        self,
        connection: sqlite3.Connection,
        entity_type: str,
        entity_id: str,
        operation: str,
        payload: Mapping[str, Any],
        *,
        owner_id: str | None = None,
    ) -> None:
        resolved_owner = owner_id or _safe_owner_id(payload.get("owner_id"))
        connection.execute(
            """
            INSERT INTO sync_outbox(
                event_id, owner_id, entity_type, entity_id, operation, payload_json,
                created_at, attempt_count, next_attempt_at, last_error
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                f"outbox-{uuid.uuid4().hex}",
                resolved_owner,
                entity_type,
                entity_id,
                operation,
                json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
                utc_now(),
                0,
                "",
                "",
            ),
        )

    @staticmethod
    def _conversation_values(record: ConversationRecord) -> tuple[Any, ...]:
        return (
            record.conversation_id,
            record.owner_id,
            record.student_id,
            record.device_id,
            record.title,
            record.board,
            record.standard,
            record.subject,
            record.chapter,
            record.created_at,
            record.updated_at,
            record.revision,
            record.sync_state,
            record.deleted_at,
        )

    @staticmethod
    def _message_values(record: ChatMessageRecord) -> tuple[Any, ...]:
        return (
            record.message_id,
            record.conversation_id,
            record.owner_id,
            record.student_id,
            record.device_id,
            record.role,
            record.text,
            record.language,
            record.board,
            record.standard,
            record.subject,
            record.chapter,
            record.backend,
            record.created_at,
            record.updated_at,
            record.revision,
            record.sync_state,
            record.deleted_at,
        )

    @staticmethod
    def _conversation_from_row(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(**dict(row))

    @staticmethod
    def _message_from_row(row: sqlite3.Row) -> ChatMessageRecord:
        return ChatMessageRecord(**dict(row))
