from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import random
import re
import shutil
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


class Phase11Error(ValueError):
    """Base error for Phase 11 validation and local-storage failures."""


class LearningMode(str, Enum):
    EXPLAIN = "explain"
    HOMEWORK = "homework"
    REVISION = "revision"
    EXAM = "exam"


class VoiceState(str, Enum):
    IDLE = "idle"
    REQUESTING_PERMISSION = "requesting_permission"
    RECORDING = "recording"
    PROCESSING = "processing"
    READY = "ready"
    PLAYING = "playing"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


SUPPORTED_BOARDS = ("GSEB", "CBSE")
SUPPORTED_MEDIUMS = ("Gujarati", "English", "Hindi")
SUPPORTED_LANGUAGES = ("Gujarati", "Hindi", "English")
SUPPORTED_STANDARDS = tuple(range(1, 11))
SUPPORTED_ATTACHMENT_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".pdf",
    ".txt",
    ".md",
    ".doc",
    ".docx",
}
MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_SESSION = 8


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_filename(value: str) -> str:
    name = Path(value or "attachment").name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return stem[:120] or "attachment"


def clean_student_text(value: object, *, max_length: int = 8_000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:max_length]


@dataclass(frozen=True)
class StudentLearningContext:
    student_id: str = "student-1"
    name: str = "Student"
    board: str = "GSEB"
    medium: str = "Gujarati"
    standard: int = 7
    preferred_language: str = "Gujarati"
    current_subject: str = "Mathematics"
    current_chapter: str = ""
    current_topic: str = ""
    learning_mode: str = LearningMode.EXPLAIN.value
    onboarding_complete: bool = False
    updated_at: str = ""

    def validate(self) -> "StudentLearningContext":
        student_id = clean_student_text(self.student_id, max_length=80) or "student-1"
        name = clean_student_text(self.name, max_length=80) or "Student"
        board = clean_student_text(self.board, max_length=40).upper() or "GSEB"
        if board not in SUPPORTED_BOARDS:
            raise Phase11Error(f"Unsupported board: {self.board}. Supported boards: GSEB, CBSE.")
        medium = clean_student_text(self.medium, max_length=40) or "Gujarati"
        language = clean_student_text(self.preferred_language, max_length=40) or medium
        subject = clean_student_text(self.current_subject, max_length=100)
        chapter = clean_student_text(self.current_chapter, max_length=180)
        topic = clean_student_text(self.current_topic, max_length=300)
        try:
            standard = int(self.standard)
        except (TypeError, ValueError) as exc:
            raise Phase11Error("Standard must be a number from 1 to 10.") from exc
        if standard not in SUPPORTED_STANDARDS:
            raise Phase11Error("Standard must be between 1 and 10.")
        mode = str(self.learning_mode or LearningMode.EXPLAIN.value).lower().strip()
        if mode not in {item.value for item in LearningMode}:
            raise Phase11Error(f"Unsupported learning mode: {mode}")
        return replace(
            self,
            student_id=student_id,
            name=name,
            board=board,
            medium=medium,
            standard=standard,
            preferred_language=language,
            current_subject=subject,
            current_chapter=chapter,
            current_topic=topic,
            learning_mode=mode,
            updated_at=self.updated_at or utc_now(),
        )

    @property
    def grade(self) -> int:
        return self.standard

    @property
    def context_label(self) -> str:
        parts = [self.board, self.medium, f"Std {self.standard}"]
        if self.current_subject:
            parts.append(self.current_subject)
        if self.current_chapter:
            parts.append(self.current_chapter)
        return " • ".join(parts)


class LearningContextStore:
    """Atomic JSON persistence for onboarding and latest school context."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def load(self) -> StudentLearningContext:
        with self._lock:
            if not self.path.exists():
                return StudentLearningContext().validate()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                data = payload.get("context", payload)
                allowed = set(StudentLearningContext.__dataclass_fields__)
                context = StudentLearningContext(**{k: v for k, v in data.items() if k in allowed})
                return context.validate()
            except (OSError, json.JSONDecodeError, TypeError, Phase11Error):
                backup = self.path.with_suffix(self.path.suffix + ".invalid")
                try:
                    shutil.copy2(self.path, backup)
                except OSError:
                    pass
                return StudentLearningContext().validate()

    def save(self, context: StudentLearningContext) -> StudentLearningContext:
        normalized = replace(context.validate(), updated_at=utc_now())
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "context": asdict(normalized),
        }
        with self._lock:
            self._atomic_write(payload)
        return normalized

    def update(self, **changes: Any) -> StudentLearningContext:
        return self.save(replace(self.load(), **changes))

    def reset(self) -> StudentLearningContext:
        return self.save(StudentLearningContext())

    def _atomic_write(self, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(payload, indent=2, ensure_ascii=False)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, self.path)
        finally:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


@dataclass(frozen=True)
class AttachmentRecord:
    attachment_id: str
    student_id: str
    session_id: str
    original_name: str
    stored_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    stored_path: str
    created_at: str

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith("image/")

    @property
    def display_size(self) -> str:
        if self.size_bytes < 1024:
            return f"{self.size_bytes} B"
        if self.size_bytes < 1024 * 1024:
            return f"{self.size_bytes / 1024:.1f} KB"
        return f"{self.size_bytes / (1024 * 1024):.1f} MB"


class HomeworkAttachmentStore:
    """Privacy-local attachment storage with validation, history and deletion."""

    SCHEMA_VERSION = 1

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "attachments.json"
        self._lock = threading.RLock()

    def add_bytes(
        self,
        *,
        student_id: str,
        session_id: str,
        original_name: str,
        data: bytes,
        mime_type: str | None = None,
    ) -> AttachmentRecord:
        if not data:
            raise Phase11Error("Selected file is empty.")
        if len(data) > MAX_ATTACHMENT_BYTES:
            raise Phase11Error("Each homework file must be 15 MB or smaller.")
        original_name = safe_filename(original_name)
        extension = Path(original_name).suffix.lower()
        if extension not in SUPPORTED_ATTACHMENT_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_ATTACHMENT_EXTENSIONS))
            raise Phase11Error(f"Unsupported file type. Allowed: {allowed}")
        existing = self.list_session(student_id=student_id, session_id=session_id)
        if len(existing) >= MAX_ATTACHMENTS_PER_SESSION:
            raise Phase11Error("Maximum 8 homework files can be attached at one time.")
        attachment_id = f"att-{uuid.uuid4().hex[:12]}"
        stored_name = f"{attachment_id}{extension}"
        student_dir = self.root / safe_filename(student_id) / safe_filename(session_id)
        student_dir.mkdir(parents=True, exist_ok=True)
        path = student_dir / stored_name
        path.write_bytes(data)
        guessed = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        record = AttachmentRecord(
            attachment_id=attachment_id,
            student_id=clean_student_text(student_id, max_length=80) or "student-1",
            session_id=clean_student_text(session_id, max_length=80) or "session",
            original_name=original_name,
            stored_name=stored_name,
            mime_type=clean_student_text(mime_type, max_length=120) or guessed,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            stored_path=str(path),
            created_at=utc_now(),
        )
        with self._lock:
            records = self._load_records()
            records.append(record)
            self._save_records(records)
        return record

    def list_session(self, *, student_id: str, session_id: str) -> list[AttachmentRecord]:
        return [
            item
            for item in self._load_records()
            if item.student_id == student_id and item.session_id == session_id
        ]

    def list_student(self, student_id: str) -> list[AttachmentRecord]:
        return [item for item in self._load_records() if item.student_id == student_id]

    def delete(self, attachment_id: str, *, student_id: str) -> bool:
        with self._lock:
            records = self._load_records()
            kept: list[AttachmentRecord] = []
            removed: AttachmentRecord | None = None
            for item in records:
                if item.attachment_id == attachment_id and item.student_id == student_id:
                    removed = item
                else:
                    kept.append(item)
            if removed is None:
                return False
            try:
                Path(removed.stored_path).unlink(missing_ok=True)
            finally:
                self._save_records(kept)
            return True

    def clear_session(self, *, student_id: str, session_id: str) -> int:
        items = self.list_session(student_id=student_id, session_id=session_id)
        return sum(self.delete(item.attachment_id, student_id=student_id) for item in items)

    def _load_records(self) -> list[AttachmentRecord]:
        with self._lock:
            if not self.index_path.exists():
                return []
            try:
                payload = json.loads(self.index_path.read_text(encoding="utf-8"))
                records = payload.get("attachments", [])
                return [AttachmentRecord(**item) for item in records]
            except (OSError, json.JSONDecodeError, TypeError):
                return []

    def _save_records(self, records: Sequence[AttachmentRecord]) -> None:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "attachments": [asdict(item) for item in records],
        }
        self.index_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


@dataclass(frozen=True)
class SyllabusSource:
    title: str
    publisher: str
    edition: str
    source_url: str = ""
    acquired_on: str = ""
    official: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SyllabusSource":
        source = cls(
            title=clean_student_text(payload.get("title"), max_length=200),
            publisher=clean_student_text(payload.get("publisher"), max_length=120),
            edition=clean_student_text(payload.get("edition"), max_length=80),
            source_url=clean_student_text(payload.get("source_url"), max_length=500),
            acquired_on=clean_student_text(payload.get("acquired_on"), max_length=30),
            official=bool(payload.get("official", False)),
            notes=clean_student_text(payload.get("notes"), max_length=500),
        )
        if not source.title or not source.publisher or not source.edition:
            raise Phase11Error("Syllabus source requires title, publisher and edition.")
        return source


@dataclass(frozen=True)
class SyllabusTopic:
    topic_id: str
    title: str
    aliases: tuple[str, ...] = ()
    learning_objectives: tuple[str, ...] = ()
    explanation: str = ""
    examples: tuple[str, ...] = ()
    exercises: tuple[str, ...] = ()
    solutions: tuple[str, ...] = ()
    practice_questions: tuple[str, ...] = ()
    practice_solutions: tuple[str, ...] = ()
    marks_pattern: str = ""
    content_origin: str = "metadata_only"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, fallback_id: str) -> "SyllabusTopic":
        origin = clean_student_text(payload.get("content_origin"), max_length=40) or "metadata_only"
        if origin not in {"official", "ai_generated", "teacher_authored", "metadata_only"}:
            raise Phase11Error(f"Unsupported content_origin: {origin}")
        title = clean_student_text(payload.get("title"), max_length=200)
        if not title:
            raise Phase11Error("Each syllabus topic requires a title.")
        values = lambda key: tuple(
            clean_student_text(item, max_length=2_000)
            for item in payload.get(key, [])
            if clean_student_text(item, max_length=2_000)
        )
        return cls(
            topic_id=clean_student_text(payload.get("topic_id"), max_length=100) or fallback_id,
            title=title,
            aliases=values("aliases"),
            learning_objectives=values("learning_objectives"),
            explanation=clean_student_text(payload.get("explanation"), max_length=10_000),
            examples=values("examples"),
            exercises=values("exercises"),
            solutions=values("solutions"),
            practice_questions=values("practice_questions"),
            practice_solutions=values("practice_solutions"),
            marks_pattern=clean_student_text(payload.get("marks_pattern"), max_length=1_000),
            content_origin=origin,
        )


@dataclass(frozen=True)
class SyllabusChapter:
    chapter_id: str
    number: str
    title: str
    topics: tuple[SyllabusTopic, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, index: int) -> "SyllabusChapter":
        title = clean_student_text(payload.get("title"), max_length=200)
        if not title:
            raise Phase11Error("Each syllabus chapter requires a title.")
        chapter_id = clean_student_text(payload.get("chapter_id"), max_length=100) or f"chapter-{index}"
        topics = tuple(
            SyllabusTopic.from_dict(item, fallback_id=f"{chapter_id}-topic-{topic_index}")
            for topic_index, item in enumerate(payload.get("topics", []), start=1)
        )
        return cls(
            chapter_id=chapter_id,
            number=clean_student_text(payload.get("number"), max_length=30) or str(index),
            title=title,
            topics=topics,
        )


@dataclass(frozen=True)
class BoardSyllabus:
    schema_version: int
    board: str
    medium: str
    standard: int
    subject: str
    textbook: str
    source: SyllabusSource
    chapters: tuple[SyllabusChapter, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BoardSyllabus":
        raw_board = clean_student_text(payload.get("board"), max_length=20).upper()
        if raw_board not in SUPPORTED_BOARDS:
            raise Phase11Error(f"Unsupported board: {raw_board}. Supported boards: GSEB, CBSE.")
        try:
            standard = int(payload.get("standard"))
        except (TypeError, ValueError) as exc:
            raise Phase11Error("Syllabus standard must be a number from 1 to 10.") from exc
        if standard not in SUPPORTED_STANDARDS:
            raise Phase11Error("Syllabus standard must be between 1 and 10.")
        medium = clean_student_text(payload.get("medium"), max_length=40)
        subject = clean_student_text(payload.get("subject"), max_length=120)
        textbook = clean_student_text(payload.get("textbook"), max_length=200)
        if not medium or not subject or not textbook:
            raise Phase11Error("Syllabus requires medium, subject and textbook.")
        chapters = tuple(
            SyllabusChapter.from_dict(item, index=index)
            for index, item in enumerate(payload.get("chapters", []), start=1)
        )
        syllabus = cls(
            schema_version=int(payload.get("schema_version", 1)),
            board=raw_board,
            medium=medium,
            standard=standard,
            subject=subject,
            textbook=textbook,
            source=SyllabusSource.from_dict(payload.get("source", {})),
            chapters=chapters,
        )
        syllabus.validate_origin_rules()
        return syllabus

    def validate_origin_rules(self) -> None:
        for chapter in self.chapters:
            for topic in chapter.topics:
                has_material = any(
                    [
                        topic.explanation,
                        topic.examples,
                        topic.exercises,
                        topic.solutions,
                        topic.practice_questions,
                        topic.practice_solutions,
                    ]
                )
                if topic.content_origin == "official" and not self.source.official:
                    raise Phase11Error(
                        "Topic cannot be marked official when source metadata is not official."
                    )
                if topic.content_origin == "metadata_only" and has_material:
                    raise Phase11Error(
                        "metadata_only topics cannot contain explanations, exercises or solutions."
                    )
                if topic.practice_solutions and (
                    len(topic.practice_solutions) != len(topic.practice_questions)
                ):
                    raise Phase11Error(
                        "practice_solutions must map one-to-one with practice_questions."
                    )
                if topic.solutions and len(topic.solutions) != len(topic.exercises):
                    raise Phase11Error(
                        "solutions must map one-to-one with exercises."
                    )

    @property
    def key(self) -> str:
        return f"{self.board.lower()}-{self.medium.lower()}-{self.standard}-{safe_filename(self.subject).lower()}"

    def coverage(self) -> dict[str, Any]:
        topics = [topic for chapter in self.chapters for topic in chapter.topics]
        content_topics = [
            topic
            for topic in topics
            if topic.content_origin != "metadata_only"
            and any([topic.explanation, topic.examples, topic.exercises, topic.practice_questions])
        ]
        official_topics = [topic for topic in content_topics if topic.content_origin == "official"]
        total = len(topics)
        return {
            "board": self.board,
            "chapters": len(self.chapters),
            "topics": total,
            "content_topics": len(content_topics),
            "official_topics": len(official_topics),
            "coverage_percent": round((len(content_topics) / total) * 100, 2) if total else 0.0,
            "official_coverage_percent": round((len(official_topics) / total) * 100, 2)
            if total
            else 0.0,
        }


def _normalize_syllabus_lookup_text(value: object) -> str:
    text = clean_student_text(value, max_length=4_000).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def _contains_syllabus_phrase(haystack: str, needle: str) -> bool:
    if not haystack or not needle:
        return False
    padded_haystack = f" {haystack} "
    if f" {needle} " in padded_haystack:
        return True

    # English textbook aliases frequently differ only by a safe singular/plural
    # ending (for example, "symbol" vs "symbols").  Treat that one-word form as
    # equivalent without applying broad stemming that could create false routes.
    if " " not in needle and len(needle) > 3:
        variants: set[str] = set()
        if needle.endswith("s") and not needle.endswith(("ss", "is", "us")):
            variants.add(needle[:-1])
        elif not needle.endswith(("s", "x", "z")):
            variants.add(needle + "s")
        if any(f" {variant} " in padded_haystack for variant in variants):
            return True
    return False


def _semester_chapter_reference(value: object) -> str:
    """Return an unambiguous installed chapter number such as ``s2-1``.

    Some GSEB semester books restart their printed chapter numbering at 1.
    Plain ``Chapter 1`` therefore remains supported for books with ordinary
    numbering, while an explicit ``Semester 2 Chapter 1`` is converted to the
    canonical semester-qualified number used by the combined syllabus package.
    """

    text = _normalize_syllabus_lookup_text(value)
    if not text:
        return ""

    semester_first = re.search(
        r"\b(?:semester|sem)\s*([12])\s+"
        r"(?:(?:chapter|chap|ch)\s*(?:number|no)?\s*(\d{1,2})"
        r"|(?:revision|rev)\s*(\d{1,2}))\b",
        text,
    )
    if semester_first:
        semester, chapter, revision = semester_first.groups()
        suffix = chapter if chapter else f"r{revision}"
        return f"s{semester}-{suffix}"

    reference_first = re.search(
        r"\b(?:(?:chapter|chap|ch)\s*(?:number|no)?\s*(\d{1,2})"
        r"|(?:revision|rev)\s*(\d{1,2}))\s+"
        r"(?:of\s+)?(?:semester|sem)\s*([12])\b",
        text,
    )
    if reference_first:
        chapter, revision, semester = reference_first.groups()
        suffix = chapter if chapter else f"r{revision}"
        return f"s{semester}-{suffix}"

    return ""


_CONTEXT_FALLBACK_WORDS = {
    "a", "about", "again", "an", "and", "answer", "answers", "any", "are",
    "can", "chapter", "check", "correct", "current", "do", "easy", "example", "examples",
    "exercise", "exercises", "explain", "for", "from", "give", "help", "homework", "how",
    "hint", "hints", "i", "in", "is", "it", "just", "language", "mark", "marks", "me", "my", "of", "one", "only",
    "please", "practice", "question", "questions", "quiz", "repeat", "revision",
    "revise", "right", "show", "simple", "solution", "solutions", "solve", "summary",
    "same", "selected", "tell", "test", "that", "the", "this", "three", "topic", "two", "understand",
    "what", "with", "without", "wrong", "you", "your",
}


def _message_allows_context_topic_fallback(message_text: str) -> bool:
    """Allow stale-context fallback only for clearly referential tutor requests."""

    if not message_text:
        return True
    evaluation_phrases = (
        "check my answer",
        "check this answer",
        "is my answer correct",
        "is this correct",
        "is it correct",
        "my attempt",
        "review my answer",
        "evaluate my answer",
        "mark my answer",
    )
    if any(phrase in message_text for phrase in evaluation_phrases):
        return True

    tokens = set(message_text.split())
    return bool(tokens) and all(
        token in _CONTEXT_FALLBACK_WORDS or token.isdigit()
        for token in tokens
    )


@dataclass(frozen=True)
class SyllabusTopicMatch:
    syllabus: BoardSyllabus
    chapter: SyllabusChapter
    topic: SyllabusTopic
    matched_by: str

    @property
    def has_validated_content(self) -> bool:
        return self.topic.content_origin != "metadata_only" and any(
            (
                self.topic.explanation,
                self.topic.examples,
                self.topic.exercises,
                self.topic.solutions,
                self.topic.practice_questions,
                self.topic.practice_solutions,
            )
        )


class SyllabusRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def import_json(self, path: str | Path) -> BoardSyllabus:
        source_path = Path(path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Phase11Error(f"Unable to read syllabus JSON: {exc}") from exc
        syllabus = BoardSyllabus.from_dict(payload)
        target = self.root / f"{syllabus.key}.json"
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return syllabus

    def install_payload(self, payload: Mapping[str, Any]) -> BoardSyllabus:
        syllabus = BoardSyllabus.from_dict(payload)
        target = self.root / f"{syllabus.key}.json"
        target.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return syllabus

    def all(self, board: str | None = None) -> list[BoardSyllabus]:
        results: list[BoardSyllabus] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                syllabus = BoardSyllabus.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if board is None or syllabus.board.casefold() == board.casefold():
                    results.append(syllabus)
            except (OSError, json.JSONDecodeError, Phase11Error):
                continue
        return results

    def find(
        self, *, board: str = "GSEB", medium: str, standard: int, subject: str
    ) -> BoardSyllabus | None:
        if not subject:
            return None
        subject_clean = clean_student_text(subject, max_length=100)
        canonical_subject = SUBJECT_ALIASES.get(subject_clean.casefold(), subject_clean)
        needle = (board.casefold(), medium.casefold(), int(standard), canonical_subject.casefold())
        for syllabus in self.all(board=board):
            if (
                syllabus.board.casefold(),
                syllabus.medium.casefold(),
                syllabus.standard,
                syllabus.subject.casefold(),
            ) == needle:
                return syllabus
        return None


    def lookup_topic(
        self,
        *,
        message: str,
        context: StudentLearningContext,
    ) -> SyllabusTopicMatch | None:
        # Prefer the student's explicit message over stale context and choose the
        # most-specific matching topic instead of the first generic substring.
        syllabus = self.find(
            board=context.board,
            medium=context.medium,
            standard=context.standard,
            subject=context.current_subject,
        )
        if syllabus is None:
            return None

        message_text = _normalize_syllabus_lookup_text(message)
        chapter_context = _normalize_syllabus_lookup_text(context.current_chapter)
        topic_context = _normalize_syllabus_lookup_text(context.current_topic)
        semester_chapter = _normalize_syllabus_lookup_text(
            _semester_chapter_reference(message)
        )

        chapter_signals: dict[str, tuple[bool, bool]] = {}
        for chapter in syllabus.chapters:
            chapter_title = _normalize_syllabus_lookup_text(chapter.title)
            chapter_number = _normalize_syllabus_lookup_text(chapter.number)
            context_aliases = {
                chapter_title,
                chapter_number,
                _normalize_syllabus_lookup_text(f"chapter {chapter.number}"),
                _normalize_syllabus_lookup_text(f"chap {chapter.number}"),
                _normalize_syllabus_lookup_text(f"ch {chapter.number}"),
                _normalize_syllabus_lookup_text(f"પાઠ {chapter.number}"),
                _normalize_syllabus_lookup_text(f"અધ્યાય {chapter.number}"),
            }
            context_match = bool(chapter_context) and chapter_context in context_aliases
            message_match = _contains_syllabus_phrase(message_text, chapter_title)
            if semester_chapter:
                message_match = message_match or semester_chapter == chapter_number
            if chapter_number:
                message_match = message_match or any(
                    _contains_syllabus_phrase(
                        message_text,
                        _normalize_syllabus_lookup_text(prefix),
                    )
                    for prefix in (
                        f"chapter {chapter.number}",
                        f"chap {chapter.number}",
                        f"ch {chapter.number}",
                        f"unit {chapter.number}",
                        f"lesson {chapter.number}",
                        f"પાઠ {chapter.number}",
                        f"અધ્યાય {chapter.number}",
                    )
                )
            chapter_signals[chapter.chapter_id] = (context_match, message_match)

        message_candidates: list[
            tuple[tuple[int, int, int, int, int, int], SyllabusTopicMatch]
        ] = []
        context_candidates: list[
            tuple[tuple[int, int, int, int], SyllabusTopicMatch]
        ] = []

        for chapter_index, chapter in enumerate(syllabus.chapters):
            chapter_context_match, chapter_message_match = chapter_signals.get(
                chapter.chapter_id, (False, False)
            )
            for topic_index, topic in enumerate(chapter.topics):
                topic_title = _normalize_syllabus_lookup_text(topic.title)
                topic_terms: list[str] = []
                for raw_term in (topic.title, *topic.aliases):
                    normalized_term = _normalize_syllabus_lookup_text(raw_term)
                    if normalized_term and normalized_term not in topic_terms:
                        topic_terms.append(normalized_term)

                # Stored exercise and practice templates are explicit syllabus
                # signals too.  A pasted homework question often omits the
                # chapter/topic name, so title-and-alias-only routing loses the
                # validated solution even though that exact question is installed.
                question_groups = (
                    ("message-exercise-template", topic.exercises),
                    ("message-practice-template", topic.practice_questions),
                )
                for matched_by, raw_questions in question_groups:
                    for raw_question in raw_questions:
                        question_term = _normalize_syllabus_lookup_text(raw_question)
                        if not question_term or not _contains_syllabus_phrase(
                            message_text,
                            question_term,
                        ):
                            continue
                        score = (
                            2,
                            int(message_text == question_term),
                            len(question_term.split()),
                            len(question_term),
                            int(chapter_message_match or chapter_context_match),
                            -((chapter_index * 1000) + topic_index),
                        )
                        message_candidates.append(
                            (
                                score,
                                SyllabusTopicMatch(
                                    syllabus=syllabus,
                                    chapter=chapter,
                                    topic=topic,
                                    matched_by=matched_by,
                                ),
                            )
                        )

                if not topic_terms:
                    continue

                for topic_term in topic_terms:
                    specificity_words = len(topic_term.split())
                    specificity_chars = len(topic_term)

                    if _contains_syllabus_phrase(message_text, topic_term):
                        exact_message = int(message_text == topic_term)
                        score = (
                            1,
                            exact_message,
                            specificity_words,
                            specificity_chars,
                            int(chapter_message_match),
                            -((chapter_index * 1000) + topic_index),
                        )
                        message_candidates.append(
                            (
                                score,
                                SyllabusTopicMatch(
                                    syllabus=syllabus,
                                    chapter=chapter,
                                    topic=topic,
                                    matched_by=(
                                        "message-topic-specific"
                                        if topic_term == topic_title
                                        else "message-topic-alias"
                                    ),
                                ),
                            )
                        )

                    context_match = bool(topic_context) and (
                        topic_context == topic_term
                        or _contains_syllabus_phrase(topic_context, topic_term)
                    )
                    if context_match:
                        score = (
                            int(topic_context == topic_term),
                            specificity_words,
                            specificity_chars,
                            int(chapter_context_match),
                        )
                        context_candidates.append(
                            (
                                score,
                                SyllabusTopicMatch(
                                    syllabus=syllabus,
                                    chapter=chapter,
                                    topic=topic,
                                    matched_by=(
                                        "context-topic-fallback"
                                        if topic_term == topic_title
                                        else "context-topic-alias"
                                    ),
                                ),
                            )
                        )

        if message_candidates:
            return max(message_candidates, key=lambda item: item[0])[1]

        # A chapter-level request (for example, "Chapter 1 test") may not name
        # one topic.  Return a representative topic while preserving the exact
        # matched chapter so the renderer can build a balanced chapter response.
        for chapter in syllabus.chapters:
            chapter_context_match, chapter_message_match = chapter_signals.get(
                chapter.chapter_id, (False, False)
            )
            if chapter_message_match and chapter.topics:
                return SyllabusTopicMatch(
                    syllabus=syllabus,
                    chapter=chapter,
                    topic=chapter.topics[0],
                    matched_by="message-chapter",
                )

        if context_candidates and _message_allows_context_topic_fallback(message_text):
            return max(context_candidates, key=lambda item: item[0])[1]

        # Profile context can still support a generic chapter request even when
        # no topic was saved, but must not hijack an unrelated academic question.
        if _message_allows_context_topic_fallback(message_text):
            for chapter in syllabus.chapters:
                chapter_context_match, _ = chapter_signals.get(
                    chapter.chapter_id, (False, False)
                )
                if chapter_context_match and chapter.topics:
                    return SyllabusTopicMatch(
                        syllabus=syllabus,
                        chapter=chapter,
                        topic=chapter.topics[0],
                        matched_by="context-chapter-fallback",
                    )

        return None

    def overall_coverage(self, board: str | None = None) -> dict[str, Any]:
        syllabi = self.all(board=board)
        topics = sum(item.coverage()["topics"] for item in syllabi)
        content = sum(item.coverage()["content_topics"] for item in syllabi)
        official = sum(item.coverage()["official_topics"] for item in syllabi)
        return {
            "syllabi": len(syllabi),
            "topics": topics,
            "content_topics": content,
            "official_topics": official,
            "coverage_percent": round((content / topics) * 100, 2) if topics else 0.0,
            "official_coverage_percent": round((official / topics) * 100, 2) if topics else 0.0,
        }


GSEBSyllabus = BoardSyllabus
GSEBSyllabusRepository = SyllabusRepository


def canonicalize_installed_syllabus_context(
    context: StudentLearningContext,
    syllabus_repository: SyllabusRepository,
) -> StudentLearningContext:
    """Repair stored synthetic chapter labels using the installed syllabus."""

    syllabus = syllabus_repository.find(
        board=context.board,
        medium=context.medium,
        standard=context.standard,
        subject=context.current_subject,
    )
    if syllabus is None and context.current_subject.casefold() in {"science", "science & technology"}:
        syllabus = syllabus_repository.find(
            board=context.board,
            medium=context.medium,
            standard=context.standard,
            subject="Science & Technology",
        )
    if syllabus is None:
        return context

    changes: dict[str, Any] = {}
    if syllabus.subject != context.current_subject:
        changes["current_subject"] = syllabus.subject

    if context.current_chapter:
        current_chapter = context.current_chapter.strip().casefold()
        chapter_token_normalized = _normalize_syllabus_lookup_text(current_chapter)
        canonical_chapter = next(
            (
                item
                for item in syllabus.chapters
                if current_chapter
                in {
                    item.title.strip().casefold(),
                    item.number.strip().casefold(),
                    f"chapter {item.number}".casefold(),
                }
                or chapter_token_normalized
                in {
                    _normalize_syllabus_lookup_text(item.number),
                    _normalize_syllabus_lookup_text(item.title),
                    _normalize_syllabus_lookup_text(f"chapter {item.number}"),
                }
            ),
            None,
        )
        if canonical_chapter and canonical_chapter.title != context.current_chapter:
            changes["current_chapter"] = canonical_chapter.title
            valid_topics = {item.title for item in canonical_chapter.topics}
            if context.current_topic not in valid_topics:
                changes["current_topic"] = ""

    if not changes:
        return context

    return replace(context, **changes).validate()



_SYLLABUS_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class SyllabusTutorRequest:
    intent: str = "explain"
    requested_count: int = 1
    explicit_count: bool = False
    include_answers: bool = False
    requires_provider_review: bool = False


def classify_syllabus_tutor_request(message: str) -> SyllabusTutorRequest:
    """Classify a syllabus request without guessing at open-ended student work."""

    requested = _normalize_syllabus_lookup_text(message)
    padded = f" {requested} "

    def contains_any(phrases: Sequence[str]) -> bool:
        return any(f" {phrase} " in padded for phrase in phrases)

    evaluation_phrases = (
        "check my answer",
        "check this answer",
        "is my answer correct",
        "is this answer correct",
        "is this correct",
        "is it correct",
        "my attempt",
        "review my answer",
        "evaluate my answer",
        "mark my answer",
        "correct my answer",
    )
    explain_phrases = (
        "explain",
        "define",
        "definition",
        "what is",
        "what are",
        "meaning",
        "understand",
        "samjhao",
    )
    example_phrases = ("example", "examples", "illustration", "illustrations")
    test_phrases = (
        "test",
        "quiz",
        "mcq",
        "question paper",
        "test paper",
        "exam paper",
        "exam",
        "paper banao",
        "test banao",
        "syllabus paper",
        "final exam paper",
    )
    practice_phrases = ("practice", "exercise", "exercises", "practice questions")
    solution_phrases = ("solution", "solutions", "solve", "final answer", "answer key")
    hint_phrases = (
        "hint",
        "hints",
        "give me a hint",
        "give me only one hint",
        "hint only",
        "need a hint",
        "help me start",
    )
    summary_phrases = ("revision", "revise", "summary", "summarize", "key points")
    homework_phrases = ("give homework", "homework questions", "assign homework")

    has_explain = contains_any(explain_phrases)
    has_examples = contains_any(example_phrases)
    explicit_hint_request = bool(
        re.match(
            r"^(?:please\s+)?(?:"
            r"(?:give|show)\s+me\s+(?:(?:only|just)\s+)?"
            r"(?:(?:a|an|\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+)?hints?\b"
            r"|(?:i\s+)?need\s+(?:a\s+|one\s+)?hints?\b"
            r"|hints?\s+only\b"
            r"|help\s+me\s+start\b"
            r")",
            requested,
        )
    )
    explicit_explain_request = bool(
        re.match(
            r"^(?:please\s+)?(?:explain|define|what\s+(?:is|are))\b",
            requested,
        )
    )
    explicit_solution_request = bool(
        re.match(r"^(?:please\s+)?(?:solve|answer)\b", requested)
    ) or any(
        phrase in requested
        for phrase in (
            "solve this homework question",
            "solve the following question",
            "give me the final answer",
        )
    )
    if any(phrase in requested for phrase in evaluation_phrases):
        intent = "evaluate"
    elif explicit_hint_request:
        intent = "hint"
    elif explicit_solution_request:
        intent = "solution"
    elif explicit_explain_request:
        intent = "explain"
    elif contains_any(test_phrases):
        intent = "test"
    elif contains_any(hint_phrases):
        intent = "hint"
    elif contains_any(homework_phrases):
        intent = "homework"
    elif contains_any(practice_phrases):
        intent = "practice"
    elif contains_any(solution_phrases):
        intent = "solution"
    elif has_examples and not has_explain:
        intent = "example"
    elif contains_any(summary_phrases):
        intent = "summary"
    else:
        intent = "explain"

    count_pattern = re.compile(
        r"\b(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
        r"(?:short\s+|simple\s+|practice\s+)?"
        r"(?:examples?|questions?|exercises?|mcqs?|items?|problems?|hints?)\b"
    )
    count_match = count_pattern.search(requested)
    explicit_count = count_match is not None or " all examples " in padded
    if count_match:
        raw_count = count_match.group(1)
        requested_count = (
            int(raw_count) if raw_count.isdigit() else _SYLLABUS_COUNT_WORDS[raw_count]
        )
    elif " all examples " in padded:
        requested_count = 10
    else:
        requested_count = {
            "test": 5,
            "practice": 3,
            "homework": 2,
            "summary": 3,
        }.get(intent, 1)
    requested_count = max(1, min(requested_count, 10))

    include_answers = any(
        phrase in requested
        for phrase in (
            "with answer",
            "with answers",
            "and answer",
            "and answers",
            "answer key",
            "answers included",
            "include answer",
            "include answers",
            "with solution",
            "with solutions",
        )
    )
    return SyllabusTutorRequest(
        intent=intent,
        requested_count=requested_count,
        explicit_count=explicit_count,
        include_answers=include_answers,
        requires_provider_review=intent in {"evaluate"},
    )


def _numbered_lines(items: Sequence[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _topic_question_bank(
    topic: SyllabusTopic,
    *,
    prefer_solved: bool = False,
) -> list[tuple[str, str]]:
    exercises = [
        (
            question,
            topic.solutions[index] if index < len(topic.solutions) else "",
        )
        for index, question in enumerate(topic.exercises)
    ]
    practice = [
        (
            question,
            (
                topic.practice_solutions[index]
                if index < len(topic.practice_solutions)
                else ""
            ),
        )
        for index, question in enumerate(topic.practice_questions)
    ]
    ordered = exercises + practice if prefer_solved else practice + exercises
    unique: list[tuple[str, str]] = []
    seen: set[str] = set()
    for question, guide in ordered:
        key = question.casefold()
        if key not in seen:
            seen.add(key)
            unique.append((question, guide))
    return unique


def _chapter_question_bank(
    chapter: SyllabusChapter,
    *,
    prefer_solved: bool = False,
) -> list[tuple[str, str, str]]:
    per_topic = [
        (topic.title, _topic_question_bank(topic, prefer_solved=prefer_solved))
        for topic in chapter.topics
    ]
    balanced: list[tuple[str, str, str]] = []
    index = 0
    while True:
        added = False
        for topic_title, questions in per_topic:
            if index < len(questions):
                question, guide = questions[index]
                balanced.append((topic_title, question, guide))
                added = True
        if not added:
            break
        index += 1
    return balanced


def _requested_question_index(
    bank: Sequence[tuple[str, str]],
    message: str,
) -> int:
    requested_text = _normalize_syllabus_lookup_text(message)
    question_number_match = re.search(
        r"\b(?:question|q)\s*(\d{1,2})\b",
        requested_text,
    )
    selected_index = (
        int(question_number_match.group(1)) - 1
        if question_number_match
        else -1
    )
    if 0 <= selected_index < len(bank):
        return selected_index

    for index, (question, _) in enumerate(bank):
        norm_q = _normalize_syllabus_lookup_text(question)
        if norm_q and (_contains_syllabus_phrase(requested_text, norm_q) or _contains_syllabus_phrase(norm_q, requested_text)):
            return index

    hint_stop_words = _CONTEXT_FALLBACK_WORDS | {
        "give", "me", "only", "just", "one", "two", "three", "hint", "hints",
        "for", "this", "homework", "question", "solve", "solution", "answer",
        "what", "why", "how", "is", "are", "do", "does", "did", "the", "a", "an",
    }
    requested_tokens = {
        token for token in requested_text.split()
        if len(token) > 2 and token not in hint_stop_words
    }

    best_index = -1
    best_overlap = 0
    if requested_tokens:
        for index, (question, _) in enumerate(bank):
            q_tokens = {
                token for token in _normalize_syllabus_lookup_text(question).split()
                if len(token) > 2 and token not in hint_stop_words
            }
            overlap = len(requested_tokens & q_tokens)
            if overlap >= 2 and overlap > best_overlap:
                best_overlap = overlap
                best_index = index

    return best_index


def _student_review_answer(message: str) -> str:
    raw = clean_student_text(message, max_length=4_000)
    markers = list(
        re.finditer(
            r"\b(?:my answer|my attempt)\s*:\s*",
            raw,
            flags=re.IGNORECASE,
        )
    )
    if not markers:
        return ""
    answer = raw[markers[-1].end():]
    answer = re.split(
        r"\s+(?:is\s+(?:my|this)\s+answer\s+correct|is\s+this\s+correct|"
        r"is\s+it\s+correct|am\s+i\s+correct)\b",
        answer,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return answer.strip(" \t\r\n.?!")
_SHORT_NUMERIC_REVIEW_RE = re.compile(
    r"^\s*([−-]?\s*₹?\s*\d[\d,]*(?:\.\d+)?"
    r"(?:\s*/\s*[−-]?\s*\d[\d,]*(?:\.\d+)?)?)\s*"
    r"(?:%|percent|percentage|degrees?|years?|months?|days?|students?|items?|rupees?)?\s*$",
    flags=re.IGNORECASE,
)
_FINAL_NUMERIC_SOLUTION_RE = re.compile(
    r"([−-]?\s*₹?\s*\d[\d,]*(?:\.\d+)?"
    r"(?:\s*/\s*[−-]?\s*\d[\d,]*(?:\.\d+)?)?)\s*"
    r"(?:%|percent|percentage|degrees?|years?|months?|days?|students?|items?|rupees?)?"
    r"\s*[.!]?\s*$",
    flags=re.IGNORECASE,
)


def _canonical_numeric_review_value(value: str) -> str:
    return (
        value.replace("−", "-")
        .replace("₹", "")
        .replace(",", "")
        .replace(" ", "")
    )


def _short_numeric_review_value(value: str) -> str:
    match = _SHORT_NUMERIC_REVIEW_RE.fullmatch(value.strip())
    return _canonical_numeric_review_value(match.group(1)) if match else ""


def _final_numeric_solution_value(solution: str) -> str:
    match = _FINAL_NUMERIC_SOLUTION_RE.search(solution)
    return _canonical_numeric_review_value(match.group(1)) if match else ""



def _std7_magnet_material_classification_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide the installed Std 7 magnet material classification locally."""

    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("magnet" in clean_question or "magnetic" in clean_question)
        and "iron" in clean_question
        and ("aluminium" in clean_question or "aluminum" in clean_question)
        and ("wooden" in clean_question or "wood" in clean_question or "ruler" in clean_question)
        and ("attract" in clean_question or "attracted" in clean_question or "attracts" in clean_question or "attraction" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer).replace("aluminum", "aluminium")
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]
    tokens = clean_student.split()

    def _claim_polarity(alias_set: set[str]) -> set[bool]:
        # Look forward from the material name to the first attraction/magnetic
        # predicate. Negation only counts when it appears before that predicate,
        # so the later "not attracted" for aluminium/wood does not accidentally
        # negate the earlier "iron nail is attracted strongly" clause.
        polarities: set[bool] = set()
        for index, token in enumerate(tokens):
            if token not in alias_set:
                continue
            window = tokens[index : min(len(tokens), index + 12)]
            predicate_index: int | None = None
            for offset, item in enumerate(window):
                if item in {"attract", "attracted", "attracts", "magnetic"}:
                    predicate_index = offset
                    break
            if predicate_index is None:
                for offset, item in enumerate(window[1:]):
                    if item in {"not", "no", "non", "neither"}:
                        polarities.add(False)
                        break
                continue
            before_predicate = set(window[:predicate_index])
            negated = bool(before_predicate & {"not", "no", "non", "neither"})
            polarities.add(not negated)
        return polarities

    def _positive_claim(alias_set: set[str]) -> bool:
        return True in _claim_polarity(alias_set)

    def _negative_claim(alias_set: set[str]) -> bool:
        return False in _claim_polarity(alias_set)

    iron_aliases = {"iron", "nail"}
    aluminium_aliases = {"aluminium", "spoon"}
    wooden_aliases = {"wooden", "wood", "ruler"}

    if _positive_claim(aluminium_aliases) or _positive_claim(wooden_aliases):
        return False
    if _negative_claim(iron_aliases):
        return False
    if (
        _positive_claim(iron_aliases)
        and _negative_claim(aluminium_aliases)
        and _negative_claim(wooden_aliases)
    ):
        return True
    return None


def _std7_magnet_force_strongest_location_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide where magnetic force is strongest question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("magnet" in clean_question or "magnetic" in clean_question)
        and ("strongest" in clean_question or "force" in clean_question or "where" in clean_question)
    ):
        return None

    if not ("strongest" in clean_question or ("where" in clean_question and "force" in clean_question)):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    middle_indicators = {"middle", "centre", "center", "central", "midway", "between"}
    has_middle_claim = bool(tokens & middle_indicators)

    pole_indicators = {"pole", "poles", "end", "ends", "terminal", "terminals"}
    has_pole_claim = bool(tokens & pole_indicators) or "north and south" in clean_student

    if has_middle_claim and not has_pole_claim:
        return False
    if has_middle_claim and ("strongest in the middle" in clean_student or "strongest in the centre" in clean_student or "strongest in the center" in clean_student):
        return False

    if has_pole_claim and not has_middle_claim:
        return True

    return None


def _std7_magnetic_field_lines_density_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide magnetic field line density / crowded lines question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("closely spaced" in clean_question or "crowded" in clean_question or "field line" in clean_question or "field-line" in clean_question or "lines" in clean_question)
        and ("field" in clean_question or "magnetic" in clean_question or "diagram" in clean_question)
    ):
        return None

    if not ("field line" in clean_question or "field-line" in clean_question or "closely spaced" in clean_question or "crowded" in clean_question):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    weak_indicators = {"weak", "weaker", "smallest", "small", "less"}
    strong_indicators = {"strong", "stronger", "great", "greater", "greatest", "maximum", "high", "denser"}

    has_weak_claim = bool(tokens & weak_indicators)
    has_strong_claim = bool(tokens & strong_indicators)

    if has_weak_claim and not has_strong_claim:
        return False
    if "weaker magnetic field" in clean_student or "weak magnetic field" in clean_student or "weaker field" in clean_student or "weak field" in clean_student:
        return False

    if has_strong_claim and not has_weak_claim:
        return True

    return None


def _std7_magnet_unlike_poles_interaction_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide unlike poles (north and south) interaction question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("north pole" in clean_question and "south pole" in clean_question)
        or "unlike poles" in clean_question
        or ("unlike" in clean_question and "pole" in clean_question)
        or ("opposite" in clean_question and "pole" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    repel_indicators = {"repel", "repels", "repulsion", "repelling", "push", "pushed", "pushing"}
    attract_indicators = {"attract", "attracts", "attraction", "attracting", "pull", "pulled", "pulling"}

    has_repel_claim = bool(tokens & repel_indicators) or "push away" in clean_student
    has_attract_claim = bool(tokens & attract_indicators) or "move toward" in clean_student or "moves toward" in clean_student

    if "two south poles attract" in clean_student or "two north poles attract" in clean_student or bool(re.search(r"\blike poles attract\b", clean_student)):
        return False

    if "unlike poles attract" in clean_student or ("north" in clean_student and "south" in clean_student and "attract" in clean_student):
        return True

    if has_repel_claim and not has_attract_claim:
        return False
    if "repel each other" in clean_student or "repel" in clean_student or "push away" in clean_student:
        if not has_attract_claim:
            return False

    if has_attract_claim and not has_repel_claim:
        return True

    return None


def _std7_magnet_like_poles_interaction_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide like poles (two south poles / two north poles) interaction question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        "two south poles" in clean_question
        or "two north poles" in clean_question
        or "like poles" in clean_question
        or ("same" in clean_question and "pole" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    attract_indicators = {"attract", "attracts", "attraction", "attracting", "pull", "pulled", "pulling"}
    repel_indicators = {"repel", "repels", "repulsion", "repelling", "push", "pushed", "pushing"}

    has_attract_claim = bool(tokens & attract_indicators) or "move toward" in clean_student or "moves toward" in clean_student
    has_repel_claim = bool(tokens & repel_indicators) or "push away" in clean_student

    if has_attract_claim and not has_repel_claim:
        return False
    if "attract each other" in clean_student or "attract" in clean_student:
        if not has_repel_claim:
            return False

    if has_repel_claim and not has_attract_claim:
        return True

    return None


def _std7_water_states_classification_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide the installed Std 7 water physical states classification locally."""

    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        "water" in clean_question
        and ("state" in clean_question or "states" in clean_question or "phase" in clean_question or "phases" in clean_question or "form" in clean_question or "forms" in clean_question)
        and ("three" in clean_question or "3" in clean_question or "physical" in clean_question or "common" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer).replace("vapor", "vapour")
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    # Normalize "water vapour" to a single token so "water" in "water vapour" is not confused with liquid water
    norm_student = clean_student.replace("water vapour", "watervapour")
    tokens = set(norm_student.split())

    has_solid = bool(tokens & {"solid", "ice"})
    has_liquid = bool(tokens & {"liquid", "water"})
    has_gas = bool(tokens & {"gas", "gaseous", "vapour", "watervapour", "steam"})

    if has_solid and has_liquid and has_gas:
        return True

    return False


def _std7_npk_nutrients_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide NPK plant nutrients question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("n, p" in clean_question or "n,p" in clean_question or "npk" in clean_question or "represented by n" in clean_question)
        and ("nutrient" in clean_question or "nutrients" in clean_question or "major" in clean_question or "element" in clean_question or "elements" in clean_question or "stand" in clean_question or "plant" in clean_question or "soil" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    has_nitrogen = "nitrogen" in tokens or "nitrogene" in clean_student
    has_phosphorus = "phosphorus" in tokens or "phosphorus" in clean_student or "phosphorous" in clean_student
    has_potassium = "potassium" in tokens or "potasium" in clean_student or "kalium" in clean_student

    wrong_elements = {
        "neon", "krypton", "argon", "helium", "xenon", "radon", "sodium", "calcium",
        "magnesium", "iron", "copper", "zinc", "carbon", "oxygen", "hydrogen"
    }
    has_wrong_element = bool(tokens & wrong_elements)

    if has_wrong_element or not (has_nitrogen and has_phosphorus and has_potassium):
        return False

    return True


def _std7_oscillatory_motion_example_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide oscillatory motion example question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not ("oscillatory" in clean_question and "motion" in clean_question):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_motion_types = {
        "straight", "linear", "rectilinear", "circular", "rotational", "random"
    }

    if bool(tokens & wrong_motion_types):
        return False

    valid_oscillatory_indicators = {
        "swing", "pendulum", "fro", "forth", "vibration", "vibrating", "vibrate", "vibrates", "guitar", "cradle", "tuning", "fork", "oscillation", "oscillates", "bob", "clock"
    }

    if bool(tokens & valid_oscillatory_indicators):
        return True

    return False


def _std7_filtration_insoluble_solid_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide filtration using filter paper question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("filter paper" in clean_question or "filtration" in clean_question)
        and ("insoluble" in clean_question or "solid" in clean_question or "liquid" in clean_question or "method" in clean_question)
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_methods = {
        "evaporation", "sedimentation", "decantation", "distillation", "handpicking", "sieving", "winnowing", "threshing", "magnetic"
    }

    if bool(tokens & wrong_methods):
        return False

    valid_filtration_tokens = {"filtration", "filtering", "filter"}
    if bool(tokens & valid_filtration_tokens):
        return True

    return False


def _std7_natural_satellite_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide natural satellite definition/example question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not ("satellite" in clean_question and ("natural" in clean_question or "example" in clean_question or "what is" in clean_question)):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_satellite_claims = {
        "manmade", "artificial", "human", "machine", "bus", "car", "robot", "vehicle", "rocket", "airplane"
    }

    if "man made" in clean_student or "man-made" in clean_student or bool(tokens & wrong_satellite_claims):
        return False

    if "moon" in tokens or "celestial" in tokens or ("revolves" in tokens and "planet" in tokens) or ("orbits" in tokens and "planet" in tokens):
        return True

    return False


def _std7_speed_average_formula_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide average speed formula / dividing distance by time question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("total distance" in clean_question or "dividing" in clean_question or "distance" in clean_question)
        and ("total time" in clean_question or "time" in clean_question or "speed" in clean_question)
    ):
        return None

    if not (
        "dividing total distance" in clean_question
        or "quantity is obtained by dividing" in clean_question
        or ("total distance" in clean_question and "total time" in clean_question)
        or ("distance" in clean_question and "time" in clean_question and ("dividing" in clean_question or "divided" in clean_question or "quantity" in clean_question))
    ):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_operation_indicators = {"multiply", "multiplying", "multiplied", "product"}
    has_wrong_operation = bool(tokens & wrong_operation_indicators) or "product of" in clean_student or "distance times time" in clean_student

    if has_wrong_operation:
        return False

    valid_speed_indicators = {
        "dividing", "divided", "divide", "division", "speed", "average"
    }
    has_valid_speed = bool(tokens & valid_speed_indicators) or "/" in clean_student or "distance by time" in clean_student

    if has_valid_speed and not has_wrong_operation:
        return True

    return None


def _std7_unbalanced_force_effect_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide what an unbalanced force can change about a moving body question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("unbalanced" in clean_question or "unbalanced force" in clean_question)
        and ("force" in clean_question or "change" in clean_question or "moving body" in clean_question or "body" in clean_question)
    ):
        return None

    if not ("unbalanced force" in clean_question or ("unbalanced" in clean_question and "change" in clean_question)):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    negation_words = {"never", "cannot", "no", "not", "without", "none"}
    has_negation = bool(tokens & negation_words) or "can not" in clean_student or "no change" in clean_student or "does not change" in clean_student or "will not change" in clean_student

    if "never change" in clean_student or "cannot change" in clean_student or "can not change" in clean_student or "no change" in clean_student or "does not change" in clean_student or "will not change" in clean_student:
        return False

    if has_negation and ("never change the motion" in clean_student or "cannot change motion" in clean_student or "no change in motion" in clean_student or "cannot change speed" in clean_student or "never change speed" in clean_student):
        return False

    valid_change_targets = {
        "speed", "direction", "shape", "state", "motion", "velocity", "path", "accelerate", "acceleration"
    }
    has_valid_target = bool(tokens & valid_change_targets) or "state of motion" in clean_student

    if has_valid_target and not (has_negation and ("never" in clean_student or "cannot" in clean_student or "no change" in clean_student or "does not" in clean_student)):
        return True

    return None


def _std7_clock_hands_motion_type_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide motion type of hands of a mechanical clock question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("clock" in clean_question or "mechanical clock" in clean_question)
        and ("hands" in clean_question or "motion" in clean_question or "type" in clean_question)
    ):
        return None

    if not (("hands" in clean_question and "clock" in clean_question) or "mechanical clock" in clean_question):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_motion_types = {
        "straight", "linear", "rectilinear", "oscillatory", "random"
    }
    has_wrong_motion = bool(tokens & wrong_motion_types) or "straight line" in clean_student or "straight-line" in clean_student

    if has_wrong_motion:
        return False

    valid_motion_types = {
        "circular", "rotational", "rotary", "revolution", "periodic"
    }
    has_valid_motion = bool(tokens & valid_motion_types)

    if has_valid_motion and not has_wrong_motion:
        return True

    return None


def _std7_motion_reference_point_definition_decision(
    student_answer: str,
    question: str,
) -> bool | None:
    """Decide motion relative to a reference point definition question evaluation locally."""
    clean_question = _normalize_syllabus_lookup_text(question)
    if not (
        ("reference point" in clean_question or "reference" in clean_question)
        and ("motion" in clean_question or "relative" in clean_question or "meant" in clean_question or "position" in clean_question)
    ):
        return None

    if not ("reference point" in clean_question and ("motion" in clean_question or "relative" in clean_question)):
        return None

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    wrong_position_claims = {
        "never changes position", "never change position", "does not change position",
        "no change in position", "without changing position", "position stays same",
        "position does not change", "same position", "always at rest", "no position change"
    }
    has_wrong_claim = any(claim in clean_student for claim in wrong_position_claims) or ("never" in clean_student and "change" in clean_student and "position" in clean_student)

    if has_wrong_claim:
        return False

    valid_position_claims = {
        "changes position", "change in position", "change of position", "changes its position",
        "position changes", "position change", "moving relative"
    }
    has_valid_claim = any(claim in clean_student for claim in valid_position_claims) or ("changes" in tokens and "position" in tokens) or ("change" in tokens and "position" in tokens)

    if has_valid_claim and not has_wrong_claim:
        return True

    return None


def _evaluate_student_answer(
    student_answer: str,
    guide: str,
    question: str,
    topic: SyllabusTopic | None = None,
) -> tuple[str, str]:
    if not student_answer or not guide:
        return (
            "Result: Needs grounded review.",
            "An answer and installed solution are required to evaluate.",
        )


    strict_res = evaluate_strict_short_answer(question, student_answer, guide, 1)
    if strict_res is not None:
        score, status, fb = strict_res
        return f"Result: {status}.", fb

    # 1. Check Yes/No decision
    student_decision = re.match(r"^\s*(yes|no)\b", student_answer.strip(), flags=re.IGNORECASE)
    expected_decision = re.match(r"^\s*(yes|no)\b", guide.strip(), flags=re.IGNORECASE)
    if student_decision and expected_decision:
        if student_decision.group(1).casefold() == expected_decision.group(1).casefold():
            return "Result: Correct.", "Your short answer matches the installed solution decision."
        else:
            return "Result: Incorrect.", "Your short answer does not match the installed solution decision."

    # 2. Check Numeric decision
    student_numeric = _short_numeric_review_value(student_answer)
    expected_numeric = _final_numeric_solution_value(guide)
    if (
        student_numeric
        and expected_numeric
        and _question_supports_short_numeric_review(question)
    ):
        if student_numeric == expected_numeric:
            return "Result: Correct.", "Your short answer matches the installed solution result."
        else:
            return "Result: Incorrect.", "Your short answer does not match the installed solution result."

    clean_student = _normalize_syllabus_lookup_text(student_answer)
    clean_question = _normalize_syllabus_lookup_text(question)

    eval_stop_words = _CONTEXT_FALLBACK_WORDS | {
        "because", "as", "since", "so", "that", "it", "they", "them", "is", "are", "was", "were",
        "be", "been", "being", "have", "has", "had", "do", "does", "did", "the", "a", "an", "and",
        "or", "but", "if", "then", "of", "to", "in", "on", "at", "by", "for", "with", "about",
        "question", "answer", "my", "your", "correct", "true", "false",
        "using", "use", "used", "make", "makes", "made", "get", "gets", "give", "gives", "given",
        "take", "takes", "put", "puts", "find", "finds", "show", "shows", "tell", "tells",
        "created", "create", "creating", "like", "directly", "refer", "refers", "referred",
    }

    all_ref_text = (
        guide
        + " "
        + (topic.explanation if topic else "")
        + " "
        + (" ".join(topic.examples) if topic and topic.examples else "")
    )
    ref_tokens = {
        token
        for token in _normalize_syllabus_lookup_text(all_ref_text).split()
        if len(token) > 2 and token not in eval_stop_words
    }
    student_tokens = {
        token
        for token in clean_student.split()
        if len(token) > 2 and token not in eval_stop_words
    }

    if not ref_tokens:
        return "Result: Needs grounded review.", "Installed solution logic is available for reference."

    matched_tokens = student_tokens & ref_tokens

    short_answer_tokens = {
        token
        for token in clean_student.split()
        if token and token not in eval_stop_words
    }
    clean_guide = _normalize_syllabus_lookup_text(guide)
    expected_short_tokens: set[str] = set()
    grammar_labels = (
        "preposition",
        "adverb",
        "adjective",
        "imperative verb",
        "verb",
        "conjunction",
        "pronoun",
        "modal",
        "prefix",
        "suffix",
        "silent letter",
    )
    for label in grammar_labels:
        if label in clean_question:
            label_pattern = re.escape(label)
            match = re.search(
                rf"\b(?:the\s+)?{label_pattern}\s+(?:is|are)\s+([a-z]+)\b",
                clean_guide,
            )
            if match:
                expected_short_tokens.add(match.group(1))
    sense_match = re.search(r"\bsense\s+of\s+([a-z]+)\b", clean_guide)
    if "what sense" in clean_question and sense_match:
        expected_short_tokens.add(sense_match.group(1))

    if expected_short_tokens and 0 < len(short_answer_tokens) <= 3:
        if short_answer_tokens & expected_short_tokens:
            return (
                "Result: Correct.",
                "Your short answer matches the installed solution.",
            )
        return (
            "Result: Incorrect.",
            "Your short answer does not match the installed solution.",
        )

    wrong_keywords = {
        "colorful", "colourful", "iron", "steel", "plastic", "stone", "fire", "magic",
        "red", "blue", "green", "yellow", "wrong", "fake", "bad", "expensive", "cheap",
        "computer", "game", "mobile", "app", "software", "video",
    }
    has_wrong_claim = bool(student_tokens & wrong_keywords)

    if has_wrong_claim:
        return (
            "Result: Incorrect.",
            "Your answer does not match the key concepts in the installed solution.",
        )

    guide_tokens = {
        token
        for token in _normalize_syllabus_lookup_text(guide).split()
        if len(token) > 2 and token not in eval_stop_words
    }
    matched_guide = student_tokens & guide_tokens

    is_why_question = bool(re.search(r"\bwhy\b", clean_question))
    if is_why_question:
        why_consequence_keywords = {
            "weak", "crop", "failure", "prevent", "yield", "yielding", "grow", "growth", "plants",
            "produce", "production", "ensure", "ensures", "blocked", "necessary", "obtain",
            "spices", "silk", "cotton", "needed", "demand", "supply", "trade", "fall", "fell",
            "conquest", "conquered", "turks", "constantinople",
        }
        method_keywords = {"water", "float", "sink", "bottom", "container", "test"}
        has_consequence = bool(student_tokens & why_consequence_keywords)
        has_method = bool(student_tokens & method_keywords)

        if has_method and not has_consequence:
            return (
                "Result: Partially correct.",
                "Your answer explains how damaged seeds can be identified, but it misses the main reason for separating them before sowing: damaged seeds are hollow and weak and may not grow into healthy plants.",
            )
        elif has_consequence and len(matched_guide) >= 3:
            return (
                "Result: Correct.",
                "Your answer correctly reflects the key concepts in the installed solution.",
            )

    student_ratio = len(matched_tokens) / float(len(student_tokens)) if student_tokens else 0.0

    if len(matched_tokens) >= 5 and student_ratio >= 0.85:
        return (
            "Result: Correct.",
            "Your answer correctly reflects the key concepts in the installed solution.",
        )

    return (
        "Result: Needs grounded review.",
        "Your answer can be compared against the installed solution logic below.",
    )


def _question_supports_short_numeric_review(question: str) -> bool:
    normalized = _normalize_syllabus_lookup_text(question)
    task = re.search(
        r"\b(?:find|calculate|determine|evaluate|solve|what is|how many)\b(.+)$",
        normalized,
    )
    if not task:
        return False
    requested_part = task.group(1)
    return " and " not in requested_part and " both " not in requested_part


def _local_question_hints(
    topic: SyllabusTopic,
    question: str,
    solution: str = "",
) -> list[str]:
    normalized = _normalize_syllabus_lookup_text(question)
    if "multiplicative inverse" in normalized:
        return [
            (
                "Use this installed rule: The multiplicative inverse is the number that makes "
                "the product 1 with the given number. For a fraction, think about swapping the "
                "numerator and denominator while keeping the sign, then stop before writing the "
                "final value."
            ),
            f"Use this learning goal as your boundary: {topic.learning_objectives[0] if topic.learning_objectives else topic.title}",
            "Before finishing, check that your answer would multiply with the given number to make 1.",
            "Write down what the question gives you and what it asks you to produce before continuing.",
            "Break the task into two smaller steps and complete only the first step initially.",
            "Try a simple original example to test whether your reasoning follows the topic rule.",
            "Circle the task word and make sure each part of your response directly serves it.",
            "Check every condition in the question; do not rely on a detail the question never gives.",
            "Explain your first step aloud in one sentence; revise it if the reason is unclear.",
            "Before submitting, remove unrelated details and verify that the response answers the exact question.",
        ]
    hint_stop_words = _CONTEXT_FALLBACK_WORDS | {
        "calculate", "complete", "determine", "find", "given", "identify",
        "name", "show", "state", "using", "value", "values", "which",
    }
    question_tokens = {
        token
        for token in normalized.split()
        if len(token) > 1 and token not in hint_stop_words
    }
    solution_text = _normalize_syllabus_lookup_text(solution)
    explanation_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", topic.explanation)
        if sentence.strip()
        and not (
            solution_text
            and solution_text in _normalize_syllabus_lookup_text(sentence)
        )
    ]
    scored_sentences: list[tuple[int, int]] = []
    for index, sentence in enumerate(explanation_sentences):
        sentence_tokens = {
            token
            for token in _normalize_syllabus_lookup_text(sentence).split()
            if len(token) > 1 and token not in hint_stop_words
        }
        scored_sentences.append((len(question_tokens & sentence_tokens), index))

    matched_indices = [
        index
        for score, index in sorted(scored_sentences, key=lambda item: (-item[0], item[1]))
        if score > 0
    ][:1]
    if not matched_indices and explanation_sentences:
        matched_indices = [0]
    selected_rules = [explanation_sentences[index] for index in sorted(matched_indices)]
    rule_text = " ".join(selected_rules).strip()
    rule_label = "these installed rules" if len(selected_rules) > 1 else "this installed rule"

    if (
        "percent profit" in normalized
        and "cost price" in normalized
        and any(word in normalized for word in ("selling price", "sells", "sold"))
    ):
        next_step = (
            "Express the selling price as (100 + profit rate) percent of CP, substitute the "
            "given selling price, isolate CP symbolically, and stop before evaluating the final result."
        )
    elif re.search(r"\d|[+×÷=₹%]", question):
        next_step = (
            "Apply the quantities and condition from the question to the rule, keep the unknown "
            "as a symbol, and stop before evaluating the final result."
        )
    elif normalized.startswith(("construct ", "draw ")):
        next_step = (
            "Use the rule to choose the first construction step, then check each stated condition "
            "before continuing; do not complete the final construction yet."
        )
    elif normalized.startswith(("compare ", "distinguish ")) or "difference" in normalized:
        next_step = (
            "Apply the rule to each item separately, then write only the comparison structure "
            "without completing the final response."
        )
    elif normalized.startswith(("why ", "how ", "explain ")):
        next_step = (
            "Use the rule as the reason for your first sentence and add one relevant detail from "
            "the question; do not write the complete response yet."
        )
    else:
        next_step = (
            "Apply the rule to the exact details in the question and write only your first reasoning "
            "step, not the final answer."
        )

    first = (
        f"Use {rule_label}: {rule_text} {next_step}"
        if rule_text
        else next_step
    )

    objective = topic.learning_objectives[0] if topic.learning_objectives else topic.title
    return [
        first,
        f"Use this learning goal as your boundary: {objective}",
        "Before finishing, check that every claim has a relevant reason, detail or example.",
        "Write down what the question gives you and what it asks you to produce before continuing.",
        "Break the task into two smaller steps and complete only the first step initially.",
        "Try a simple original example to test whether your reasoning follows the topic rule.",
        "Circle the task word and make sure each part of your response directly serves it.",
        "Check every condition in the question; do not rely on a detail the question never gives.",
        "Explain your first step aloud in one sentence; revise it if the reason is unclear.",
        "Before submitting, remove unrelated details and verify that the response answers the exact question.",
    ]


@dataclass(frozen=True)
class TestPaperScope:
    scope_type: str  # "single_chapter", "multi_chapter", "full_book"
    chapters: list[SyllabusChapter]
    total_marks: int
    duration_minutes: int
    include_answers: bool
    description: str


@dataclass
class StructuredEvaluationRules:
    required_concepts: list[str] = field(default_factory=list)
    forbidden_concepts: list[str] = field(default_factory=list)
    numeric_formula: str = ""
    expected_value: str = ""
    unit: str = ""
    contradiction_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TestPaperQuestionItem:
    question_num: int
    section_title: str
    topic_title: str
    question_text: str
    max_marks: int
    solution_guide: str
    intended_marks: int = 1
    required_concepts: list[str] = field(default_factory=list)
    forbidden_concepts: list[str] = field(default_factory=list)
    numeric_formula: str = ""
    expected_value: str = ""
    unit: str = ""
    contradiction_patterns: list[str] = field(default_factory=list)


def derive_structured_evaluation_rules(
    question_text: str,
    solution_guide: str,
    topic_title: str = "",
) -> StructuredEvaluationRules:
    """Derive centralized structured evaluation rules for a test question across Std 7 Science."""
    q_clean = _normalize_syllabus_lookup_text(question_text)
    g_clean = _normalize_syllabus_lookup_text(solution_guide)
    rules = StructuredEvaluationRules()

    # 1. Average speed / Formula (multiply vs divide)
    if (
        ("total distance" in q_clean or "dividing" in q_clean or "distance" in q_clean)
        and ("total time" in q_clean or "time" in q_clean or "speed" in q_clean)
        and ("dividing" in q_clean or "quantity" in q_clean or "formula" in q_clean or "average speed" in q_clean)
    ):
        rules.required_concepts = ["speed", "divide", "distance", "time", "dividing"]
        rules.forbidden_concepts = ["multiply", "multiplying", "multiplied", "product"]
        rules.contradiction_patterns = [r"\bmultiplying?\b", r"\bproduct of\b", r"\bdistance times time\b"]

    # 2. Unbalanced force effect
    elif "unbalanced" in q_clean and ("force" in q_clean or "change" in q_clean or "body" in q_clean):
        rules.required_concepts = ["speed", "direction", "motion", "shape", "state"]
        rules.forbidden_concepts = ["never change", "cannot change", "can not change", "no change", "does not change", "will not change"]
        rules.contradiction_patterns = [r"\bnever change\b", r"\bcannot change\b", r"\bno change\b", r"\bdoes not change\b"]

    # 3. Mechanical clock hands motion
    elif ("hands" in q_clean and "clock" in q_clean) or "mechanical clock" in q_clean:
        rules.required_concepts = ["circular", "rotational", "rotary"]
        rules.forbidden_concepts = ["straight", "linear", "rectilinear", "oscillatory", "random"]
        rules.contradiction_patterns = [r"\bstraight-?line\b", r"\blinear\b", r"\brectilinear\b", r"\boscillatory\b"]

    # 4. Motion relative to reference point
    elif "reference point" in q_clean and ("motion" in q_clean or "relative" in q_clean):
        rules.required_concepts = ["position", "change", "reference point"]
        rules.forbidden_concepts = ["never changes position", "never change position", "does not change position", "no change in position", "without changing position", "position stays same", "always at rest"]
        rules.contradiction_patterns = [r"\bnever change(s)? position\b", r"\bno change in position\b", r"\bdoes not change position\b"]

    # 5. Bar magnet strongest location (poles vs middle)
    elif ("magnet" in q_clean or "magnetic" in q_clean) and ("strongest" in q_clean or "force" in q_clean or "where" in q_clean):
        rules.required_concepts = ["pole", "poles", "end", "ends"]
        rules.forbidden_concepts = ["middle", "centre", "center", "central", "midway"]
        rules.contradiction_patterns = [r"\bmiddle\b", r"\bcentre\b", r"\bcenter\b", r"\bmidway\b"]

    # 6. Magnetic field line density
    elif ("field line" in q_clean or "field-line" in q_clean or "closely spaced" in q_clean or "crowded" in q_clean) and ("field" in q_clean or "magnetic" in q_clean):
        rules.required_concepts = ["strong", "stronger", "great", "denser"]
        rules.forbidden_concepts = ["weak", "weaker", "smallest", "less"]
        rules.contradiction_patterns = [r"\bweaker?\b", r"\bless\b"]

    # 7. Unlike poles (North & South)
    elif ("north pole" in q_clean and "south pole" in q_clean) or "unlike poles" in q_clean or ("unlike" in q_clean and "pole" in q_clean):
        rules.required_concepts = ["attract", "attracts", "attraction"]
        rules.forbidden_concepts = ["repel", "repels", "repulsion", "repelling", "push away"]
        rules.contradiction_patterns = [r"\brepel\b", r"\brepulsion\b", r"\bpush away\b"]

    # 8. Like poles (Two South / Two North)
    elif "two south poles" in q_clean or "two north poles" in q_clean or "like poles" in q_clean:
        rules.required_concepts = ["repel", "repels", "repulsion"]
        rules.forbidden_concepts = ["attract", "attracts", "attraction", "pull together"]
        rules.contradiction_patterns = [r"\battract\b", r"\battraction\b", r"\bpull together\b"]

    # 9. Filtration vs Evaporation/Separation
    elif ("filter paper" in q_clean or "filtration" in q_clean) and ("insoluble" in q_clean or "solid" in q_clean or "method" in q_clean or "process" in q_clean):
        rules.required_concepts = ["filtration", "filter", "filtering"]
        rules.forbidden_concepts = ["evaporation", "sedimentation", "decantation", "distillation", "handpicking", "sieving", "winnowing"]
        rules.contradiction_patterns = [r"\bevaporation\b", r"\bdecantation\b", r"\bsedimentation\b", r"\bdistillation\b"]

    # 10. NPK Plant Nutrients
    elif ("n, p" in q_clean or "n,p" in q_clean or "npk" in q_clean or "represented by n" in q_clean) and ("nutrient" in q_clean or "nutrients" in q_clean or "major" in q_clean or "stand" in q_clean):
        rules.required_concepts = ["nitrogen", "phosphorus", "potassium"]
        rules.forbidden_concepts = ["neon", "krypton", "argon", "helium", "xenon", "radon", "sodium", "calcium", "magnesium", "iron", "copper", "zinc", "carbon", "oxygen", "hydrogen"]
        rules.contradiction_patterns = [r"\bneon\b", r"\bkrypton\b", r"\bargon\b", r"\bsodium\b", r"\bcalcium\b", r"\bcarbon\b"]

    # 11. Water 3 physical states
    elif "water" in q_clean and ("state" in q_clean or "states" in q_clean or "forms" in q_clean) and ("three" in q_clean or "3" in q_clean or "physical" in q_clean):
        rules.required_concepts = ["solid", "liquid", "gas", "ice", "vapour", "water"]

    # 12. Natural satellite
    elif "satellite" in q_clean and ("natural" in q_clean or "example" in q_clean or "what is" in q_clean):
        rules.required_concepts = ["moon", "celestial"]
        rules.forbidden_concepts = ["manmade", "man made", "artificial", "human", "machine", "rocket", "airplane", "bus"]
        rules.contradiction_patterns = [r"\bman\s*made\b", r"\bman-?made\b", r"\bartificial\b"]

    # 13. Cultural achievement linked with Chalukya period / general cultural achievements
    elif (
        "cultural achievement" in q_clean
        or ("chalukya" in q_clean and "cultural" in q_clean)
        or ("cultural" in q_clean and "achievement" in q_clean)
    ):
        rules.required_concepts = [
            "temple", "temples", "rock-cut cave", "rock cut cave", "rock-cut caves",
            "cave art", "caves", "cave", "sculpture", "sculptures", "painting",
            "paintings", "architecture", "architectural", "art", "arts",
        ]

    # 15. Harsha vs Pulakeshin II expansion/outcome question
    elif (
        ("harshavardhana" in q_clean or "harsha" in q_clean)
        and ("pulakeshin" in q_clean or "deccan" in q_clean or "stopped" in q_clean or "expansion" in q_clean or "narmada" in q_clean)
    ) or (
        "pulakeshin" in g_clean and ("harshavardhana" in g_clean or "harsha" in g_clean)
    ):
        rules.required_concepts = ["pulakeshin"]
        rules.forbidden_concepts = [
            "pulakeshin was defeated",
            "pulakeshin ii was defeated",
            "harsha defeated pulakeshin",
            "harshavardhana defeated pulakeshin",
            "lost to harshavardhana",
            "lost to harsha",
            "pulakeshin was stopped",
            "pulakeshin ii was stopped",
            "harsha stopped pulakeshin",
            "harshavardhana stopped pulakeshin",
        ]
        rules.contradiction_patterns = [
            r"\bpulakeshin(\s+ii|\s+2)?\s+(was\s+)?defeated\s+by\s+harsha(vardhana)?\b",
            r"\bharsha(vardhana)?\s+defeated\s+pulakeshin(\s+ii|\s+2)?\b",
            r"\bpulakeshin(\s+ii|\s+2)?\s+(was\s+)?stopped\s+by\s+harsha(vardhana)?\b",
            r"\bharsha(vardhana)?\s+stopped\s+pulakeshin(\s+ii|\s+2)?\b",
            r"\bpulakeshin(\s+ii|\s+2)?\s+lost\s+to\s+harsha(vardhana)?\b",
        ]

    # 16. MLA full form
    elif "mla" in q_clean and ("stand" in q_clean or "meaning" in q_clean or "full form" in q_clean or "what" in q_clean):
        rules.required_concepts = ["member of legislative assembly", "member of the legislative assembly", "legislative assembly"]
        rules.forbidden_concepts = ["master", "manager", "minister", "administration", "affairs", "land", "local"]
        rules.contradiction_patterns = [r"\bmaster\b", r"\bmanager\b", r"\bminister\b"]

    # 17. Longitude measurement
    elif "longitude" in q_clean and ("measure" in q_clean or "measures" in q_clean):
        rules.required_concepts = ["east or west", "east and west", "east", "west", "prime meridian", "meridian"]
        rules.forbidden_concepts = ["north", "south", "equator", "temperature", "pressure", "altitude", "weight"]
        rules.contradiction_patterns = [r"\bnorth\s+or\s+south\b", r"\bnorth\b", r"\bsouth\b", r"\bequator\b"]

    # 18. Ahmedabad growth factors
    elif "ahmedabad" in q_clean and ("grow" in q_clean or "growth" in q_clean or "factor" in q_clean or "helped" in q_clean):
        rules.required_concepts = [
            "political role", "political", "skilled crafts", "skilled", "crafts", "craft",
            "textile production", "textile", "textiles", "production", "markets", "market",
            "trade", "trading", "route connections", "route", "routes", "connection", "connections",
            "good location", "location", "situated", "geographical"
        ]
        rules.forbidden_concepts = [
            "submarine", "glacier", "volcano", "volcanic", "eruption", "snowfall", "earthquake", "tsunami", "nuclear"
        ]
        rules.contradiction_patterns = [
            r"\bsubmarine\b", r"\bglacier\b", r"\bvolcano\b", r"\beruption\b", r"\bsnowfall\b"
        ]

    # 19. Dynasty following Solankis in medieval Gujarat (Vaghela)
    elif ("vaghela" in g_clean or "vaghela" in q_clean or "followed the solankis" in q_clean):
        rules.required_concepts = ["vaghela", "vaghelas"]
        rules.forbidden_concepts = [
            "mughal", "chola", "gupta", "maratha", "maurya", "mauryan", "slave", "tughlaq", "khilji", "lodhi", "solanki", "chauhan", "rashtrakuta", "pala", "pratihara"
        ]
        rules.contradiction_patterns = [
            r"\bmughals?\b", r"\bcholas?\b", r"\bguptas?\b", r"\bmarathas?\b", r"\bmauryas?\b", r"\bsolankis?\b"
        ]

    # 20. Rajput dynasty strongly associated with medieval Gujarat (Solanki/Chaulukya)
    elif ("solanki" in g_clean or "chaulukya" in g_clean) and ("rajput" in q_clean or "gujarat" in q_clean or "associated" in q_clean or "solanki" in q_clean):
        rules.required_concepts = ["solanki", "chaulukya", "solankis", "chaulukyas"]
        rules.forbidden_concepts = [
            "mughal", "chola", "gupta", "maratha", "maurya", "mauryan", "slave", "tughlaq", "khilji", "lodhi", "vaghela"
        ]
        rules.contradiction_patterns = [
            r"\bmughals?\b", r"\bcholas?\b", r"\bguptas?\b", r"\bmarathas?\b", r"\bmauryas?\b", r"\bvaghelas?\b"
        ]

    # 21. Major physical features of Europe
    elif "europe" in q_clean and ("physical feature" in q_clean or "physical features" in q_clean or "two" in q_clean or "features" in q_clean):
        rules.required_concepts = [
            "peninsulas", "peninsula", "rivers", "river", "alps", "north european plain",
            "rhine", "danube", "scandinavian peninsula", "scandinavian", "mediterranean peninsulas",
            "mediterranean", "mountains", "mountain", "plains", "plain", "plateaus", "plateau",
            "highlands", "highland", "volga", "pyrenees", "urals", "ural"
        ]
        rules.forbidden_concepts = [
            "sahara", "amazon", "himalayas", "himalaya", "gobi", "thar", "nile", "ganges",
            "ganga", "mississippi", "rockies", "andes", "kalahari"
        ]
        rules.contradiction_patterns = [
            r"\bsahara\b", r"\bamazon\b", r"\bhimalayas?\b", r"\bgobi\b", r"\bthar\b",
            r"\bnile\b", r"\bganges\b", r"\bganga\b", r"\bmississippi\b", r"\bandes\b"
        ]

    # 22. Major mountain system forming natural boundary in north (Himalayas)
    elif ("mountain" in q_clean or "boundary" in q_clean or "north" in q_clean) and ("himalayas" in g_clean or "himalaya" in g_clean):
        rules.required_concepts = ["himalayas", "himalaya"]
        rules.forbidden_concepts = ["andes", "alps", "rockies", "pyrenees", "urals", "ural", "karakoram", "vindhya", "satpura", "aravalli", "nilgiri"]
        rules.contradiction_patterns = [r"\bandes\b", r"\balps\b", r"\brockies\b", r"\bpyrenees\b", r"\burals?\b"]

    # 23. Executive role in government/civics
    elif "executive" in q_clean and ("role" in q_clean or "main role" in q_clean or "function" in q_clean or "what is" in q_clean):
        rules.required_concepts = ["implements laws", "implement laws", "implements", "implement", "enforce", "enforces", "executes", "administers", "administration", "policy"]
        rules.forbidden_concepts = ["makes laws", "make laws", "creates laws", "create laws", "passes laws", "pass laws", "judges", "interprets"]
        rules.contradiction_patterns = [r"\b(makes|make|creates?|passes?)\s+laws\b", r"\bjudges?\b", r"\binterprets?\b"]

    # 24. Earlier local time direction (East vs West)
    elif ("earlier" in q_clean or "earlier local time" in q_clean or "earlier local" in q_clean) and ("east" in g_clean or "farther east" in g_clean):
        rules.required_concepts = ["farther east", "further east", "east"]
        rules.forbidden_concepts = ["farther west", "further west", "west"]
        rules.contradiction_patterns = [
            r"\b(farther|further|place)?\s*west\s*(has|is|gets)?\s*(earlier|ahead)\b",
            r"\b(farther|further)?\s*west\b",
        ]

    # 25. Alvars and Nayanars (poet-saints devoted to Vishnu and Shiva)
    elif ("alvars" in q_clean or "nayanars" in q_clean or "poet-saints" in q_clean) or ("alvars" in g_clean or "nayanars" in g_clean):
        rules.required_concepts = ["poet", "saint", "saints", "vishnu", "shiva", "bhakti", "devoted"]
        rules.forbidden_concepts = ["mughal", "emperor", "emperors", "king", "kings", "sultan", "sultans", "british"]
        rules.contradiction_patterns = [r"\bmughals?\b", r"\bemperors?\b", r"\bsultans?\b"]

    # 26. Values emphasized in Sufi traditions
    elif "sufi" in q_clean and ("value" in q_clean or "values" in q_clean or "tradition" in q_clean or "traditions" in q_clean):
        rules.required_concepts = ["love", "service", "devotion", "remembrance", "god", "ethical", "conduct", "humility", "compassion"]
        rules.forbidden_concepts = ["violence", "hatred", "greed", "war", "cruelty", "revenge", "selfishness"]
        rules.contradiction_patterns = [r"\bviolence\b", r"\bhatred\b", r"\bgreed\b", r"\bwar\b"]

    # 27. Access to justice / informal dispute settlement (Q21)
    elif "dispute" in q_clean and ("informal" in q_clean or "settled" in q_clean or "agreement" in q_clean):
        rules.required_concepts = [
            "no", "courts", "court", "formal", "legal", "trial", "investigation", "binding", "judiciary"
        ]
        rules.forbidden_concepts = ["yes", "always", "every dispute can be settled informally"]
        rules.contradiction_patterns = [r"\byes\b", r"\balways\s+(be\s+)?settled\b", r"\bevery\s+dispute\s+can\b"]

    # 28. Artisans importance in medieval cities (Q25)
    elif "artisans" in q_clean and ("important" in q_clean or "medieval" in q_clean or "cities" in q_clean or "role" in q_clean):
        rules.required_concepts = [
            "made", "produced", "goods", "crafts", "textiles", "metalwork", "trade", "economy", "traders", "residents", "courts"
        ]
        rules.forbidden_concepts = ["not useful", "useless", "no role", "no importance", "unimportant", "harmful"]
        rules.contradiction_patterns = [r"\bnot\s+useful\b", r"\buseless\b", r"\bno\s+role\b", r"\bunimportant\b"]

    # 29. Forts importance to regional rulers (Q22)
    elif "forts" in q_clean and ("important" in q_clean or "rulers" in q_clean or "regional" in q_clean or "why" in q_clean):
        rules.required_concepts = [
            "protected", "protect", "capitals", "capital", "routes", "route", "supplies", "people", "control", "political control", "defence", "defense"
        ]
        rules.forbidden_concepts = ["sports", "entertainment", "recreation", "useless", "no importance"]
        rules.contradiction_patterns = [r"\bsports?\b", r"\brecreation\b", r"\buseless\b"]

    # 30. Industry adding value to raw materials (Q23)
    elif "industry" in q_clean and ("value" in q_clean or "raw material" in q_clean or "add value" in q_clean or "adds value" in q_clean):
        rules.required_concepts = [
            "processes", "process", "combines", "combine", "product", "products", "usefulness", "market value", "value", "greater value"
        ]
        rules.forbidden_concepts = ["destroys", "destroy", "reduces value", "no value", "useless"]
        rules.contradiction_patterns = [r"\bdestroys?\b", r"\breduces?\s+value\b", r"\bno\s+value\b"]

    # 31. Major physiographic divisions of India (Q24)
    elif "physiographic" in q_clean or ("divisions" in q_clean and "india" in q_clean):
        rules.required_concepts = [
            "himalayas", "northern plains", "peninsular plateau", "indian desert", "coastal plains", "islands",
            "mountains", "plains", "plateau", "desert", "coasts"
        ]
        rules.forbidden_concepts = ["sahara", "amazon", "andes", "gobi", "rockies"]
        rules.contradiction_patterns = [r"\bsahara\b", r"\bamazon\b", r"\bandes\b", r"\bgobi\b"]

    # 21. "Name one" / "Give one" questions with "any one... is acceptable" in solution guide
    elif "any one" in g_clean and not rules.required_concepts:
        prefix_part = g_clean.split(";")[0] if ";" in g_clean else g_clean.split(".")[0]
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for",
            "with", "of", "and", "or", "because", "it", "they", "them", "this", "that", "from",
            "be", "been", "such", "as", "during", "period", "developed", "example",
            "acceptable", "suitable", "examples", "work", "works", "methods", "any", "one",
        }
        words = [w for w in re.findall(r"\w+", prefix_part) if len(w) > 2 and w not in stop_words]
        if words:
            rules.required_concepts = words

    # 13. Automatic Proper Noun required concepts for factual identity/ruler/place/event questions
    if not rules.required_concepts and re.search(r"\b(who|which ruler|which king|which dynasty|which emperor|which capital|name the|what was the capital)\b", q_clean):
        proper_nouns = [
            w for w in re.findall(r"\b[A-Z][a-zA-Z0-9]+\b", solution_guide)
            if w.casefold() not in {
                "the", "a", "an", "of", "and", "in", "on", "at", "to", "first", "second", "third",
                "south", "north", "east", "west", "they", "them", "their", "this", "that", "these",
                "those", "it", "its", "he", "she", "who", "which", "what", "where", "when"
            }
        ]
        if proper_nouns:
            rules.required_concepts = [p.casefold() for p in proper_nouns]

    # Numeric extraction
    nums = re.findall(r"-?\d+(?:\.\d+)?", g_clean)
    if nums:
        rules.expected_value = nums[-1]
    units = [w for w in re.findall(r"[a-z/]+", g_clean) if w in {"km/h", "m/s", "cm", "mm", "kg", "g", "seconds", "hours", "minutes", "students", "degrees", "percent"}]
    if units:
        rules.unit = units[0]

    return rules


def evaluate_strict_short_answer(
    q_text: str,
    user_ans: str,
    sol_guide: str,
    max_marks: int,
    rules: StructuredEvaluationRules | None = None,
) -> tuple[float, str, str] | None:
    """Centralized strict short-answer evaluation layer."""
    if not user_ans or not user_ans.strip():
        return 0.0, "Not answered", "No answer provided."

    if rules is None:
        rules = derive_structured_evaluation_rules(q_text, sol_guide)

    q_clean = q_text.casefold()

    # Magnet 3-material classification special handler if question matches
    magnet_mat = _std7_magnet_material_classification_decision(user_ans, q_text)
    if magnet_mat is True:
        return float(max_marks), "Correct", "Correct answer."
    elif magnet_mat is False:
        return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    clean_student = _normalize_syllabus_lookup_text(user_ans)
    if " my answer " in f" {clean_student} ":
        clean_student = clean_student.split(" my answer ", 1)[1]

    tokens = set(re.findall(r"\w+", clean_student))

    # 1. STRICT FORBIDDEN CONCEPTS & CONTRADICTION PATTERNS CHECK FIRST
    if rules.forbidden_concepts or rules.contradiction_patterns:
        has_forbidden_word = bool(tokens & set(rules.forbidden_concepts)) or any(fc in clean_student for fc in rules.forbidden_concepts)
        has_contradiction_pattern = any(bool(re.search(pat, clean_student)) for pat in rules.contradiction_patterns)

        if has_forbidden_word or has_contradiction_pattern:
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    # Europe physical features special handler
    if "europe" in q_clean and ("physical feature" in q_clean or "physical features" in q_clean or "two" in q_clean or "features" in q_clean):
        forbidden_europe = {
            "sahara", "amazon", "himalayas", "himalaya", "gobi", "thar", "nile", "ganges",
            "ganga", "mississippi", "rockies", "andes", "kalahari"
        }
        if any(f_word in tokens or f_word in clean_student for f_word in forbidden_europe):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        broad_features = {
            "peninsulas", "peninsula", "rivers", "river", "mountains", "mountain",
            "plains", "plain", "plateaus", "plateau", "seas", "sea", "oceans", "ocean",
            "islands", "island", "highlands", "highland"
        }
        specific_features = [
            "alps", "north european plain", "rhine", "danube", "scandinavian peninsula",
            "scandinavian", "mediterranean peninsulas", "mediterranean", "volga", "pyrenees", "urals", "ural"
        ]

        found_features: set[str] = set()
        for b in broad_features:
            if b in tokens or b in clean_student:
                norm_key = "peninsula" if "peninsula" in b else ("river" if "river" in b else ("mountain" if "mountain" in b else ("plain" if "plain" in b else ("plateau" if "plateau" in b else b))))
                found_features.add(norm_key)

        for s_feat in specific_features:
            if s_feat in clean_student:
                found_features.add(s_feat)

        if len(found_features) >= 2:
            return float(max_marks), "Correct", "Correct answer."
        elif len(found_features) == 1:
            half = round(max_marks * 0.5, 1)
            return half, "Partially correct", f"Partially correct. Mentioned one feature ({list(found_features)[0]}). Expected two."
        else:
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    # Sufi values special handler
    if "sufi" in q_clean and ("value" in q_clean or "values" in q_clean or "tradition" in q_clean or "traditions" in q_clean):
        forbidden_sufi = {"violence", "hatred", "greed", "war", "cruelty", "revenge", "selfishness"}
        if any(f_word in tokens or f_word in clean_student for f_word in forbidden_sufi):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        valid_sufi_values = [
            "love", "devotion", "remembrance of god", "remembrance", "god",
            "ethical conduct", "ethical", "conduct", "humility", "service",
            "compassion", "peace", "harmony", "brotherhood", "tolerance", "equality"
        ]
        found_sufi_values: set[str] = set()
        for v in valid_sufi_values:
            if v in clean_student or v in tokens:
                if v in {"love", "devotion"}:
                    found_sufi_values.add("devotion_love")
                elif v in {"service", "compassion"}:
                    found_sufi_values.add(v)
                elif v in {"remembrance of god", "remembrance", "god"}:
                    found_sufi_values.add("god_remembrance")
                elif v in {"ethical conduct", "ethical", "conduct"}:
                    found_sufi_values.add("ethical_conduct")
                elif v in {"humility"}:
                    found_sufi_values.add("humility")
                else:
                    found_sufi_values.add(v)

        if len(found_sufi_values) >= 2:
            return float(max_marks), "Correct", "Correct answer."
        elif len(found_sufi_values) == 1:
            half = round(max_marks * 0.5, 1)
            return half, "Partially correct", f"Partially correct. Mentioned one value. Expected two."
        else:
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    # Q21: Informal dispute settlement special handler
    if "dispute" in q_clean and ("informal" in q_clean or "settled" in q_clean or "agreement" in q_clean):
        if any(re.search(pat, clean_student) for pat in rules.contradiction_patterns) or "yes" in tokens:
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        has_no = bool(tokens & {"no", "not", "cannot", "never"}) or "no." in clean_student or "no," in clean_student
        has_formal = bool(tokens & {"courts", "court", "formal", "legal", "trial", "investigation", "binding", "judiciary", "processes", "process"}) or "formal legal" in clean_student
        if has_no and has_formal:
            return float(max_marks), "Correct", "Correct answer."

    # Q25: Artisans in medieval cities special handler
    if "artisans" in q_clean and ("important" in q_clean or "medieval" in q_clean or "cities" in q_clean or "role" in q_clean):
        if any(re.search(pat, clean_student) for pat in rules.contradiction_patterns):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        has_goods = bool(tokens & {"made", "produced", "goods", "crafts", "textiles", "metalwork", "materials", "making", "producing"}) or "made goods" in clean_student or "produced goods" in clean_student
        has_support = bool(tokens & {"trade", "traders", "economy", "residents", "courts", "supported", "city", "market", "cities"}) or "city economy" in clean_student or "supported trade" in clean_student
        if has_goods and has_support:
            return float(max_marks), "Correct", "Correct answer."

    # Q22: Forts importance handler
    if "forts" in q_clean and ("important" in q_clean or "rulers" in q_clean or "regional" in q_clean or "why" in q_clean):
        if any(re.search(pat, clean_student) for pat in rules.contradiction_patterns):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        has_protect = bool(tokens & {"protected", "protect", "defence", "defense", "control", "protecting", "serving"}) or "political control" in clean_student
        has_target = bool(tokens & {"capitals", "capital", "routes", "route", "supplies", "people", "control", "center", "centers", "centres", "centre"})
        if has_protect and has_target:
            return float(max_marks), "Correct", "Correct answer."

    # Q23: Industry adding value handler
    if "industry" in q_clean and ("value" in q_clean or "raw material" in q_clean or "add value" in q_clean or "adds value" in q_clean):
        if any(re.search(pat, clean_student) for pat in rules.contradiction_patterns):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        has_process = bool(tokens & {"processes", "process", "combines", "combine", "processing", "combining", "manufactures", "making"})
        has_val = bool(tokens & {"product", "products", "usefulness", "useful", "value", "market", "greater"}) or "market value" in clean_student or "greater usefulness" in clean_student
        if has_process and has_val:
            return float(max_marks), "Correct", "Correct answer."

    # Q24: Physiographic divisions of India handler
    if "physiographic" in q_clean or ("divisions" in q_clean and "india" in q_clean):
        if any(re.search(pat, clean_student) for pat in rules.contradiction_patterns):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        divisions = [
            "himalayas", "northern plains", "peninsular plateau", "indian desert", "coastal plains", "islands",
            "mountain", "mountains", "plain", "plains", "plateau", "desert", "coast", "coasts"
        ]
        found_divs: set[str] = set()
        for div in divisions:
            if div in clean_student or div in tokens:
                norm_div = "mountain" if "mountain" in div or "himalayas" in div else ("plain" if "plain" in div else ("plateau" if "plateau" in div else ("desert" if "desert" in div else ("coast" if "coast" in div else div))))
                found_divs.add(norm_div)

        if len(found_divs) >= 4:
            return float(max_marks), "Correct", "Correct answer."
        elif len(found_divs) >= 2:
            half = round(max_marks * 0.5, 1)
            return half, "Partially correct", f"Partially correct. Mentioned {len(found_divs)} divisions. Expected four."
        else:
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    # 2. REQUIRED CONCEPTS CHECK
    if rules.required_concepts:
        req_set = set(rules.required_concepts)
        # Check special multi-concept sets
        if "nitrogen" in req_set and "phosphorus" in req_set and "potassium" in req_set:
            has_n = "nitrogen" in tokens or "nitrogene" in clean_student
            has_p = "phosphorus" in tokens or "phosphorous" in clean_student
            has_k = "potassium" in tokens or "potasium" in clean_student
            if has_n and has_p and has_k:
                return float(max_marks), "Correct", "Correct answer."
            else:
                return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        if "solid" in req_set and "liquid" in req_set and ("gas" in req_set or "vapour" in req_set):
            norm_student = clean_student.replace("water vapour", "watervapour").replace("water vapor", "watervapour")
            s_tokens = set(norm_student.split())
            has_solid = bool(s_tokens & {"solid", "ice"})
            has_liquid = bool(s_tokens & {"liquid", "water"})
            has_gas = bool(s_tokens & {"gas", "gaseous", "vapour", "watervapour", "steam"})
            if has_solid and has_liquid and has_gas:
                return float(max_marks), "Correct", "Correct answer."
            else:
                return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

        matched_req = bool(tokens & req_set) or any(rc in clean_student for rc in rules.required_concepts)
        if matched_req:
            return float(max_marks), "Correct", "Correct answer."
        elif max_marks == 1 or re.search(r"\b(who|which ruler|which king|which dynasty|which emperor|which capital|name the)\b", q_clean):
            return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    return None


@dataclass
class GeneratedTestPaper:
    board: str
    medium: str
    standard: int
    subject: str
    scope_description: str
    total_marks: int
    duration_minutes: int
    questions: list[TestPaperQuestionItem]
    source_footer: str
    created_at: float = field(default_factory=time.time)


def parse_student_test_answers(message: str) -> dict[int, tuple[str, str]]:
    pattern = r"(?:^|\n|\s+)(?:Q|Ans|Question)?\s*(\d{1,2})\s*[:\.\)]\s*"
    splits = re.split(pattern, message, flags=re.IGNORECASE)
    answers: dict[int, tuple[str, str]] = {}
    if len(splits) >= 3:
        for i in range(1, len(splits), 2):
            q_num = int(splits[i])
            ans_text = splits[i + 1].strip() if i + 1 < len(splits) else ""
            lines = [line.strip() for line in ans_text.splitlines() if line.strip()]
            clean_text = " ".join(lines)
            ans_split = re.split(
                r"\b(?:Ans|Answer|My\s+answer)\s*[:\.]\s*",
                clean_text,
                flags=re.IGNORECASE,
            )
            if len(ans_split) == 2:
                answers[q_num] = (ans_split[0].strip(), ans_split[1].strip())
            else:
                answers[q_num] = ("", clean_text)
    return answers


def _detect_test_paper_mismatches(
    paper: GeneratedTestPaper,
    parsed_answers: dict[int, tuple[str, str]],
) -> list[tuple[int, str, int, TestPaperQuestionItem]]:
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for", "with",
        "of", "and", "or", "because", "it", "they", "them", "this", "that", "from", "be", "been",
        "your", "my", "our", "used", "using", "how", "what", "why", "which", "when", "where",
    }
    q_map = {q.question_num: q for q in paper.questions}
    mismatches: list[tuple[int, str, int, TestPaperQuestionItem]] = []

    for q_num, (q_prompt, ans_text) in parsed_answers.items():
        if q_prompt or not ans_text.strip():
            continue
        ans_words = {
            w for w in re.findall(r"\w+", ans_text.casefold())
            if len(w) > 2 and w not in stop_words
        }
        if not ans_words:
            continue

        assigned_q = q_map.get(q_num)
        assigned_score = 0
        if assigned_q:
            ref_text = f"{assigned_q.question_text} {assigned_q.solution_guide} {assigned_q.topic_title}"
            ref_words = {
                w for w in re.findall(r"\w+", ref_text.casefold())
                if len(w) > 2 and w not in stop_words
            }
            assigned_score = len(ans_words & ref_words)

        best_other_q: int | None = None
        best_other_score = 0
        for o_num, o_q in q_map.items():
            if o_num == q_num:
                continue
            o_text = f"{o_q.question_text} {o_q.solution_guide} {o_q.topic_title}"
            o_words = {
                w for w in re.findall(r"\w+", o_text.casefold())
                if len(w) > 2 and w not in stop_words
            }
            score = len(ans_words & o_words)
            if score > best_other_score:
                best_other_score = score
                best_other_q = o_num

        if (
            best_other_q is not None
            and best_other_score >= 2
            and (best_other_score > assigned_score + 1 or assigned_score == 0)
        ):
            mismatches.append((q_num, ans_text, best_other_q, q_map[best_other_q]))

    return mismatches


def evaluate_single_test_answer(
    q_text: str,
    user_ans: str,
    sol_guide: str,
    max_marks: int,
    rules: StructuredEvaluationRules | None = None,
) -> tuple[float, str, str]:
    if not user_ans or not user_ans.strip():
        return 0.0, "Not answered", "No answer provided."

    strict_res = evaluate_strict_short_answer(q_text, user_ans, sol_guide, max_marks, rules=rules)
    if strict_res is not None:
        return strict_res

    u_clean = user_ans.strip().casefold()
    g_clean = sol_guide.strip().casefold()

    def _strip_short_fillers(t: str) -> str:
        words = re.findall(r"\w+", t.casefold())
        fillers = {"system", "method", "process", "tool", "device", "technique", "type", "crops", "crop"}
        filtered = [w for w in words if w not in fillers]
        return " ".join(filtered) if filtered else " ".join(words)

    u_norm = _strip_short_fillers(u_clean)
    g_norm = _strip_short_fillers(g_clean)

    u_nums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", u_clean)
    g_nums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", g_clean)

    def _canon_unit_token(token: str) -> str:
        token = token.casefold()
        aliases = {
            "student": "students",
            "students": "students",
            "degree": "degrees",
            "degrees": "degrees",
            "percent": "percent",
            "percentage": "percent",
            "point": "points",
            "points": "points",
            "book": "books",
            "books": "books",
        }
        return aliases.get(token, token)

    def _token_stream(text: str) -> list[str]:
        return re.findall(r"-?\d+(?:\.\d+)?|[a-z]+", text.casefold())

    def _number_unit_pairs_nearby(text: str) -> list[tuple[str, set[str]]]:
        tokens = _token_stream(text)
        unit_words = {"students", "degrees", "percent", "points", "books"}
        pairs: list[tuple[str, set[str]]] = []
        for idx, token in enumerate(tokens):
            if not re.fullmatch(r"-?\d+(?:\.\d+)?", token):
                continue
            nearby_units = {
                _canon_unit_token(t)
                for t in tokens[idx + 1 : idx + 4]
                if _canon_unit_token(t) in unit_words
            }
            if nearby_units:
                pairs.append((token, nearby_units))
        return pairs

    def _guide_has_number_unit_pair(number: str, units: set[str]) -> bool:
        for guide_number, guide_units in _number_unit_pairs_nearby(g_clean):
            if guide_number == number and bool(units & guide_units):
                return True
        return False

    def _short_final_answer_embedded_in_solution() -> bool:
        # Attached test answers are often concise final answers ("30 students")
        # while the installed guide contains full working
        # ("...90/360...120 x 1/4 = 30 students"). Accept only when the final
        # number is paired with the same unit/answer word in the guide, so a
        # wrong answer like "90 students" does not pass just because 90 appears
        # elsewhere in the formula.
        if "/" in u_clean:
            return False

        raw_user_tokens = _token_stream(u_clean)
        if not raw_user_tokens or len(raw_user_tokens) > 12:
            return False

        compact_user = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.\-]+", " ", u_clean)).strip()
        compact_guide = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.\-]+", " ", g_clean)).strip()
        user_pairs = _number_unit_pairs_nearby(u_clean)
        if user_pairs:
            if not all(_guide_has_number_unit_pair(number, units) for number, units in user_pairs):
                return False
            if len(compact_user) >= 3 and compact_user in compact_guide:
                return True

        stop = {
            "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for",
            "with", "of", "and", "or", "because", "it", "they", "them", "this", "that", "from",
            "be", "been", "so", "as", "than",
        }
        user_tokens = {
            _canon_unit_token(t)
            for t in raw_user_tokens
            if len(t) > 1 and t not in stop
        }
        guide_tokens = {
            _canon_unit_token(t)
            for t in _token_stream(g_clean)
            if len(t) > 1 and t not in stop
        }
        if len(user_tokens) < 2 or not user_tokens <= guide_tokens:
            return False
        if user_pairs:
            return True

        anchor_words = {
            "larger", "smaller", "left", "right", "between", "complete", "incomplete",
            "yes", "no", "bus", "walk", "cycle", "music", "art",
        }
        return bool(user_tokens & anchor_words)


    def _fraction_values(text: str) -> list[Fraction]:
        values: list[Fraction] = []
        for raw_num in re.findall(r"-?\d+(?:/\d+)?", text.casefold()):
            try:
                values.append(Fraction(raw_num))
            except (ValueError, ZeroDivisionError):
                continue
        return values

    def _ceil_fraction(value: Fraction) -> int:
        return -(-value.numerator // value.denominator)

    q_clean = q_text.casefold()
    q_values = _fraction_values(q_clean)
    u_values = _fraction_values(u_clean)

    if "between which two integers" in q_clean and q_values and u_values:
        target = q_values[0]
        lower = target.numerator // target.denominator
        upper = _ceil_fraction(target)
        if lower != upper and {Fraction(lower), Fraction(upper)} <= set(u_values):
            return float(max_marks), "Correct", "Correct answer."

    if "find three rational numbers between" in q_clean and len(q_values) >= 2 and u_values:
        low, high = sorted((q_values[-2], q_values[-1]))
        valid_between = {value for value in u_values if low < value < high}
        if len(valid_between) >= 3:
            return float(max_marks), "Correct", "Correct answer."

    if _short_final_answer_embedded_in_solution():
        return float(max_marks), "Correct", "Correct answer."

    if len(g_clean.split()) <= 5 or g_nums:
        if u_nums and g_nums:
            q_nums = re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", q_clean)
            u_ans_nums = [n for n in u_nums if n not in q_nums]
            if u_nums == g_nums or u_ans_nums == g_nums or (g_nums and g_nums[-1] in u_nums and set(u_nums) - set(q_nums) == set(g_nums)):
                return float(max_marks), "Correct", "Correct answer."
            else:
                return 0.0, "Incorrect", f"Incorrect. Expected value: {sol_guide}"
        if (
            u_clean == g_clean
            or u_norm == g_norm
            or (len(u_norm) >= 4 and u_norm in g_norm)
            or (len(g_norm) >= 4 and g_norm in u_norm)
        ):
            return float(max_marks), "Correct", "Correct answer."
        if len(u_clean.split()) <= 4:
            return 0.0, "Incorrect", f"Incorrect. Expected answer: {sol_guide}"

    if u_clean == g_clean or u_norm == g_norm:
        return float(max_marks), "Correct", "Correct answer."

    wrong_keywords = {
        "red", "blue", "green", "yellow", "iron", "steel", "plastic", "magic", "fake", "bad"
    }
    u_words = set(re.findall(r"\w+", u_clean))
    g_words = set(re.findall(r"\w+", g_clean))

    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for", "with",
        "of", "and", "or", "because", "it", "they", "them", "this", "that", "from", "be", "been"
    }
    ref_keywords = {w for w in g_words if len(w) > 2 and w not in stop_words}
    user_keywords = {w for w in u_words if len(w) > 2 and w not in stop_words}

    short_fact_question = any(
        phrase in q_text.casefold()
        for phrase in (
            "identify",
            "complete",
            "what sense",
            "which word",
            "name",
            "what is",
            "who is",
            "when",
            "where",
        )
    )
    if (
        short_fact_question
        and 0 < len(user_keywords) <= 3
        and user_keywords <= ref_keywords
    ):
        return float(max_marks), "Correct", "Correct answer."

    has_wrong_keyword = (
        bool(user_keywords & wrong_keywords)
        and not bool(ref_keywords & wrong_keywords)
    )
    if has_wrong_keyword:
        return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    method_words = {"water", "float", "sink", "hollow"}
    consequence_words = {
        "healthy", "yield", "crop", "plants", "grow", "growth", "produce", "weak"
    }

    has_method = bool(user_keywords & method_words)
    has_consequence = bool(user_keywords & consequence_words)

    if "why" in q_text.casefold() or "seed" in q_text.casefold():
        if has_method and not has_consequence:
            half = round(max_marks * 0.5, 1)
            return (
                half,
                "Partially correct",
                "Explains the identification method (float/sink) but misses main reason (hollow/weak seeds failing to grow into healthy plants).",
            )

    negative_words = {"never", "not", "no", "destroyed", "denied", "fake", "refused", "failed", "surrendered", "wasteland", "confuse", "useless", "nothing"}
    user_negs = user_keywords & negative_words
    guide_negs = ref_keywords & negative_words
    if user_negs and not guide_negs:
        return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    if max_marks >= 2:
        return 0.0, "Needs review", f"Descriptive answer requires manual review or structured rubric. Expected key points: {sol_guide}"

    if ref_keywords:
        matched = user_keywords & ref_keywords
        ratio = len(matched) / float(len(ref_keywords))
        if ratio >= 0.5 or len(matched) >= 3:
            return float(max_marks), "Correct", "Correct key concepts covered."
        elif ratio >= 0.25 or len(matched) >= 2:
            half = round(max_marks * 0.5, 1)
            return (
                half,
                "Partially correct",
                f"Partially correct answer. Missing complete details: {sol_guide}",
            )

    return 0.0, "Incorrect", f"Incorrect. Correct answer: {sol_guide}"


def evaluate_test_paper(
    paper: GeneratedTestPaper,
    message: str,
) -> str:
    parsed_answers = parse_student_test_answers(message)

    # 1. Question-prompt remapping (if user included question text in submission)
    mapped_answers: dict[int, str] = {}
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for", "with",
        "of", "and", "or", "because", "it", "they", "them", "this", "that", "from", "be", "been",
    }
    for q_num, (q_prompt, ans_text) in parsed_answers.items():
        if q_prompt:
            p_words = {
                w for w in re.findall(r"\w+", q_prompt.casefold())
                if len(w) > 2 and w not in stop_words
            }
            best_q = q_num
            best_overlap = 0
            for q_item in paper.questions:
                q_words = {
                    w for w in re.findall(r"\w+", q_item.question_text.casefold())
                    if len(w) > 2 and w not in stop_words
                }
                overlap = len(p_words & q_words)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_q = q_item.question_num
            mapped_answers[best_q] = ans_text
        else:
            mapped_answers[q_num] = ans_text

    # 2. Check for concept mismatches (only when prompts were not explicitly given)
    mismatches = _detect_test_paper_mismatches(paper, parsed_answers)
    answered_count = len([a for _, a in mapped_answers.items() if a.strip()])
    if len(mismatches) >= 2 or (answered_count > 0 and len(mismatches) / float(answered_count) >= 0.5):
        warning_lines = [
            "Your pasted answers do not appear to match the question numbers in the generated test paper.",
            "",
            "Detected Question Mismatches:",
        ]
        for q_num, ans_text, alt_q_num, alt_item in mismatches[:4]:
            trunc_ans = ans_text[:40] + ("..." if len(ans_text) > 40 else "")
            trunc_q = alt_item.question_text[:40] + ("..." if len(alt_item.question_text) > 40 else "")
            warning_lines.append(
                f"- Your Answer {q_num} (\"{trunc_ans}\") matches Question {alt_q_num} (\"{trunc_q}\")"
            )
        warning_lines.extend(
            [
                "",
                "How to Fix & Re-submit:",
                "1. Re-paste your answers using the exact question numbers from the test paper:",
                "   1. <Answer for Question 1>",
                "   2. <Answer for Question 2>",
                "   3. <Answer for Question 3>",
                "",
                "2. OR include the question text with each answer:",
                "   Q1. Classify wheat and paddy... Ans: Paddy is Kharif crop...",
                "   Q2. Why should damaged seeds be separated? Ans: Because...",
                "",
                paper.source_footer,
            ]
        )
        return "\n".join(warning_lines)

    # 3. Perform actual grading
    total_awarded = 0.0
    total_max = paper.total_marks

    table_rows: list[str] = []
    weak_topics: dict[str, float] = {}

    for q_item in paper.questions:
        ans_text = mapped_answers.get(q_item.question_num, "")
        awarded, result_str, feedback_str = evaluate_single_test_answer(
            q_item.question_text,
            ans_text,
            q_item.solution_guide,
            q_item.max_marks,
        )
        total_awarded += awarded
        table_rows.append(
            f"| Q{q_item.question_num} | [{q_item.topic_title}] | {q_item.max_marks} | {awarded:g} | {result_str} | {feedback_str} |"
        )
        if awarded < q_item.max_marks:
            lost = q_item.max_marks - awarded
            weak_topics[q_item.topic_title] = weak_topics.get(q_item.topic_title, 0.0) + lost

    percentage = (total_awarded / float(total_max) * 100.0) if total_max > 0 else 0.0

    board_name = (
        "Gujarat Secondary and Higher Secondary Education Board (GSEB)"
        if paper.board.casefold() == "gseb"
        else paper.board
    )

    lines: list[str] = [
        "Test Evaluation",
        board_name,
        f"Medium: {paper.medium} | Standard: {paper.standard} | Subject: {paper.subject}",
        f"Test Scope: {paper.scope_description}",
        f"Total Marks: {total_awarded:g}/{total_max} ({percentage:.1f}%)",
        "",
        "Per-Question Evaluation:",
        "| Q No | Topic | Max Marks | Awarded Marks | Result | Feedback |",
        "|---|---|---|---|---|---|",
    ]
    lines.extend(table_rows)
    lines.append("")

    if weak_topics:
        lines.append("Weak Topics Identified:")
        for top_title, lost_m in weak_topics.items():
            lines.append(f"- {top_title}: Lost {lost_m:g} mark/marks")
        lines.append("")
        lines.append("Suggested Revision Plan:")
        for top_title in weak_topics.keys():
            lines.append(
                f"- Review topic '{top_title}' in {paper.subject} textbook and re-solve key practice exercises."
            )
        lines.append("")
    else:
        lines.append("Excellent performance! All answers were fully correct.")
        lines.append("")

    lines.append(paper.source_footer)
    return "\n".join(lines)


def format_test_paper_duration(duration_minutes: int) -> str:
    if duration_minutes == 180:
        return "3 Hours"
    if duration_minutes == 120:
        return "2 Hours"
    if duration_minutes == 90:
        return "90 Minutes"
    if duration_minutes == 60:
        return "1 Hour"
    return f"{duration_minutes} Minutes"


def _chapter_number_digits(c_num: str) -> list[str]:
    """Extract list of possible chapter number representations."""
    digits = re.sub(r"\D", "", c_num)
    results = [c_num.casefold(), digits]
    m = re.search(r"[-_](\d+)$", c_num)
    if m:
        results.append(m.group(1))
        results.append(str(int(m.group(1))))
    elif digits and digits.isdigit():
        results.append(str(int(digits)))
    return list(set(r for r in results if r))


def _find_explicit_chapter_in_message(
    message: str,
    syllabus: BoardSyllabus,
) -> SyllabusChapter | None:
    msg_clean = message.casefold()

    # 1. Match chapter number (e.g. "chapter 2", "ch 2", "chap 2", "path 2", "chapter 02")
    num_match = re.search(
        r"\b(?:chapter|ch|chap|path|adhyay)\.?\s*(\d{1,2})\b",
        message,
        re.IGNORECASE,
    )
    if num_match:
        target_num_str = num_match.group(1)
        target_num_int = str(int(target_num_str))
        for c in syllabus.chapters:
            c_digits = _chapter_number_digits(c.number)
            if target_num_str in c_digits or target_num_int in c_digits:
                return c

    # 2. Match chapter titles or stripped titles in message
    for c in syllabus.chapters:
        c_title_clean = c.title.casefold()
        if c_title_clean in msg_clean:
            return c
        stripped_title = re.sub(
            r"^semester\s*\d+\s*[—\-–:]\s*",
            "",
            c_title_clean,
            flags=re.IGNORECASE,
        ).strip()
        if len(stripped_title) >= 3 and stripped_title in msg_clean:
            return c

    return None


def _find_chapter_from_context(
    ctx_ch: str,
    syllabus: BoardSyllabus,
) -> SyllabusChapter | None:
    if not ctx_ch or not ctx_ch.strip():
        return None
    ctx_clean = ctx_ch.casefold().strip()

    # 1. Direct title comparison (exact or substring)
    for c in syllabus.chapters:
        c_title_clean = c.title.casefold()
        if c_title_clean == ctx_clean or c_title_clean in ctx_clean or ctx_clean in c_title_clean:
            return c

    # 2. Stripped title comparison (removing "Semester X — ")
    for c in syllabus.chapters:
        stripped_title = re.sub(
            r"^semester\s*\d+\s*[—\-–:]\s*",
            "",
            c.title.casefold(),
            flags=re.IGNORECASE,
        ).strip()
        if len(stripped_title) >= 3 and (stripped_title in ctx_clean or ctx_clean in stripped_title):
            return c

    # 3. Chapter number in context string (e.g. "Chapter 2", "Ch 2", "Path 2", "S1-2")
    num_match = re.search(
        r"\b(?:chapter|ch|chap|path|s\d+[-_]?)\s*(\d{1,2})\b",
        ctx_ch,
        re.IGNORECASE,
    )
    if num_match:
        target_num_str = num_match.group(1)
        target_num_int = str(int(target_num_str))
        for c in syllabus.chapters:
            c_digits = _chapter_number_digits(c.number)
            if target_num_str in c_digits or target_num_int in c_digits:
                return c

    # 4. Digits match if context is short (e.g. "2" or "S1-2")
    ctx_digits = re.sub(r"\D", "", ctx_ch)
    if ctx_digits:
        ctx_num_int = str(int(ctx_digits)) if ctx_digits.isdigit() else ""
        for c in syllabus.chapters:
            c_digits = _chapter_number_digits(c.number)
            if ctx_digits in c_digits or (ctx_num_int and ctx_num_int in c_digits):
                return c

    return None


def parse_test_paper_scope(
    message: str,
    context: StudentLearningContext,
    syllabus: BoardSyllabus,
) -> TestPaperScope:
    msg_clean = message.casefold()
    include_answers = any(
        phrase in msg_clean
        for phrase in (
            "with answer",
            "with answers",
            "and answer",
            "and answers",
            "answer key",
            "answers included",
            "include answer",
            "include answers",
            "with solution",
            "with solutions",
        )
    )

    marks_match = re.search(
        r"\b(20|25|50|80|100)\s*(?:marks?|mark|m)\b",
        message,
        re.IGNORECASE,
    )
    explicit_marks = int(marks_match.group(1)) if marks_match else None

    dur_match = re.search(
        r"\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|hour|hr|minutes?|mins?|min)\b",
        message,
        re.IGNORECASE,
    )
    explicit_duration: int | None = None
    if dur_match:
        val = float(dur_match.group(1))
        unit = dur_match.group(2).casefold()
        if "hour" in unit or "hr" in unit:
            explicit_duration = int(val * 60)
        else:
            explicit_duration = int(val)

    full_book_phrases = (
        "full book",
        "pure book",
        "full syllabus",
        "final exam",
        "entire book",
        "all chapters",
        "full syllabus paper",
        "annual exam",
        "board exam",
    )
    is_full_book = any(phrase in msg_clean for phrase in full_book_phrases)

    if is_full_book:
        total_marks = explicit_marks if explicit_marks is not None else 100
        duration = (
            explicit_duration
            if explicit_duration is not None
            else (
                180
                if total_marks == 100
                else {20: 30, 25: 45, 50: 90, 80: 120, 100: 180}.get(total_marks, 180)
            )
        )
        return TestPaperScope(
            scope_type="full_book",
            chapters=list(syllabus.chapters),
            total_marks=total_marks,
            duration_minutes=duration,
            include_answers=include_answers,
            description=f"Full Syllabus — Full book test ({len(syllabus.chapters)} Chapters / Full Book)",
        )

    # Multi-chapter range
    range_match = re.search(
        r"\bchapter[s]?\s*(\d{1,2})\s*(?:to|-|through|till|se)\s*(\d{1,2})\b",
        message,
        re.IGNORECASE,
    )
    if range_match:
        start_c, end_c = int(range_match.group(1)), int(range_match.group(2))
        matched = [
            c
            for c in syllabus.chapters
            if start_c <= int(re.sub(r"\D", "", c.number) or 0) <= end_c
        ]
        if len(matched) > 1:
            total_marks = explicit_marks if explicit_marks is not None else 50
            duration = (
                explicit_duration
                if explicit_duration is not None
                else (
                    90
                    if total_marks == 50
                    else {20: 30, 25: 45, 50: 90, 80: 120, 100: 180}.get(total_marks, 90)
                )
            )
            ch_str = ", ".join(c.number for c in matched)
            return TestPaperScope(
                scope_type="multi_chapter",
                chapters=matched,
                total_marks=total_marks,
                duration_minutes=duration,
                include_answers=include_answers,
                description=f"Chapters {ch_str} ({len(matched)} Chapters)",
            )

    # Multi-chapter list (e.g. Chapters 1, 2 and 3)
    list_match = re.search(
        r"\bchapters?\s*(\d{1,2}(?:\s*,\s*\d{1,2})*(?:\s*(?:and|&)\s*\d{1,2})+)\b",
        message,
        re.IGNORECASE,
    )
    if list_match:
        nums = [int(n) for n in re.findall(r"\b\d{1,2}\b", list_match.group(1))]
        matched = [
            c
            for c in syllabus.chapters
            if int(re.sub(r"\D", "", c.number) or 0) in nums
        ]
        if len(matched) > 1:
            total_marks = explicit_marks if explicit_marks is not None else 50
            duration = (
                explicit_duration
                if explicit_duration is not None
                else (
                    90
                    if total_marks == 50
                    else {20: 30, 25: 45, 50: 90, 80: 120, 100: 180}.get(total_marks, 90)
                )
            )
            ch_str = ", ".join(c.number for c in matched)
            return TestPaperScope(
                scope_type="multi_chapter",
                chapters=matched,
                total_marks=total_marks,
                duration_minutes=duration,
                include_answers=include_answers,
                description=f"Chapters {ch_str} ({len(matched)} Chapters)",
            )

    # Multi-chapter count (e.g. 3 chapters complete hue hain)
    count_match = re.search(
        r"\b(\d{1,2})\s*chapters?\b",
        message,
        re.IGNORECASE,
    )
    if count_match:
        cnt = int(count_match.group(1))
        if cnt > 1:
            matched = syllabus.chapters[:cnt]
            total_marks = explicit_marks if explicit_marks is not None else 50
            duration = (
                explicit_duration
                if explicit_duration is not None
                else (
                    90
                    if total_marks == 50
                    else {20: 30, 25: 45, 50: 90, 80: 120, 100: 180}.get(total_marks, 90)
                )
            )
            ch_str = ", ".join(c.number for c in matched)
            return TestPaperScope(
                scope_type="multi_chapter",
                chapters=matched,
                total_marks=total_marks,
                duration_minutes=duration,
                include_answers=include_answers,
                description=f"Chapters {ch_str} ({len(matched)} Chapters)",
            )

    # Single chapter resolution
    ambiguous_another_phrases = (
        "dusra chapter",
        "dusre chapter",
        "dusri chapter",
        "another chapter",
        "different chapter",
        "other chapter",
        "next chapter",
        "naya chapter",
        "naye chapter",
        "nayi chapter",
        "dusra test",
        "dusri test",
        "dusre test",
        "change chapter",
    )
    is_ambiguous_another = any(phrase in msg_clean for phrase in ambiguous_another_phrases)

    explicit_ch = _find_explicit_chapter_in_message(message, syllabus)

    if is_ambiguous_another and explicit_ch is None:
        return TestPaperScope(
            scope_type="ambiguous",
            chapters=[],
            total_marks=0,
            duration_minutes=0,
            include_answers=include_answers,
            description="Please select or name the chapter for the chapter test.",
        )

    target_ch = explicit_ch
    if target_ch is None and context and context.current_chapter:
        target_ch = _find_chapter_from_context(context.current_chapter, syllabus)

    if target_ch is None:
        target_ch = syllabus.chapters[0]

    total_marks = explicit_marks if explicit_marks is not None else 25
    duration = (
        explicit_duration
        if explicit_duration is not None
        else (
            45
            if total_marks == 25
            else {20: 30, 25: 45, 50: 90, 80: 120, 100: 180}.get(total_marks, 45)
        )
    )
    return TestPaperScope(
        scope_type="single_chapter",
        chapters=[target_ch],
        total_marks=total_marks,
        duration_minutes=duration,
        include_answers=include_answers,
        description=f"{target_ch.title} — Chapter test",
    )


def is_random_test_request(message: str) -> bool:
    msg_clean = message.casefold()
    repeat_phrases = (
        "same test",
        "repeat test",
        "same paper",
        "repeat paper",
        "previous test",
        "default test",
    )
    if any(phrase in msg_clean for phrase in repeat_phrases):
        return False

    random_phrases = (
        "new test",
        "different test",
        "random test",
        "practice test",
        "practice exam",
        "another test",
        "new paper",
        "different paper",
        "random paper",
        "naya test",
        "naya paper",
        "dusra test",
        "dusra paper",
        "dusri test",
        "shuffle",
        "vary",
    )
    if any(phrase in msg_clean for phrase in random_phrases):
        return True

    if any(w in msg_clean for w in ("new", "different", "random", "practice", "naya", "dusra", "another")):
        if any(w in msg_clean for w in ("banao", "create", "generate", "give", "karo", "chahiye")):
            return True

    return False


def extract_test_seed(message: str) -> int | str | None:
    match = re.search(r"\bseed\s*[:=]?\s*(\w+)\b", message, re.IGNORECASE)
    if match:
        val = match.group(1)
        return int(val) if val.isdigit() else val
    return None


def determine_question_intended_marks(q_text: str, sol_text: str, is_example: bool = False) -> int:
    q_lower = q_text.casefold().strip()
    sol_clean = sol_text.strip()
    sol_words = len(sol_clean.split())

    # One-line / simple factual questions -> 1 Mark
    one_line_prefixes = (
        "what was ",
        "who was ",
        "which instrument",
        "name the three main parts",
        "name the three",
        "give one role",
        "which ",
        "name ",
        "give one ",
        "what is ",
        "what are ",
        "define ",
        "where is ",
        "what happens when ",
        "identify ",
        "fill in ",
        "state one",
        "who ",
    )
    if any(q_lower.startswith(prefix) for prefix in one_line_prefixes):
        if sol_words < 20 and not any(k in q_lower for k in ("explain in detail", "describe the process", "compare")):
            return 1

    if q_lower.startswith("state ") and not any(k in q_lower for k in ("state two", "state three", "state the effects", "state how", "state why")):
        if sol_words < 18:
            return 1

    # Examples like "Explain with an example: ..." -> 3 Marks
    if is_example or q_lower.startswith("explain with an example:"):
        return 3

    # Long-answer / process / 6-mark questions -> 6 Marks
    long_6m_keywords = (
        "describe the process",
        "explain in detail",
        "how will you show",
        "how can you show",
        "draw and explain",
        "describe in detail",
        "step-by-step process",
        "cause and effect",
        "advantages and limitations",
        "detailed process",
        "describe harshavardhana's rule",
        "explain pulakeshin ii's rule",
        "explain how travellers' accounts",
        "public welfare activities",
        "importance of vatapi",
        "cultural achievements of",
    )
    if any(k in q_lower for k in long_6m_keywords) or (
        sol_words >= 35 and (sol_clean.count(".") >= 3 or "\n" in sol_clean or ";" in sol_clean)
    ):
        return 6

    # 2-mark question specific patterns (classify, state two, distinguish with example, explain how ... with one example, calculations)
    if any(k in q_lower for k in ("state two", "classify", "distinguish", "with one example", "with an example")) and sol_words <= 35:
        return 2

    if "speed = distance / time" in sol_clean.casefold() or "time = distance / speed" in sol_clean.casefold() or "distance = speed * time" in sol_clean.casefold():
        if sol_words <= 30:
            return 2

    # 3-mark questions: explanation, distinction, reasoning, multi-point, calculation with steps
    three_mark_keywords = (
        "explain in detail",
        "explain with an example",
        "describe",
        "compare and contrast",
    )
    if any(k in q_lower for k in three_mark_keywords) or sol_words >= 35:
        return 3

    # Brief reasons / 2-point answers -> 2 Marks
    if sol_words >= 12 or any(k in q_lower for k in ("why", "reason", "difference", "two", "explain", "how")):
        return 2

    return 1



def build_natural_6mark_question(
    topic_title: str,
    explanation: str,
    examples: list[str],
) -> tuple[str, str] | None:
    t_lower = topic_title.casefold().strip()
    exp_clean = explanation.strip() if explanation else ""

    if len(exp_clean.split()) < 12:
        return None

    ex_str = f" Examples: {', '.join(examples[:2])}." if examples else ""
    sol_text = f"{exp_clean}{ex_str}"

    # 1. Specifically requested exact-topic mappings
    if "harshavardhana" in t_lower or "kanauj" in t_lower:
        return (
            "Describe Harshavardhana's rule, public welfare activities, support for learning, and importance of Kanauj.",
            sol_text,
        )
    if "pulakeshin" in t_lower or "chalukya" in t_lower or "vatapi" in t_lower:
        return (
            "Explain Pulakeshin II's rule, the importance of Vatapi, his conflict with Harshavardhana, and cultural achievements of the Chalukyas.",
            sol_text,
        )
    if "travellers" in t_lower or "nalanda" in t_lower or "historical evidence" in t_lower:
        return (
            "Explain how travellers' accounts, Nalanda, inscriptions, and coins help us understand early medieval India.",
            sol_text,
        )
    if "court hierarchy" in t_lower or ("civil cases" in t_lower and "criminal cases" in t_lower):
        return (
            "Explain the court hierarchy in India and distinguish civil cases from criminal cases with examples.",
            sol_text,
        )
    if "physiographic divisions" in t_lower or ("physiographic" in t_lower and "india" in t_lower):
        return (
            "Describe the major physiographic divisions of India and explain how they influence resources, settlement and occupations.",
            sol_text,
        )
    if "saint-poets" in t_lower or ("saint" in t_lower and "equality" in t_lower) or ("devotion" in t_lower and "cultural exchange" in t_lower):
        return (
            "Explain how saint-poets spread messages of devotion, equality and cultural exchange with suitable examples.",
            sol_text,
        )
    if "mixtures and separation choices" in t_lower:
        return (
            "Explain how different mixture components can be separated using hand-picking, filtration, magnetic separation, and evaporation, with one example each.",
            sol_text,
        )
    if "mixtures and separation choices" in t_lower:
        return (
            "Explain how different mixture components can be separated using hand-picking, filtration, magnetic separation, and evaporation, with one example each.",
            sol_text,
        )
    if "plane-mirror images and types of reflection" in t_lower:
        return (
            "Explain the image properties formed by a plane mirror and distinguish regular reflection from diffuse reflection with examples.",
            sol_text,
        )
    if "energy conservation and responsible use" in t_lower or ("energy" in t_lower and "responsible use" in t_lower):
        return (
            "Explain why electrical energy should be used responsibly and describe four ways to conserve energy at home or school.",
            sol_text,
        )
    if "conservation and sustainable action" in t_lower:
        return (
            "Explain the importance of water conservation and describe the process of rainwater harvesting.",
            sol_text,
        )
    if "light, visibility and reflection" in t_lower:
        return (
            "Explain how we see luminous and non-luminous objects. Include the role of light, reflection, and two examples.",
            sol_text,
        )
    if "laws of reflection" in t_lower:
        return (
            "State the two laws of reflection, explain the angle of incidence and angle of reflection, and solve a reflection angle problem.",
            sol_text,
        )
    if "concave and convex mirrors" in t_lower:
        return (
            "Compare concave and convex mirrors in terms of reflecting surface shape, focal point, and ray convergence or divergence.",
            sol_text,
        )
    if "images and uses of curved mirrors" in t_lower:
        return (
            "Describe image formation in concave and convex mirrors for different object positions and state their practical applications in dentist mirrors and rear-view mirrors.",
            sol_text,
        )
    if "thermal equilibrium and everyday applications" in t_lower:
        return (
            "Explain thermal equilibrium with two everyday examples and describe how heat transfer stops when temperatures become equal.",
            sol_text,
        )
    if "smaller bodies and conditions for life" in t_lower:
        return (
            "Describe the main conditions that make Earth suitable for life and compare them with smaller bodies such as comets or dwarf planets.",
            sol_text,
        )

    # 2. Levers & Simple machines
    if "classes of levers" in t_lower or "class of lever" in t_lower:
        return (
            "Explain the three classes of levers with one example of each class.",
            sol_text,
        )
    if "lever parts and mechanical advantage" in t_lower:
        return (
            "Define fulcrum, effort, and load in a lever, and explain mechanical advantage with formula.",
            sol_text,
        )
    if "moments, balance and applications" in t_lower:
        return (
            "Explain the principle of moments, beam balance equilibrium, and practical applications of levers in daily tools.",
            sol_text,
        )

    # 3. Plant Reproduction / Flowers / Fruits / Seeds / Roots / Stems
    if "flowers, fruits and seeds" in t_lower or "parts of plants" in t_lower:
        return (
            "Explain how flowers help in reproduction and describe how fruits and seeds are formed.",
            sol_text,
        )
    if "roots and root modifications" in t_lower:
        return (
            "Describe taproot and fibrous root systems and explain how root modifications support storage, anchoring, and breathing.",
            sol_text,
        )
    if "stems, leaves and modifications" in t_lower:
        return (
            "Explain the functions of stems and leaves, including modifications for food storage, tendrils, and protection.",
            sol_text,
        )

    # 4. Physiology / Digestion / Respiration / Circulation / Excretion
    if "digestion and absorption" in t_lower:
        return (
            "Describe the process of digestion and absorption in humans step by step.",
            sol_text,
        )
    if "respiration and gas exchange" in t_lower:
        return (
            "Explain the process of respiration in human beings and describe how gas exchange occurs.",
            sol_text,
        )
    if "blood circulation, heart and pulse" in t_lower:
        return (
            "Describe the structure and function of the human circulatory system and how blood is pumped.",
            sol_text,
        )

    # 5. Physics / Speed / Motion / Heat / Electricity / Magnetism
    if "speed and its measurement" in t_lower:
        return (
            "Solve a speed-distance-time calculation problem and explain the formula, steps, and units used.",
            sol_text,
        )
    if "conduction, convection and radiation" in t_lower:
        return (
            "Explain the three modes of heat transfer with labelled diagrams and real-life examples.",
            sol_text,
        )
    if "heat, temperature and thermometers" in t_lower:
        return (
            "Distinguish heat from temperature, explain heat flow direction, and describe laboratory and clinical thermometers.",
            sol_text,
        )
    if "electric cells, circuits and current" in t_lower:
        return (
            "Describe the construction and working of a simple electric circuit with symbols and safety measures.",
            sol_text,
        )
    if "conductors, insulators and switches" in t_lower:
        return (
            "Differentiate between electrical conductors and insulators with three examples each and explain the role of a switch.",
            sol_text,
        )
    if "electrical effects, safety and conservation" in t_lower:
        return (
            "Explain the heating and magnetic effects of electric current and safety measures like fuses and insulation.",
            sol_text,
        )
    if "magnetic materials and poles" in t_lower:
        return (
            "Describe magnetic materials, poles, and how magnetic force behaves near magnet ends.",
            sol_text,
        )
    if "attraction, repulsion and magnetic field" in t_lower:
        return (
            "Describe the properties of magnets, magnetic field lines, and how attraction and repulsion work.",
            sol_text,
        )
    if "compass" in t_lower or "earth's magnetism" in t_lower or "earth magnetism" in t_lower:
        return (
            "Explain how a magnetic compass works, describe Earth's magnetic behavior, and explain how a freely suspended magnet aligns north-south.",
            sol_text,
        )

    # 6. Chemistry / Acid-Base / Physical-Chemical changes / Elements / Compounds / Mixtures
    if "physical and chemical" in t_lower or "chemical change" in t_lower:
        return (
            "Compare physical and chemical changes with at least three differences and supporting examples.",
            sol_text,
        )
    if "elements and atoms" in t_lower:
        return (
            "Define an element and atom, give chemical symbols of oxygen, iron, and copper, and explain why elements cannot be broken down by chemical methods.",
            sol_text,
        )
    if "compounds and chemical combination" in t_lower:
        return (
            "Define a compound, explain fixed mass ratios, chemical formulas, and how compound properties differ from their component elements.",
            sol_text,
        )
    if "mixtures and classification" in t_lower:
        return (
            "Differentiate between elements, compounds, and mixtures with fixed vs variable compositions and two examples of each.",
            sol_text,
        )
    if "separating insoluble solids" in t_lower:
        return (
            "Describe the processes of sedimentation, decantation, and filtration for separating insoluble solids from liquids.",
            sol_text,
        )
    if "separating solutions and miscible liquids" in t_lower:
        return (
            "Explain evaporation, condensation, and distillation methods for separating dissolved solids and miscible liquids.",
            sol_text,
        )

    # 7. Environment / Soil / Water / Air pollution
    if "soil composition" in t_lower:
        return (
            "Describe the different layers of a soil profile and explain the causes and prevention of soil erosion.",
            sol_text,
        )
    if "soil testing and plant nutrients" in t_lower:
        return (
            "Explain how soil testing identifies nutrient deficiencies and describe major plant nutrients needed for crop yield.",
            sol_text,
        )
    if "maintaining soil fertility" in t_lower:
        return (
            "Describe the methods used to maintain soil fertility, including organic manure, crop rotation, and balanced fertilizers.",
            sol_text,
        )
    if "physical properties and states of water" in t_lower:
        return (
            "Describe the three physical states of water, their interconversion, and physical properties like boiling and freezing points.",
            sol_text,
        )
    if "water as a solvent and solutions" in t_lower:
        return (
            "Explain why water is a universal solvent and describe saturated, unsaturated, and concentrated solutions.",
            sol_text,
        )
    if "composition of water and the water cycle" in t_lower:
        return (
            "Describe the chemical composition of water and explain the detailed processes of the water cycle.",
            sol_text,
        )
    if "air pollutants and their sources" in t_lower:
        return (
            "Describe major air pollutants (carbon monoxide, PM, SO2), their human/industrial sources, and health hazards.",
            sol_text,
        )
    if "effects of polluted air" in t_lower:
        return (
            "Explain the harmful effects of air pollution, including respiratory diseases, acid rain, smog, and plant damage.",
            sol_text,
        )
    if "prevention and air-quality action" in t_lower:
        return (
            "Describe measures to prevent air pollution, including clean energy, public transport, industrial filters, and tree planting.",
            sol_text,
        )

    # 8. Solar system / Ecosystem / Food chain / Skeleton / Muscles / Diet / Energy
    if "the sun and planets" in t_lower:
        return (
            "Describe the structure of the solar system, listing the eight planets in order and comparing inner rocky vs outer gas planets.",
            sol_text,
        )
    if "rotation, revolution and satellites" in t_lower:
        return (
            "Distinguish rotation from revolution, explain Earth's day-night cycle, year duration, and natural satellites like the Moon.",
            sol_text,
        )
    if "producers, consumers and decomposers" in t_lower:
        return (
            "Explain the roles of producers, consumers (primary, secondary), and decomposers in an ecosystem with examples.",
            sol_text,
        )
    if "food chains, food webs and energy flow" in t_lower:
        return (
            "Explain how energy flows through food chains and food webs, and why energy decreases at higher trophic levels.",
            sol_text,
        )
    if "population changes and ecosystem balance" in t_lower:
        return (
            "Describe how changes in one population affect predator-prey relationships and overall food web balance.",
            sol_text,
        )
    if "biotic and abiotic ecosystem components" in t_lower:
        return (
            "Distinguish biotic and abiotic components of an ecosystem and explain how they interact to support life.",
            sol_text,
        )
    if "disturbance, biodiversity and resilience" in t_lower:
        return (
            "Explain how human activities disturb environmental equilibrium and how biodiversity increases ecosystem resilience.",
            sol_text,
        )
    if "skeleton, bones and support" in t_lower:
        return (
            "Describe the functions of the human skeleton, bone structure, and organ protection by skull, rib cage, and spine.",
            sol_text,
        )
    if "joints and their movement" in t_lower:
        return (
            "Explain fixed, hinge, ball-and-socket, and pivot joints with anatomical locations and movement directions.",
            sol_text,
        )
    if "muscles, tendons and movement" in t_lower:
        return (
            "Explain how antagonistic muscle pairs (biceps and triceps) work with tendons to move bones.",
            sol_text,
        )
    if "nutrients and their functions" in t_lower or "balanced diet and deficiency" in t_lower:
        return (
            "Explain the key nutrients required in a balanced diet, their main functions, and the effects of nutrient deficiency.",
            sol_text,
        )
    if "simple food tests" in t_lower:
        return (
            "Describe the step-by-step procedures for testing starch, fats, and proteins in food samples with expected color changes.",
            sol_text,
        )
    if "mass, volume and density" in t_lower:
        return (
            "Explain how mass, volume, and density are measured, write the formula used, and solve a density calculation problem.",
            sol_text,
        )
    if "forms and transformations of energy" in t_lower:
        return (
            "Describe different forms of energy and explain law of conservation of energy with energy transformation examples.",
            sol_text,
        )
    if "renewable and non-renewable sources" in t_lower:
        return (
            "Compare renewable and non-renewable energy sources with suitable examples and environmental impacts.",
            sol_text,
        )

    return None


def is_generic_topic_title_question(q_text: str, topic_title: str = "") -> bool:
    q_clean = q_text.casefold().strip()
    forbidden_patterns = (
        "explain the main ideas of",
        "explain the main properties of",
        "state the main idea of",
        "state the main properties of",
        "key principle behind",
        "why is the study of",
        "what is the key principle behind",
        "explain in detail the concept of",
        "give one example related to",
        "state one key observation related to",
        "is observed in daily life",
        "is observed and applied in daily life",
        "observed and applied in daily life",
        "observed in daily life",
        "key daily life applications of",
        "daily life applications of",
        "scientific principles supporting",
        "key principles, observations, and practical applications of",
        "explain in detail the structure, key functions, public importance, and constitutional role of",
        "explain in detail the geographical features, natural resources, environmental importance, and human impact of",
        "explain in detail the core principles, key developments, practical applications, and overall significance of",
        "explain in detail the political history, administration, social life, and cultural developments of",
        "explain in detail the significance, key events, and historical impact of",
        "describe in detail the process and scientific principles of",
        "analyze and explain in detail the core features, importance, and practical applications of",
    )
    if any(p in q_clean for p in forbidden_patterns):
        return True

    if "(variant" in q_clean or "variant 2" in q_clean:
        return True

    # Grammar guard: no "effects is", "topics is", "properties is", etc.
    if re.search(r"\b(effects|topics|properties|poles|principles|materials|forces|magnets|objects|lines|examples)\s+is\b", q_clean):
        return True

    if topic_title:
        t_clean = topic_title.casefold().strip()
        generic_phrases = (
            f"explain the main ideas of {t_clean}",
            f"explain the main properties of {t_clean}",
            f"state the main idea of {t_clean}",
            f"why is the study of {t_clean}",
            f"key principle behind {t_clean}",
            f"how {t_clean}",
            f"describe how {t_clean}",
            f"explain with an example how {t_clean}",
            f"applications of {t_clean}",
            f"example of {t_clean}",
            f"supporting {t_clean}",
        )
        if any(g in q_clean for g in generic_phrases):
            return True

    return False



def extract_question_concept_words(q_text: str) -> set[str]:
    text = q_text.casefold().strip()
    text = re.sub(r"[\(\[\{]\s*variant\s*\d*\s*[\)\]\}]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s]", " ", text)
    stop_words = {
        "explain", "state", "describe", "why", "how", "what", "which", "when", "where",
        "example", "examples", "following", "with", "from", "that", "this", "these", "those",
        "can", "could", "would", "should", "does", "do", "did", "is", "are", "was", "were",
        "and", "the", "for", "one", "two", "three", "both", "all", "any", "each", "other",
        "main", "ideas", "properties", "concept", "principles", "observation", "demonstrate",
        "relative", "respect", "given", "below", "show", "find", "calculate"
    }
    words = [w for w in text.split() if len(w) > 2 and w not in stop_words]
    normalized = set()
    for w in words:
        if w in {"moving", "moves", "moved", "motion"}:
            normalized.add("motion")
        elif w in {"passengers", "passenger"}:
            normalized.add("passenger")
        elif w in {"seated", "seat", "seats"}:
            normalized.add("seat")
        elif w in {"forces", "force", "forced"}:
            normalized.add("force")
        elif w in {"speeds", "speed"}:
            normalized.add("speed")
        elif w in {"magnets", "magnet", "magnetic"}:
            normalized.add("magnet")
        elif w in {"poles", "pole"}:
            normalized.add("pole")
        elif w in {"attracts", "attraction", "attract"}:
            normalized.add("attract")
        elif w in {"repels", "repulsion", "repel"}:
            normalized.add("repel")
        else:
            normalized.add(w)
    return normalized


def extract_question_intent(q_text: str) -> str:
    text = q_text.casefold().strip()
    text = re.sub(r"[\(\[\{]\s*variant\s*\d*\s*[\)\]\}]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w\s]", " ", text)
    fillers = (
        "explain the main ideas of",
        "explain the main properties of",
        "explain the main idea of",
        "explain the main property of",
        "key principle behind",
        "why is the study of",
        "is significant",
        "what can be concluded",
        "explain with an example",
        "explain step by step",
        "explain in detail",
        "briefly explain",
        "state the main idea of",
        "state the main principle of",
        "give one example related to",
        "give one example of",
        "give one role of",
        "what is meant by",
        "what is the concept of",
        "what is the main concept of",
        "what is",
        "what are",
        "why is",
        "why do",
        "why does",
        "how does",
        "how can",
        "classify",
        "state",
        "define",
    )
    for filler in fillers:
        text = text.replace(filler, " ")
    words = [w for w in text.split() if len(w) > 2]
    return " ".join(words)


def is_duplicate_question(
    topic_title: str,
    q_text: str,
    used_q_texts: set[str],
    used_intents: set[tuple[str, str]],
) -> bool:
    if is_generic_topic_title_question(q_text, topic_title):
        return True

    q_norm = " ".join(q_text.casefold().strip().split())
    if q_norm in used_q_texts:
        return True

    intent = extract_question_intent(q_text)
    if intent:
        topic_norm = " ".join(topic_title.casefold().strip().split())
        if (topic_norm, intent) in used_intents:
            return True

    new_concepts = extract_question_concept_words(q_text)
    if len(new_concepts) >= 2:
        for prev_q in used_q_texts:
            prev_concepts = extract_question_concept_words(prev_q)
            overlap = new_concepts & prev_concepts
            if len(overlap) >= 3:
                return True
            if "passenger" in overlap and len(overlap & {"rest", "motion", "seat", "bus"}) >= 2:
                return True

    return False


def mark_question_used(
    topic_title: str,
    q_text: str,
    used_q_texts: set[str],
    used_intents: set[tuple[str, str]],
) -> None:
    q_norm = " ".join(q_text.casefold().strip().split())
    used_q_texts.add(q_norm)
    intent = extract_question_intent(q_text)
    if intent:
        topic_norm = " ".join(topic_title.casefold().strip().split())
        used_intents.add((topic_norm, intent))


def is_suitable_for_section(q_text: str, sol_text: str, mark_per_q: int) -> bool:
    q_lower = q_text.casefold().strip()
    if is_generic_topic_title_question(q_text):
        return False

    sol_text_clean = sol_text.strip()
    sol_words = len(sol_text_clean.split())

    one_line_prefixes = (
        "what was ",
        "who was ",
        "which instrument",
        "name the three main parts",
        "name the three",
        "give one role",
        "which ",
        "name ",
        "give one ",
        "what is ",
        "what are ",
        "define ",
        "state ",
        "where is ",
        "what happens when ",
        "identify ",
        "fill in ",
        "who ",
    )
    is_one_line = any(q_lower.startswith(prefix) for prefix in one_line_prefixes) or (
        sol_words < 15 and not any(k in q_lower for k in ("explain", "describe", "detail", "process", "how"))
    )

    heavy_prefixes = (
        "explain with an example",
        "explain in detail",
        "describe the process",
        "how will you show",
        "how can you show",
        "draw and explain",
        "describe ",
    )
    is_heavy_explanation = any(q_lower.startswith(prefix) for prefix in heavy_prefixes) or (
        sol_words >= 25 and (sol_text_clean.count(".") >= 2 or "\n" in sol_text_clean or ";" in sol_text_clean)
    )

    if mark_per_q == 6:
        if is_one_line:
            return False
        if any(q_lower.startswith(p) for p in ("what was", "who was", "name", "give one", "which", "what is", "what are", "define", "where is")):
            return False
        if sol_words < 20 and not is_heavy_explanation:
            return False
        if "scientific principles, and applications of" in q_lower:
            return False
        if "core scientific principles of" in q_lower:
            return False
        return True

    elif mark_per_q == 1:
        if is_heavy_explanation:
            return False
        return True

    elif mark_per_q == 2:
        if sol_words > 90:
            return False
        return True

    elif mark_per_q == 3:
        simple_3m_prefixes = (
            "give one role",
            "give one",
            "which method",
            "which instrument",
            "which ",
            "name ",
            "what is ",
            "what are ",
            "state one",
            "state ",
            "define ",
            "fill in",
            "identify ",
        )
        is_3m_explanation_type = any(
            k in q_lower for k in (
                "explain", "distinguish", "why", "how", "describe",
                "compare", "calculate", "reason", "example"
            )
        )
        if any(q_lower.startswith(prefix) for prefix in simple_3m_prefixes) and not is_3m_explanation_type:
            return False
        if is_one_line and not is_3m_explanation_type:
            return False
        if sol_words < 12 and not is_3m_explanation_type:
            return False
        return True

    return True


def get_topic_fallback_variants(topic: SyllabusTopic, mark_per_q: int) -> list[tuple[str, str, str, int]]:
    variants: list[tuple[str, str, str, int]] = []
    t_lower = topic.title.casefold().strip()

    # 1. From existing exercises and practice questions
    for i, q in enumerate(topic.exercises):
        if q and q.strip() and i < len(topic.solutions) and topic.solutions[i] and topic.solutions[i].strip():
            q_txt = q.strip()
            sol_txt = topic.solutions[i].strip()
            if is_generic_topic_title_question(q_txt, topic.title):
                continue
            im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
            if im == mark_per_q:
                variants.append((topic.title, q_txt, sol_txt, mark_per_q))
    for i, q in enumerate(topic.practice_questions):
        if q and q.strip() and i < len(topic.practice_solutions) and topic.practice_solutions[i] and topic.practice_solutions[i].strip():
            q_txt = q.strip()
            sol_txt = topic.practice_solutions[i].strip()
            if is_generic_topic_title_question(q_txt, topic.title):
                continue
            im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
            if im == mark_per_q:
                variants.append((topic.title, q_txt, sol_txt, mark_per_q))

    # 2. Topic-specific natural 1-mark and 2-mark fallback questions
    if mark_per_q == 1:
        if "motion and reference point" in t_lower:
            variants.append((
                topic.title,
                "What is the term for a fixed point used to decide whether an object is in motion?",
                "A reference point.",
                1,
            ))
            variants.append((
                topic.title,
                "What type of motion does a simple pendulum show as it swings to and fro?",
                "Oscillatory motion.",
                1,
            ))
            variants.append((
                topic.title,
                "What type of motion is shown by a car moving along a straight flat road?",
                "Linear motion.",
                1,
            ))
            variants.append((
                topic.title,
                "What type of motion is shown by the hands of a mechanical clock?",
                "Circular motion.",
                1,
            ))
        elif "force and its effects" in t_lower:
            variants.append((
                topic.title,
                "Is friction classified as a contact force or a non-contact force?",
                "Friction is a contact force.",
                1,
            ))
            variants.append((
                topic.title,
                "Is gravitational attraction classified as a contact force or a non-contact force?",
                "Gravity is a non-contact force.",
                1,
            ))
            variants.append((
                topic.title,
                "What can an unbalanced force change about a moving body?",
                "It can change the speed or direction of motion.",
                1,
            ))
            variants.append((
                topic.title,
                "Do balanced forces change the speed or direction of motion of an object?",
                "No, balanced forces do not change an object's speed or direction.",
                1,
            ))
        elif "speed and its measurement" in t_lower:
            variants.append((
                topic.title,
                "State the SI unit of speed.",
                "Metres per second (m/s).",
                1,
            ))
            variants.append((
                topic.title,
                "Write the mathematical formula used to calculate speed.",
                "Speed = distance / time.",
                1,
            ))
            variants.append((
                topic.title,
                "What quantity is obtained by dividing total distance covered by total time taken?",
                "Average speed.",
                1,
            ))
            variants.append((
                topic.title,
                "Name one unit used to measure speed of motor vehicles over long distances.",
                "Kilometres per hour (km/h).",
                1,
            ))

    if mark_per_q == 2:
        if "magnetic materials and poles" in t_lower:
            variants.append((
                topic.title,
                "Classify an iron nail, an aluminium spoon and a wooden ruler by whether a common magnet attracts them strongly.",
                "The iron nail is magnetic and is attracted strongly. The aluminium spoon and wooden ruler are not strongly attracted by a common classroom magnet.",
                2,
            ))
            variants.append((
                topic.title,
                "Why is magnetic force usually strongest near the two poles of a bar magnet?",
                "Magnetic field lines are concentrated near the ends, creating maximum magnetic force at the north and south poles.",
                2,
            ))
            variants.append((
                topic.title,
                "What happens when a bar magnet is broken into two pieces?",
                "Each broken piece becomes a complete magnet with its own north pole and south pole.",
                2,
            ))
            variants.append((
                topic.title,
                "How can you test whether an object is magnetic using a bar magnet?",
                "Bring a bar magnet near the object; if it is attracted strongly to either pole of the magnet, the object is magnetic.",
                2,
            ))
        elif "attraction, repulsion and magnetic field" in t_lower:
            variants.append((
                topic.title,
                "What happens when like poles and unlike poles of magnets are brought near each other?",
                "Unlike poles attract each other, while like poles push away or repel each other.",
                2,
            ))
            variants.append((
                topic.title,
                "What does a crowded pattern of magnetic field lines show?",
                "It represents a stronger magnetic field in that region, where magnetic force is greater.",
                2,
            ))
            variants.append((
                topic.title,
                "How can attraction and repulsion be used to identify magnet poles?",
                "Repulsion is the sure test of magnetism because a known pole will repel only a like pole of another magnet.",
                2,
            ))
            variants.append((
                topic.title,
                "Why do two north poles repel each other?",
                "Like magnetic poles exert repulsive forces on each other due to the alignment of their magnetic field lines.",
                2,
            ))
        elif "compass and earth's magnetism" in t_lower or "compass and earth" in t_lower:
            variants.append((
                topic.title,
                "Why does a compass needle turn and settle in a particular direction?",
                "Earth acts as a giant magnet, and its magnetic field exerts a turning effect on the needle until it aligns approximately north-south.",
                2,
            ))
            variants.append((
                topic.title,
                "What can a compass show about direction in a classroom?",
                "Its marked north-seeking end points toward the north direction of the room, assuming no magnetic objects disturb it.",
                2,
            ))
            variants.append((
                topic.title,
                "Why does a freely suspended magnet point roughly north-south?",
                "The magnetic field of the Earth exerts force on the freely suspended magnet, causing it to align along the geomagnetic meridian.",
                2,
            ))
            variants.append((
                topic.title,
                "How does Earth's magnetic field affect a compass needle?",
                "Earth's magnetic field aligns the magnetized compass needle along the magnetic north-south direction.",
                2,
            ))
        elif "motion and reference point" in t_lower:
            variants.append((
                topic.title,
                "Explain how motion depends on the observer's reference point with one example.",
                "A passenger sitting in a moving bus is at rest relative to other passengers inside the bus, but in motion relative to trees and buildings outside on the roadside.",
                2,
            ))
            variants.append((
                topic.title,
                "Distinguish rest and motion using a passenger in a moving bus as an example.",
                "Rest means an object does not change its position relative to a reference frame, while motion means position changes over time. A bus passenger is at rest relative to the bus seat but in motion relative to the ground.",
                2,
            ))
            variants.append((
                topic.title,
                "Classify linear, circular and oscillatory motion with one example each.",
                "Linear motion: a car moving on a straight road. Circular motion: hands of a clock. Oscillatory motion: a swinging pendulum.",
                2,
            ))
        elif "force and its effects" in t_lower:
            variants.append((
                topic.title,
                "State two effects of force on an object with examples.",
                "1. Force can change the speed of a moving object (e.g. pressing a car accelerator). 2. Force can change the direction of motion (e.g. hitting a cricket ball with a bat).",
                2,
            ))
            variants.append((
                topic.title,
                "Classify contact and non-contact forces with one example of each.",
                "Contact forces require physical touch (e.g. friction or muscular force). Non-contact forces act at a distance without physical touch (e.g. magnetic or gravitational force).",
                2,
            ))
            variants.append((
                topic.title,
                "How can force change the speed, direction or shape of an object?",
                "Pushing or pulling can increase or decrease speed, alter the path of a moving body, or deform an object like squeezing a rubber ball.",
                2,
            ))
        elif "speed and its measurement" in t_lower:
            variants.append((
                topic.title,
                "Find the speed of a runner who covers 100 metres in 20 seconds.",
                "Speed = Distance / Time = 100 metres / 20 seconds = 5 m/s.",
                2,
            ))
            variants.append((
                topic.title,
                "A toy car covers 24 metres at 3 m/s. Find the time taken.",
                "Time = Distance / Speed = 24 metres / 3 m/s = 8 seconds.",
                2,
            ))
            variants.append((
                topic.title,
                "Explain why speed is calculated as distance divided by time.",
                "Speed measures the rate of motion, which is the amount of distance covered per unit of time (metres per second or kilometres per hour).",
                2,
            ))

    # 3. From examples
    if mark_per_q == 3:
        for ex in topic.examples:
            if ex and ex.strip():
                variants.append(
                    (
                        topic.title,
                        f"Explain with an example: {ex.strip()}",
                        f"Example solution: {ex.strip()}",
                        3,
                    )
                )

    # 4. Natural 6-mark builder
    if mark_per_q == 6:
        nat_6m = build_natural_6mark_question(topic.title, topic.explanation, list(topic.examples))
        if nat_6m is not None:
            q_6m_txt, sol_6m_txt = nat_6m
            variants.append((topic.title, q_6m_txt, sol_6m_txt, 6))

    # 5. Objective / Explanation based variants using learning objectives
    if topic.explanation and topic.explanation.strip():
        exp_clean = topic.explanation.strip()
        if mark_per_q == 2:
            for obj in topic.learning_objectives:
                if obj.startswith("Explain "):
                    q_2m = f"{obj.strip()}"
                    if is_generic_topic_title_question(q_2m, topic.title):
                        continue
                    sol_2m = exp_clean if len(exp_clean.split()) < 30 else ". ".join(exp_clean.split('.')[:2]).strip()
                    if len(sol_2m.split()) < 12:
                        sol_2m = f"{sol_2m} This is an essential scientific concept of {topic.title}."
                    if determine_question_intended_marks(q_2m, sol_2m) == 2:
                        variants.append((topic.title, q_2m, sol_2m, 2))

    return variants


def render_test_paper(
    syllabus: BoardSyllabus,
    scope: TestPaperScope,
    *,
    context: StudentLearningContext | None = None,
    message: str = "",
    randomize: bool | None = None,
    seed: int | str | None = None,
) -> tuple[str, GeneratedTestPaper]:
    if scope.scope_type == "ambiguous":
        msg = "Please select or name the chapter for the chapter test."
        empty_paper = GeneratedTestPaper(
            board=syllabus.board,
            medium=syllabus.medium,
            standard=syllabus.standard,
            subject=syllabus.subject,
            scope_description=scope.description,
            total_marks=0,
            duration_minutes=0,
            questions=[],
            source_footer="GyanVerse AI Tutor",
        )
        return msg, empty_paper

    lines: list[str] = []
    board_name = (
        "Gujarat Secondary and Higher Secondary Education Board (GSEB)"
        if syllabus.board.casefold() == "gseb"
        else syllabus.board
    )
    lines.append(board_name)
    lines.append(
        f"Medium: {syllabus.medium} | Standard: {syllabus.standard} | Subject: {syllabus.subject}"
    )
    lines.append(f"Test Paper: {scope.description}")
    lines.append(
        f"Time: {format_test_paper_duration(scope.duration_minutes)} | Total Marks: {scope.total_marks} Marks"
    )
    lines.append("")
    lines.append("Instructions:")
    lines.append("1. All questions are compulsory.")
    lines.append("2. Figures to the right indicate full marks for each question.")
    lines.append("3. Read all questions carefully before writing your answers.")
    lines.append("")

    SECTION_SPECS = {
        20: [
            ("Section A (1 Mark Each)", 1, 5),
            ("Section B (2 Marks Each)", 2, 3),
            ("Section C (3 Marks Each)", 3, 1),
            ("Section D (6 Marks Each)", 6, 1),
        ],
        25: [
            ("Section A (1 Mark Each)", 1, 5),
            ("Section B (2 Marks Each)", 2, 4),
            ("Section C (3 Marks Each)", 3, 2),
            ("Section D (6 Marks Each)", 6, 1),
        ],
        50: [
            ("Section A (1 Mark Each)", 1, 10),
            ("Section B (2 Marks Each)", 2, 8),
            ("Section C (3 Marks Each)", 3, 4),
            ("Section D (6 Marks Each)", 6, 2),
        ],
        80: [
            ("Section A (1 Mark Each)", 1, 20),
            ("Section B (2 Marks Each)", 2, 12),
            ("Section C (3 Marks Each)", 3, 6),
            ("Section D (6 Marks Each)", 6, 3),
        ],
        100: [
            ("Section A (1 Mark Each)", 1, 20),
            ("Section B (2 Marks Each)", 2, 16),
            ("Section C (3 Marks Each)", 3, 8),
            ("Section D (6 Marks Each)", 6, 4),
        ],
    }
    specs = SECTION_SPECS.get(scope.total_marks, SECTION_SPECS[25])

    target_chapters = scope.chapters if (scope.chapters and len(scope.chapters) > 0) else syllabus.chapters

    pool: list[tuple[str, str, str, int]] = []
    if len(target_chapters) > 1:
        # Multi-chapter or Full-book: Interleave by chapter
        ch_pools: list[list[tuple[str, str, str, int]]] = []
        for ch in target_chapters:
            c_items: list[tuple[str, str, str, int]] = []
            t_items_list: list[list[tuple[str, str, str, int]]] = []
            for t in ch.topics:
                t_q: list[tuple[str, str, str, int]] = []
                for i, q in enumerate(t.exercises):
                    if q and q.strip() and i < len(t.solutions) and t.solutions[i] and t.solutions[i].strip():
                        q_txt = q.strip()
                        sol_txt = t.solutions[i].strip()
                        im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
                        t_q.append((t.title, q_txt, sol_txt, im))
                for i, q in enumerate(t.practice_questions):
                    if q and q.strip() and i < len(t.practice_solutions) and t.practice_solutions[i] and t.practice_solutions[i].strip():
                        q_txt = q.strip()
                        sol_txt = t.practice_solutions[i].strip()
                        im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
                        t_q.append((t.title, q_txt, sol_txt, im))
                for ex in t.examples:
                    if ex and ex.strip():
                        t_q.append(
                            (
                                t.title,
                                f"Explain with an example: {ex.strip()}",
                                f"Example solution: {ex.strip()}",
                                3,
                            )
                        )
                nat_6m = build_natural_6mark_question(t.title, t.explanation, t.examples)
                if nat_6m is not None:
                    q_6m_txt, sol_6m_txt = nat_6m
                    t_q.append((t.title, q_6m_txt, sol_6m_txt, 6))

                for mark_b in (1, 2, 3, 6):
                    for v in get_topic_fallback_variants(t, mark_b):
                        if v not in t_q:
                            t_q.append(v)

                if t_q:
                    t_items_list.append(t_q)

            idx = 0
            while True:
                added = False
                for t_q in t_items_list:
                    if idx < len(t_q):
                        c_items.append(t_q[idx])
                        added = True
                if not added:
                    break
                idx += 1
            if c_items:
                ch_pools.append(c_items)

        idx = 0
        while True:
            added = False
            for c_items in ch_pools:
                if idx < len(c_items):
                    pool.append(c_items[idx])
                    added = True
            if not added:
                break
            idx += 1
    elif target_chapters:
        # Single-chapter: Interleave by topic
        ch = target_chapters[0]
        t_items_list: list[list[tuple[str, str, str, int]]] = []
        for t in ch.topics:
            t_q: list[tuple[str, str, str, int]] = []
            for i, q in enumerate(t.exercises):
                if q and q.strip() and i < len(t.solutions) and t.solutions[i] and t.solutions[i].strip():
                    q_txt = q.strip()
                    sol_txt = t.solutions[i].strip()
                    im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
                    t_q.append((t.title, q_txt, sol_txt, im))
            for i, q in enumerate(t.practice_questions):
                if q and q.strip() and i < len(t.practice_solutions) and t.practice_solutions[i] and t.practice_solutions[i].strip():
                    q_txt = q.strip()
                    sol_txt = t.practice_solutions[i].strip()
                    im = determine_question_intended_marks(q_txt, sol_txt, is_example=False)
                    t_q.append((t.title, q_txt, sol_txt, im))
            for ex in t.examples:
                if ex and ex.strip():
                    t_q.append(
                        (
                            t.title,
                            f"Explain with an example: {ex.strip()}",
                            f"Example solution: {ex.strip()}",
                            3,
                        )
                    )
            nat_6m = build_natural_6mark_question(t.title, t.explanation, t.examples)
            if nat_6m is not None:
                q_6m_txt, sol_6m_txt = nat_6m
                t_q.append((t.title, q_6m_txt, sol_6m_txt, 6))

            for mark_b in (1, 2, 3, 6):
                for v in get_topic_fallback_variants(t, mark_b):
                    if v not in t_q:
                        t_q.append(v)

            if t_q:
                t_items_list.append(t_q)

        idx = 0
        while True:
            added = False
            for t_q in t_items_list:
                if idx < len(t_q):
                    pool.append(t_q[idx])
                    added = True
            if not added:
                break
            idx += 1

    if not pool:
        pool = [
            (
                "General",
                "Explain the key concepts of the topic.",
                "Use the installed topic guide for explanation and practice.",
                1,
            )
        ]

    if seed is not None:
        do_random = True
    elif randomize is not None:
        do_random = randomize
    else:
        do_random = is_random_test_request(message)

    if do_random:
        if seed is None:
            seed = extract_test_seed(message)
        if seed is None:
            seed = random.randrange(1, 1_000_000_000)
        rng = random.Random(seed)
    else:
        rng = None

    used_q_texts: set[str] = set()
    used_intents: set[tuple[str, str]] = set()

    q_num = 1
    sec_answers: list[tuple[str, list[tuple[int, str, str]]]] = []
    items: list[TestPaperQuestionItem] = []
    pool_idx = 0

    if rng is not None:
        available_pool = list(pool)
        rng.shuffle(available_pool)
    else:
        available_pool = list(pool)

    for sec_title, mark_per_q, q_count in specs:
        sec_tot = mark_per_q * q_count
        lines.append(f"{sec_title} — Total: {sec_tot} Marks")
        answers_list: list[tuple[int, str, str]] = []
        for _ in range(q_count):
            selected_item: tuple[str, str, str, int] | None = None

            if rng is not None:
                # 1. Primary rule: match intended_m == mark_per_q AND is_suitable_for_section AND non-duplicate
                candidates_p1 = [
                    (idx, item) for idx, item in enumerate(available_pool)
                    if not is_duplicate_question(item[0], item[1], used_q_texts, used_intents) and item[3] == mark_per_q and is_suitable_for_section(item[1], item[2], mark_per_q)
                ]
                if candidates_p1:
                    idx, selected_item = rng.choice(candidates_p1)
                    available_pool.pop(idx)

                # 2. Secondary rule: match intended_m == mark_per_q AND non-duplicate in available_pool
                if selected_item is None:
                    candidates_p2 = [
                        (idx, item) for idx, item in enumerate(available_pool)
                        if not is_duplicate_question(item[0], item[1], used_q_texts, used_intents) and item[3] == mark_per_q and is_suitable_for_section(item[1], item[2], mark_per_q)
                    ]
                    if candidates_p2:
                        idx, selected_item = rng.choice(candidates_p2)
                        available_pool.pop(idx)

                # 3. Match intended_m == mark_per_q in base pool
                if selected_item is None:
                    candidates_p3 = [
                        item for item in pool
                        if not is_duplicate_question(item[0], item[1], used_q_texts, used_intents) and item[3] == mark_per_q and is_suitable_for_section(item[1], item[2], mark_per_q)
                    ]
                    if candidates_p3:
                        selected_item = rng.choice(candidates_p3)
            else:
                # Deterministic mode: sequential search through pool for next unused item
                while pool_idx < len(pool):
                    candidate = pool[pool_idx]
                    pool_idx += 1
                    if not is_duplicate_question(candidate[0], candidate[1], used_q_texts, used_intents):
                        selected_item = candidate
                        break

            # Safe Fallback Level A: strictly search target_chapters for topic fallback variants matching mark_per_q
            if selected_item is None:
                for ch in target_chapters:
                    for t in ch.topics:
                        variants = get_topic_fallback_variants(t, mark_per_q)
                        if rng is not None:
                            rng.shuffle(variants)
                        for v_item in variants:
                            t_lbl, q_t, sol_t, im = v_item
                            if not is_duplicate_question(t_lbl, q_t, used_q_texts, used_intents) and not is_generic_topic_title_question(q_t, t_lbl) and (im == mark_per_q or determine_question_intended_marks(q_t, sol_t) == mark_per_q) and is_suitable_for_section(q_t, sol_t, mark_per_q):
                                selected_item = (t_lbl, q_t, sol_t, mark_per_q)
                                break
                        if selected_item is not None:
                            break
                    if selected_item is not None:
                        break

            # Safe Fallback Level B: strictly search target_chapters natural exercises, practice questions, and examples
            if selected_item is None:
                for ch in target_chapters:
                    for t in ch.topics:
                        candidate_qs = []
                        for i, q in enumerate(t.exercises):
                            if i < len(t.solutions):
                                candidate_qs.append((q.strip(), t.solutions[i].strip()))
                        for i, q in enumerate(t.practice_questions):
                            if i < len(t.practice_solutions):
                                candidate_qs.append((q.strip(), t.practice_solutions[i].strip()))
                        for ex in t.examples:
                            if ex and ex.strip():
                                candidate_qs.append((f"Explain with an example: {ex.strip()}", f"{ex.strip()} illustrates {t.title}: {t.explanation}"))

                        for q_t, sol_t in candidate_qs:
                            im = determine_question_intended_marks(q_t, sol_t)
                            if (
                                not is_duplicate_question(t.title, q_t, used_q_texts, used_intents)
                                and not is_generic_topic_title_question(q_t, t.title)
                                and (im == mark_per_q or (mark_per_q != 6 and im >= 1))
                                and is_suitable_for_section(q_t, sol_t, mark_per_q)
                            ):
                                selected_item = (t.title, q_t, sol_t, mark_per_q)
                                break
                        if selected_item is not None:
                            break
                    if selected_item is not None:
                        break

            # Safe Fallback Level C (Emergency In-Chapter Fallback): Strictly generate in-chapter topic questions from target_chapters only
            if selected_item is None:
                sorted_topics: list[tuple[int, BoardSyllabusChapter, SyllabusTopic]] = []
                for ch in target_chapters:
                    for t in ch.topics:
                        used_cnt = sum(1 for (t_name, _) in used_intents if t_name == t.title)
                        sorted_topics.append((used_cnt, ch, t))
                sorted_topics.sort(key=lambda item: item[0])
                if rng is not None and sorted_topics:
                    min_cnt = sorted_topics[0][0]
                    min_candidates = [item for item in sorted_topics if item[0] == min_cnt]
                    rng.shuffle(min_candidates)
                    sorted_topics = min_candidates + [item for item in sorted_topics if item[0] > min_cnt]

                for _, ch, t in sorted_topics:
                    t_title = t.title
                    exp_text = (t.explanation or "Scientific principle and observation.").strip()

                    if mark_per_q == 1:
                        q_t = f"What is the key scientific concept of {t_title}?"
                        sol_t = exp_text.split('.')[0].strip() + "."
                        if len(sol_t.split()) > 18:
                            sol_t = " ".join(sol_t.split()[:14]) + "."
                    elif mark_per_q == 2:
                        q_t = f"Explain {t_title} with one key scientific observation."
                        sentences = [s.strip() for s in exp_text.split('.') if s.strip()]
                        sol_t = ". ".join(sentences[:2]).strip() + "."
                    elif mark_per_q == 3:
                        ex_str = t.examples[0] if t.examples else f"observation of {t_title}"
                        q_t = f"Explain with an example: {ex_str}"
                        sol_t = f"Example solution: {ex_str} demonstrates {exp_text}"
                    else:  # 6 marks
                        nat_6m = build_natural_6mark_question(t_title, exp_text, list(t.examples))
                        if nat_6m is not None:
                            q_t, sol_t = nat_6m
                        else:
                            q_t = f"Explain the key principles, observations, and main features of {t_title}."
                            sol_t = f"{exp_text} Key examples include: {', '.join(t.examples) if t.examples else 'natural phenomena'}."

                    q_clean_norm = " ".join(q_t.casefold().strip().split())
                    if q_clean_norm not in used_q_texts and not is_generic_topic_title_question(q_t, t_title):
                        selected_item = (t_title, q_t, sol_t, mark_per_q)
                        break

            topic_title, q_text, sol_text, raw_intended_m = selected_item
            mark_question_used(topic_title, q_text, used_q_texts, used_intents)

            lbl = "Mark" if mark_per_q == 1 else "Marks"
            lines.append(f"{q_num}. [{topic_title}] {q_text} ({mark_per_q} {lbl})")
            answers_list.append((q_num, topic_title, sol_text))
            eval_rules = derive_structured_evaluation_rules(q_text, sol_text, topic_title)
            items.append(
                TestPaperQuestionItem(
                    question_num=q_num,
                    section_title=sec_title,
                    topic_title=topic_title,
                    question_text=q_text,
                    max_marks=mark_per_q,
                    solution_guide=sol_text,
                    intended_marks=mark_per_q,
                    required_concepts=eval_rules.required_concepts,
                    forbidden_concepts=eval_rules.forbidden_concepts,
                    numeric_formula=eval_rules.numeric_formula,
                    expected_value=eval_rules.expected_value,
                    unit=eval_rules.unit,
                    contradiction_patterns=eval_rules.contradiction_patterns,
                )
            )
            q_num += 1
        lines.append("")
        sec_answers.append((sec_title, answers_list))

    origin_label = "Teacher-authored content"
    footer = (
        f"Source type: {origin_label}. "
        f"{syllabus.textbook}; edition {syllabus.source.edition}."
    )

    if scope.include_answers:
        lines.append("Answer Guide:")
        lines.append("")
        for sec_title, ans_items in sec_answers:
            lines.append(f"{sec_title} Answers:")
            for q_n, t_title, sol_t in ans_items:
                lines.append(f"{q_n}. [{t_title}] {sol_t}")
            lines.append("")

    lines.append(footer)
    paper_obj = GeneratedTestPaper(
        board=syllabus.board,
        medium=syllabus.medium,
        standard=syllabus.standard,
        subject=syllabus.subject,
        scope_description=scope.description,
        total_marks=scope.total_marks,
        duration_minutes=scope.duration_minutes,
        questions=items,
        source_footer=footer,
    )
    return "\n".join(lines), paper_obj


def _source_description(match: SyllabusTopicMatch) -> str:
    origin_label = {
        "official": "Official source content",
        "teacher_authored": "Teacher-authored content",
        "ai_generated": "AI-generated practice content",
    }.get(match.topic.content_origin, "Validated local content")
    return (
        f"Source type: {origin_label}. "
        f"{match.syllabus.textbook}; edition {match.syllabus.source.edition}."
    )


def render_syllabus_grounding(match: SyllabusTopicMatch) -> str:
    topic = match.topic
    lines = [
        f"Board: {match.syllabus.board}",
        f"Medium: {match.syllabus.medium}",
        f"Standard: {match.syllabus.standard}",
        f"Subject: {match.syllabus.subject}",
        f"Chapter: {match.chapter.number}. {match.chapter.title}",
        f"Topic: {topic.title}",
        f"Content origin: {topic.content_origin}",
    ]
    if topic.learning_objectives:
        lines.append("Learning objectives: " + "; ".join(topic.learning_objectives))
    if topic.explanation:
        lines.append("Explanation: " + topic.explanation)
    if topic.examples:
        lines.append("Examples: " + " | ".join(topic.examples))
    if topic.exercises:
        lines.append("Exercises: " + " | ".join(topic.exercises))
    if topic.solutions:
        lines.append("Solution logic: " + " | ".join(topic.solutions))
    if topic.practice_questions:
        lines.append("Practice templates: " + " | ".join(topic.practice_questions))
    if topic.practice_solutions:
        lines.append("Practice answer logic: " + " | ".join(topic.practice_solutions))
    return "\n".join(lines)


def render_syllabus_match(
    match: SyllabusTopicMatch,
    *,
    context: StudentLearningContext,
    message: str = "",
    teaching_guidance: str = "",
) -> str:
    syllabus = match.syllabus
    topic = match.topic

    if not match.has_validated_content:
        return (
            f"{topic.title} is listed in the installed {syllabus.board} "
            f"{syllabus.medium} Standard {syllabus.standard} {syllabus.subject} syllabus, "
            "but a validated local explanation for this topic is not installed yet. "
            "I will not invent textbook content or label an AI-generated answer as official."
        )

    request = classify_syllabus_tutor_request(message)
    chapter_level = match.matched_by in {"message-chapter", "context-chapter-fallback"}

    sections: list[str] = []
    if request.intent == "explain" and not chapter_level:
        sections.append(topic.title)
        if topic.explanation:
            sections.append(topic.explanation)
        if topic.examples:
            sections.append("Example: " + topic.examples[0])
    elif request.intent == "example":
        selected = (
            topic.examples[: request.requested_count]
            if topic.examples
            else ["No specific example is installed for this topic."]
        )
        sections.append(topic.title)
        if len(selected) == 1:
            sections.append("Example: " + selected[0])
        else:
            sections.append("Examples:\n" + _numbered_lines(selected))
    elif request.intent == "test":
        scope = parse_test_paper_scope(message, context, match.syllabus)
        raw_text, _ = render_test_paper(match.syllabus, scope, context=context, message=message)
        return raw_text
    elif request.intent in {"practice", "homework"}:
        bank = _topic_question_bank(
            topic,
            prefer_solved=request.include_answers,
        )
        selected = bank[: request.requested_count]
        heading = "Homework" if request.intent == "homework" else "Practice"
        sections.extend((topic.title, f"{heading}:\n" + _numbered_lines([q for q, _ in selected])))
        if request.include_answers:
            guides = [
                guide or "Use the topic explanation and justify the response with evidence."
                for _, guide in selected
            ]
            sections.append("Answer guide:\n" + _numbered_lines(guides))
    elif request.intent == "hint":
        bank = _topic_question_bank(topic, prefer_solved=True)
        selected_index = _requested_question_index(bank, message)
        sections.append(topic.title)
        if selected_index < 0 and bank:
            selected_index = 0
        if 0 <= selected_index < len(bank):
            question, guide = bank[selected_index]
            hints = _local_question_hints(topic, question, guide)[: request.requested_count]
            sections.append("Question: " + question)
            if len(hints) == 1:
                sections.append("Hint: " + hints[0])
            else:
                sections.append("Hints:\n" + _numbered_lines(hints))
        else:
            if bank:
                question, guide = bank[0]
                hints = _local_question_hints(topic, question, guide)[: request.requested_count]
                sections.append("Question: " + question)
                if len(hints) == 1:
                    sections.append("Hint: " + hints[0])
                else:
                    sections.append("Hints:\n" + _numbered_lines(hints))
            else:
                hints = _local_question_hints(topic, topic.title, topic.explanation)[: request.requested_count]
                if len(hints) == 1:
                    sections.append("Hint: " + hints[0])
                else:
                    sections.append("Hints:\n" + _numbered_lines(hints))
    elif request.intent == "solution":
        bank = _topic_question_bank(topic, prefer_solved=True)
        selected_index = _requested_question_index(bank, message)
        sections.append(topic.title)
        if 0 <= selected_index < len(bank):
            question, guide = bank[selected_index]
            sections.append("Question: " + question)
            sections.append(
                "Validated solution: "
                + (guide or "Use the topic explanation and show the supporting evidence.")
            )
        else:
            sections.append(
                "Tell me the question number or paste the exact homework question. "
                "I will explain the method before giving the final answer."
            )
    elif request.intent == "evaluate":
        bank = _topic_question_bank(topic, prefer_solved=True)
        selected_index = _requested_question_index(bank, message)
        sections.append(topic.title)
        if 0 <= selected_index < len(bank):
            question, guide = bank[selected_index]
            student_answer = _student_review_answer(message)
            sections.append("Question: " + question)
            if student_answer:
                sections.append("Your answer: " + student_answer)

            result_header, reason_body = _evaluate_student_answer(
                student_answer,
                guide,
                question,
                topic=topic,
            )
            sections.append(result_header)
            sections.append("Reason: " + reason_body)

            if guide:
                heading = "Correct method: " if "Incorrect" in result_header else "Installed solution logic: "
                sections.append(heading + guide)
        else:
            sections.append(
                "Paste the exact stored question and your complete answer. "
                "I will bind the review to its one-to-one installed solution before judging it."
            )
    elif request.intent == "summary":
        sections.append(topic.title)
        objectives = list(topic.learning_objectives[: request.requested_count])
        if objectives:
            sections.append("Key points:\n" + _numbered_lines(objectives))
        if topic.explanation:
            sections.append(topic.explanation)
    elif chapter_level:
        sections.append(f"{match.chapter.title} — Chapter overview")
        sections.append(
            "Main learning areas:\n"
            + _numbered_lines([item.title for item in match.chapter.topics])
        )
        normalized_message = _normalize_syllabus_lookup_text(message)
        if re.search(r"\bexamples?\b", normalized_message):
            chapter_examples: list[str] = []
            max_example_depth = max(
                (len(chapter_topic.examples) for chapter_topic in match.chapter.topics),
                default=0,
            )
            for example_index in range(max_example_depth):
                for chapter_topic in match.chapter.topics:
                    if example_index >= len(chapter_topic.examples):
                        continue
                    example = chapter_topic.examples[example_index]
                    chapter_examples.append(f"[{chapter_topic.title}] {example}")
                    if len(chapter_examples) >= request.requested_count:
                        break
                if len(chapter_examples) >= request.requested_count:
                    break
            if chapter_examples:
                sections.append("Examples:\n" + _numbered_lines(chapter_examples))
            if request.explicit_count and request.requested_count > len(chapter_examples):
                sections.append(
                    f"Only {len(chapter_examples)} validated example(s) are installed for this chapter."
                )
    else:
        sections.append(topic.title)
        if context.learning_mode == LearningMode.REVISION.value and topic.learning_objectives:
            sections.append("Key objectives: " + "; ".join(topic.learning_objectives[:3]))
        if topic.explanation:
            if teaching_guidance and teaching_guidance.get("step_size") in {"very_small", "small"}:
                sections.append("Key idea: " + topic.explanation)
            else:
                sections.append(topic.explanation)
        selected = list(topic.examples[: request.requested_count])
        if len(selected) == 1:
            sections.append("Example: " + selected[0])
        elif selected:
            sections.append("Examples:\n" + _numbered_lines(selected))
        if request.explicit_count and request.requested_count > len(selected):
            sections.append(
                f"Only {len(selected)} validated example(s) are installed for this topic."
            )

    if context.learning_mode == LearningMode.EXAM.value and topic.marks_pattern:
        sections.append("Marks pattern: " + topic.marks_pattern)

    sections.append(_source_description(match))

    return "\n\n".join(section for section in sections if section).strip()


SUBJECT_ALIASES = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "ganit": "Mathematics",
    "ગણિત": "Mathematics",
    "science": "Science",
    "science and technology": "Science & Technology",
    "science & technology": "Science & Technology",
    "vigyan": "Science",
    "વિજ્ઞાન": "Science",
    "english": "English",
    "social science": "Social Science",
    "social studies": "Social Science",
    "sst": "Social Science",
    "સામાજિક વિજ્ઞાન": "Social Science",
    "સામાજિકવિજ્ઞાન": "Social Science",
}


def detect_context_from_message(
    text: str,
    current: StudentLearningContext,
    syllabus_repository: SyllabusRepository | None = None,
) -> tuple[StudentLearningContext, dict[str, str]]:
    """Conservative context extraction; only updates fields found explicitly."""

    normalized = clean_student_text(text, max_length=2_000)
    lowered = normalized.casefold()
    changes: dict[str, Any] = {}
    detected: dict[str, str] = {}

    subject_matches: list[tuple[int, str, str]] = []
    for alias, canonical in SUBJECT_ALIASES.items():
        if re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", lowered):
            subject_matches.append((len(alias), alias, canonical))

    if subject_matches:
        _, _, canonical = max(subject_matches, key=lambda item: item[0])
        # "Science" is a common short form for the official subject title
        # "Science & Technology" in older GSEB semester books.  Prefer the
        # exact installed package for this learner, while preserving newer
        # packages whose canonical subject is simply "Science".
        if canonical == "Science" and syllabus_repository is not None:
            installed_science = syllabus_repository.find(
                board=current.board,
                medium=current.medium,
                standard=current.standard,
                subject="Science",
            )
            installed_science_technology = syllabus_repository.find(
                board=current.board,
                medium=current.medium,
                standard=current.standard,
                subject="Science & Technology",
            )
            if installed_science is None and installed_science_technology is not None:
                canonical = "Science & Technology"
        changes["current_subject"] = canonical
        detected["subject"] = canonical

    chapter_match = re.search(
        r"(?:chapter|chap|ch|unit|lesson|પાઠ|અધ્યાય)\s*(?:number|no\.?|નંબર)?\s*[:#-]?\s*([\w.-]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if chapter_match:
        chapter = f"Chapter {chapter_match.group(1)}"
        changes["current_chapter"] = chapter
        detected["chapter"] = chapter

    semester_chapter_reference = _semester_chapter_reference(normalized)

    standard_match = re.search(
        r"(?:std|standard|class|ધોરણ)\s*[:#-]?\s*(1[0-2]|[1-9])\b",
        lowered,
        flags=re.IGNORECASE,
    )
    if standard_match:
        changes["standard"] = int(standard_match.group(1))
        detected["standard"] = standard_match.group(1)

    for language in SUPPORTED_LANGUAGES:
        if language.casefold() in lowered:
            changes["preferred_language"] = language
            detected["language"] = language
            break

    # A phrase such as "Chapter 1 test" must resolve to the installed canonical
    # chapter title instead of replacing "Exploring Symbols" with the synthetic
    # label "Chapter 1".  If no installed match exists, preserve the saved chapter.
    if (chapter_match or semester_chapter_reference) and syllabus_repository is not None:
        provisional = replace(current, **changes)
        syllabus = syllabus_repository.find(
            board=provisional.board,
            medium=provisional.medium,
            standard=provisional.standard,
            subject=provisional.current_subject,
        )
        chapter_token = (
            semester_chapter_reference
            if semester_chapter_reference
            else chapter_match.group(1).strip().casefold()
        )
        chapter_token_normalized = _normalize_syllabus_lookup_text(chapter_token)
        canonical_chapter = next(
            (
                item.title
                for item in (syllabus.chapters if syllabus is not None else ())
                if chapter_token_normalized
                in {
                    _normalize_syllabus_lookup_text(item.number),
                    _normalize_syllabus_lookup_text(item.title),
                    _normalize_syllabus_lookup_text(f"chapter {item.number}"),
                }
            ),
            "",
        )
        if canonical_chapter:
            changes["current_chapter"] = canonical_chapter
            detected["chapter"] = canonical_chapter
            if canonical_chapter != current.current_chapter:
                changes["current_topic"] = ""
        else:
            changes.pop("current_chapter", None)
            detected.pop("chapter", None)

    # When the message explicitly names an installed topic, synchronize the
    # saved profile with that topic's canonical chapter.  Context-only fallback
    # matches are intentionally ignored so generic follow-ups cannot silently
    # switch chapters or revive stale topics.
    if syllabus_repository is not None:
        provisional = replace(current, **changes).validate()
        topic_match = syllabus_repository.lookup_topic(
            message=normalized,
            context=provisional,
        )
        if topic_match is not None and topic_match.matched_by in {
            "message-topic-specific",
            "message-topic-alias",
            "message-exercise-template",
            "message-practice-template",
        }:
            explicit_chapter = clean_student_text(
                changes.get("current_chapter"),
                max_length=200,
            )
            if not explicit_chapter or explicit_chapter == topic_match.chapter.title:
                changes["current_chapter"] = topic_match.chapter.title
                changes["current_topic"] = topic_match.topic.title
                detected["chapter"] = topic_match.chapter.title
                detected["topic"] = topic_match.topic.title

    if not changes:
        return current, detected
    return replace(current, **changes, updated_at=utc_now()).validate(), detected


def build_tutor_system_instruction(context: StudentLearningContext) -> str:
    mode_guidance = {
        LearningMode.EXPLAIN.value:
            "Explain clearly. Give one simple example only if it helps.",
        LearningMode.HOMEWORK.value:
            "Help solve the homework. If the student asks for the final answer, give it with a brief explanation.",
        LearningMode.REVISION.value:
            "Give a concise revision answer. Ask one revision question only if the student requests practice.",
        LearningMode.EXAM.value:
            "Write a board-exam style answer that is clear, well structured and concise.",
    }[context.learning_mode]

    return (
        "You are GyanVerse, an AI tutor for school students (Standards 1-10). "

        "Your highest priority is answering the student's actual question correctly. "

        "Do NOT invent conversation. "
        "Do NOT greet unless the student greeted first. "
        "Do NOT say 'Welcome back'. "
        "Do NOT mention previous sessions, memory, records, learning history, or assumed subjects. "
        "Do NOT say things like 'I noticed you were studying Mathematics'. "

        "Answer immediately. Do not write introductions or motivational paragraphs. "

        "Keep answers concise unless the student explicitly asks for a detailed explanation. "
        "Normally stay under about 200 words. "

        "Use simple school-level language. "
        "Avoid unnecessary markdown. "
        "Avoid LaTeX unless the student explicitly requests mathematical notation. "

        "Never ask 'Let's check your understanding' by default. "
        "Never generate quizzes or follow-up questions unless the student asks for practice, quiz, MCQs or test questions. "

        "If the student's question is ambiguous, ask one short clarification question instead of guessing. "

        f"Reply in {context.preferred_language} unless the student clearly uses another supported language. "

        f"Board: {context.board}; Medium: {context.medium}; Standard: {context.standard}. "

        f"Current learning mode: {context.learning_mode}. "
        f"{mode_guidance}"
    )


def _local_topic_answer(message: str) -> str:
    lowered = message.casefold()
    topics = (
        (
            ("photosynthesis", "food in plants"),
            "Photosynthesis is the process by which green plants use sunlight, chlorophyll, carbon dioxide and water to make glucose (food). Oxygen is released. In short: carbon dioxide + water --sunlight/chlorophyll--> glucose + oxygen. Check yourself: which gas does the plant take in?",
        ),
        (
            ("force",),
            "Force is a push or pull that can change an object's speed, direction or shape. Its SI unit is the newton (N). Example: pushing a door applies force. Check yourself: is friction also a force?",
        ),
        (
            ("pressure",),
            "Pressure means force acting on each unit of area: pressure = force / area. The same force creates more pressure on a smaller area. Its SI unit is pascal (Pa).",
        ),
        (
            ("heat", "temperature"),
            "Heat is energy transferred from a hotter object to a colder one, while temperature tells how hot or cold an object is. Heat is measured in joules; temperature is commonly measured in degrees Celsius or kelvin.",
        ),
        (
            ("photosynthesis",),
            "Photosynthesis is how green plants prepare food using sunlight, chlorophyll, carbon dioxide and water, releasing oxygen as a by-product.",
        ),
        (
            ("rational number", "rational numbers"),
            "A rational number can be written as p/q, where p and q are integers and q is not zero. Examples: 3/4, -2, and 0.5 are rational numbers.",
        ),
        (
            ("linear equation",),
            "A linear equation has a variable with highest power 1, such as 2x + 3 = 11. Keep both sides balanced: subtract 3 from both sides, then divide by 2, so x = 4.",
        ),
        (
            ("fraction", "fractions"),
            "A fraction represents parts of a whole. The top number is the numerator and the bottom number is the denominator. To add unlike fractions, first make their denominators equal.",
        ),
        (
            ("active voice", "passive voice"),
            "In active voice the subject performs the action: 'Riya writes a letter.' In passive voice the receiver comes first: 'A letter is written by Riya.'",
        ),
        (
            ("noun",),
            "A noun names a person, place, animal, thing or idea. Examples: teacher, Ahmedabad, tiger, book and honesty.",
        ),
        (
            ("verb",),
            "A verb shows an action, occurrence or state. Examples: run, write, become and is.",
        ),
    )
    for keywords, answer in topics:
        if any(keyword in lowered for keyword in keywords):
            return answer
    return ""


def _local_arithmetic_answer(message: str) -> str:
    match = re.fullmatch(
        r"(?:what\s+is|calculate|solve)?\s*(-?\d+(?:\.\d+)?)\s*([+\-*/x×÷])\s*(-?\d+(?:\.\d+)?)\s*\??",
        message.strip(),
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    left = float(match.group(1))
    operator = match.group(2)
    right = float(match.group(3))
    if operator == "+":
        result = left + right
    elif operator == "-":
        result = left - right
    elif operator in {"*", "x", "×"}:
        result = left * right
    else:
        if right == 0:
            return "Division by zero is not defined."
        result = left / right
    formatted = str(int(result)) if result.is_integer() else f"{result:.6g}"
    return f"{match.group(1)} {operator} {match.group(3)} = {formatted}."


def offline_tutor_response(
    message: str,
    context: StudentLearningContext,
    attachments: Sequence[AttachmentRecord] = (),
    provider_failed: bool = False,
) -> str:
    """Question-aware deterministic tutor used when online AI is unavailable."""

    cleaned = clean_student_text(message)
    if not cleaned and not attachments:
        return "Please type a question or attach a homework page."

    attachment_note = ""
    if attachments:
        attachment_note = (
            f"\n\nI received {len(attachments)} homework file(s). Their text/image content needs the online AI service, "
            "but the files remain saved locally and can be removed from Homework History."
        )

    arithmetic_answer = _local_arithmetic_answer(cleaned)
    if arithmetic_answer:
        return arithmetic_answer + attachment_note

    topic_answer = _local_topic_answer(cleaned)
    if topic_answer:
        return topic_answer + attachment_note

    if provider_failed:
        return "The online tutor could not respond right now. Your question is saved. Please tap Retry." + attachment_note

    chapter = context.current_chapter or "the current chapter"
    subject = context.current_subject or "the current subject"
    quoted_question = cleaned or "the attached homework"

    if context.learning_mode == LearningMode.HOMEWORK.value:
        return (
            f'Your homework question is: “{quoted_question}”\n\n'
            f"For {subject}, {chapter}, first show the step you already tried. I will check that exact step, "
            "point out the first mistake and give one hint before the final answer."
            + attachment_note
        )
    if context.learning_mode == LearningMode.REVISION.value:
        return (
            f'You want to revise: “{quoted_question}”\n\n'
            f"Write one definition, one rule and one example you remember from {subject}, {chapter}. "
            "I will compare them and ask a focused recall question."
            + attachment_note
        )
    if context.learning_mode == LearningMode.EXAM.value:
        return (
            f'Exam question received: “{quoted_question}”\n\n'
            "Add the marks or expected answer length. I will organize it as definition/key idea, working or evidence, "
            "and a concise final statement."
            + attachment_note
        )
    return (
        f'You asked: “{quoted_question}”\n\n'
        f"I am using the local tutor for this reply. For {subject}, {chapter}, tell me which word, rule or step is confusing, "
        "or paste the related textbook line. I will explain that exact part instead of giving a generic answer."
        + attachment_note
    )

def attachment_prompt(records: Sequence[AttachmentRecord]) -> str:
    if not records:
        return ""
    lines = ["Attached homework files:"]
    for item in records:
        lines.append(f"- {item.original_name} ({item.mime_type}, {item.display_size})")
    lines.append(
        "Read the visible question and the student's attempt. Identify subject/chapter only when evidence is clear. "
        "Highlight mistakes respectfully and give hints before the final answer."
    )
    return "\n".join(lines)


def format_tutor_response(
    text: str,
    *,
    student_message: str = "",
) -> str:
    """
    Post-processes tutor responses without changing their meaning.
    Safe for both Gemini and Offline tutor.
    """
    if not text:
        return ""

    text = str(text or "")[:20000]
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    greeted = bool(
        re.match(
            r"^\s*(hi|hello|hey|namaste|good morning|good afternoon|good evening)\b",
            student_message,
            flags=re.IGNORECASE,
        )
    )

    if not greeted:
        text = re.sub(
            r"^(hello|hi|hey|certainly|sure|absolutely|of course)[,!\.\s]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    text = re.sub(
        r"\b(As an AI language model|As an AI|I'm an AI|I am an AI)\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = text.replace("**", "")
    text = re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"\1", text)
    text = text.replace("```", "")

    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


INSTANT_INTENT_GREETING = "greeting"
INSTANT_INTENT_THANKS = "thanks"
INSTANT_INTENT_BYE = "bye"
INSTANT_INTENT_HELP = "help"

ACADEMIC_KEYWORDS = {
    "explain", "what", "why", "how", "solve", "calculate", "chapter", "math",
    "science", "formula", "question", "problem", "mean", "define", "derivative",
    "equation", "photosynthesis", "fraction", "decimal", "geometry", "algebra",
    "physics", "chemistry", "biology", "history", "geography", "grammar",
    "translate", "summarize", "evaluate", "find", "derive", "proof", "example"
}


def classify_instant_intent(text: str) -> str | None:
    raw = clean_student_text(text, max_length=200).lower()
    if not raw:
        return None

    words = re.findall(r"\b[a-z0-9]+\b", raw)
    if not words or len(words) > 6:
        return None

    if any(w in ACADEMIC_KEYWORDS for w in words):
        return None

    clean = " ".join(words)

    if re.fullmatch(
        r"(hello|hi|hey|namaste|good morning|good afternoon|good evening|kem cho|su prabhat|namaskar)( (there|ji|tutor|buddy|friend|bhai|sir|maam))?",
        clean,
    ):
        return INSTANT_INTENT_GREETING

    if re.fullmatch(
        r"(thanks|thank you|thanku|dhanyawad|aabhar|thx)( (very much|so much|a lot|ji|tutor))?",
        clean,
    ):
        return INSTANT_INTENT_THANKS

    if re.fullmatch(
        r"(bye|goodbye|alvida|aavjo|see you)( (tutor|buddy|later))?",
        clean,
    ):
        return INSTANT_INTENT_BYE

    if re.fullmatch(r"(help|commands|study tools|options)", clean):
        return INSTANT_INTENT_HELP

    return None


def instant_tutor_response(intent: str, context: StudentLearningContext) -> str:
    lang = (context.preferred_language or context.medium or "English").strip().lower()

    if intent == INSTANT_INTENT_HELP:
        return (
            "Available study tools:\n"
            "• Ask doubts directly in Explain, Homework, Revision or Exam mode\n"
            "• Attach homework photos or PDFs for hint-first review\n"
            "• Record voice questions in Gujarati, Hindi or English\n"
            "• Daily Sync: save what school taught today"
        )

    if "gujarati" in lang:
        if intent == INSTANT_INTENT_GREETING:
            return f"નમસ્તે {context.name}! હું તમારો જ્ઞાનવર્સ ટ્યુટર છું. આજે Std {context.standard} {context.current_subject or 'અભ્યાસ'}માં શું મદદ કરું?"
        if intent == INSTANT_INTENT_THANKS:
            return "તમારો ખૂબ આભાર! સરસ રીતે ભણતા રહો."
        if intent == INSTANT_INTENT_BYE:
            return "આવજો! સરસ અભ્યાસ કરો અને ફરી મળીશું."

    elif "hindi" in lang:
        if intent == INSTANT_INTENT_GREETING:
            return f"नमस्ते {context.name}! मैं आपका ज्ञानवर्स ट्यूटर हूँ। आज कक्षा {context.standard} के {context.current_subject or 'पढ़ाई'} में क्या समझना चाहते हैं?"
        if intent == INSTANT_INTENT_THANKS:
            return "आपका स्वागत है! मन लगाकर पढ़ते रहिए।"
        if intent == INSTANT_INTENT_BYE:
            return "अलविदा! अच्छे से पढ़ाई करें, फिर मिलेंगे।"

    elif "hinglish" in lang:
        if intent == INSTANT_INTENT_GREETING:
            return f"Namaste {context.name}! Main aapka GyanVerse tutor hoon. Aaj Std {context.standard} {context.current_subject or 'subject'} mein kya padhenge?"
        if intent == INSTANT_INTENT_THANKS:
            return "Welcome! Aise hi mehnat se padhte rahiye."
        if intent == INSTANT_INTENT_BYE:
            return "Bye! Acche se padhai karna, phir milenge."

    if intent == INSTANT_INTENT_GREETING:
        return f"Hello {context.name}! I am your GyanVerse tutor. What would you like to study in Class {context.standard} {context.current_subject or 'today'}?"
    if intent == INSTANT_INTENT_THANKS:
        return "You are very welcome! Keep up the great learning."
    if intent == INSTANT_INTENT_BYE:
        return "Goodbye! Have a productive study session."

    return f"Hello {context.name}! How can I help you with your studies today?"


ABBREVIATIONS = (
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "e.g.", "i.e.",
    "vs.", "etc.", "std.", "no.", "st.", "fig.", "approx.", "rs.", "vol."
)


def split_into_sentences(text: str) -> list[str]:
    """
    Deterministic sentence segmenter supporting English, Hindi, and Gujarati.
    Preserves decimal numbers, abbreviations, numbered steps, and bullet points.
    Discards empty/whitespace segments.
    """
    if not text or not str(text).strip():
        return []

    raw = str(text).strip()

    PH_DECIMAL = "\uF000"
    PH_ABBR = "\uF001"
    PH_LIST = "\uF002"

    # Step 1: Protect decimal numbers (e.g. 3.14, 0.5)
    protected = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + PH_DECIMAL + m.group(2), raw)

    # Step 2: Protect common abbreviations
    for abbr in ABBREVIATIONS:
        pattern = re.compile(re.escape(abbr), re.IGNORECASE)
        replacement = abbr[:-1] + PH_ABBR
        protected = pattern.sub(replacement, protected)

    # Step 3: Insert boundary marker before step prefixes if preceded by whitespace
    protected = re.sub(r"(?<=\s)(step\s+\d+[\.:]?|\d+[\.:])", r"\n\1", protected, flags=re.IGNORECASE)

    # Step 4: Protect numbered list prefixes at line starts (e.g. "1. ", "2. ")
    protected = re.sub(r"(^|\n)(\s*\d+)\.\s+", lambda m: m.group(1) + m.group(2) + PH_LIST + " ", protected)

    # Step 4: Split by sentence boundaries (. ! ? । ॥) or newlines
    raw_segments = re.split(r"(?<=[.!?।॥])\s+|\n+", protected)

    results: list[str] = []
    for seg in raw_segments:
        cleaned_seg = seg.replace(PH_DECIMAL, ".").replace(PH_ABBR, ".").replace(PH_LIST, ". ").strip()
        if cleaned_seg:
            results.append(cleaned_seg)

    merged_results: list[str] = []
    i = 0
    while i < len(results):
        seg = results[i]
        if i + 1 < len(results) and re.fullmatch(r"(step\s+\d+[\.:]?|phase\s+\d+[\.:]?|\d+[\.:])", seg, flags=re.IGNORECASE):
            merged_results.append(f"{seg} {results[i+1]}")
            i += 2
        else:
            merged_results.append(seg)
            i += 1

    return merged_results
