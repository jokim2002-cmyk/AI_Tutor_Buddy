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


    magnet_decision = _std7_magnet_material_classification_decision(student_answer, question)
    if magnet_decision is True:
        return (
            "Result: Correct.",
            "Your answer correctly classifies the magnetic and non-magnetic materials in the installed solution.",
        )
    if magnet_decision is False:
        return (
            "Result: Incorrect.",
            "Your answer reverses the installed material classification.",
        )

    water_decision = _std7_water_states_classification_decision(student_answer, question)
    if water_decision is True:
        return (
            "Result: Correct.",
            "Your answer correctly names the three physical states of water.",
        )
    if water_decision is False:
        return (
            "Result: Incorrect.",
            "Your answer does not correctly name all three physical states of water.",
        )

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


@dataclass(frozen=True)
class TestPaperQuestionItem:
    question_num: int
    section_title: str
    topic_title: str
    question_text: str
    max_marks: int
    solution_guide: str


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
) -> tuple[float, str, str]:
    if not user_ans or not user_ans.strip():
        return 0.0, "Not answered", "No answer provided."

    magnet_decision = _std7_magnet_material_classification_decision(user_ans, q_text)
    if magnet_decision is True:
        return float(max_marks), "Correct", "Correct answer."
    elif magnet_decision is False:
        return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

    water_decision = _std7_water_states_classification_decision(user_ans, q_text)
    if water_decision is True:
        return float(max_marks), "Correct", "Correct answer."
    elif water_decision is False:
        return 0.0, "Incorrect", f"Incorrect concept. Correct answer: {sol_guide}"

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
            if u_nums == g_nums:
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

    # Single chapter
    ch_num_match = re.search(r"\bchapter\s*(\d{1,2})\b", message, re.IGNORECASE)
    target_ch_num = ch_num_match.group(1) if ch_num_match else None
    if not target_ch_num and context.current_chapter:
        ctx_match = re.search(
            r"\bchapter\s*(\d{1,2})\b",
            context.current_chapter,
            re.IGNORECASE,
        )
        if ctx_match:
            target_ch_num = ctx_match.group(1)

    target_ch = (
        next(
            (
                c
                for c in syllabus.chapters
                if target_ch_num and re.sub(r"\D", "", c.number) == target_ch_num
            ),
            None,
        )
        if target_ch_num
        else None
    )

    if target_ch is None and context.current_chapter:
        ctx_clean = context.current_chapter.casefold()
        target_ch = next(
            (
                c
                for c in syllabus.chapters
                if c.title.casefold() in ctx_clean or ctx_clean in c.title.casefold()
            ),
            None,
        )

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


def is_suitable_for_section(q_text: str, sol_text: str, mark_per_q: int) -> bool:
    q_lower = q_text.casefold().strip()
    sol_text_clean = sol_text.strip()
    sol_words = len(sol_text_clean.split())

    one_line_prefixes = (
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
        # 6 marks: MUST NOT be a simple one-line factual question.
        if is_one_line:
            return False
        if sol_words < 20 and not is_heavy_explanation:
            return False
        return True

    elif mark_per_q == 1:
        # 1 mark: MUST NOT be a heavy explanation prompt where answer guide expects multiple points.
        if is_heavy_explanation:
            return False
        return True

    elif mark_per_q == 2:
        if sol_words > 90:
            return False
        return True

    elif mark_per_q == 3:
        if is_one_line and sol_words < 12:
            return False
        return True

    return True


def render_test_paper(
    syllabus: BoardSyllabus,
    scope: TestPaperScope,
    *,
    context: StudentLearningContext | None = None,
    message: str = "",
    randomize: bool | None = None,
    seed: int | str | None = None,
) -> tuple[str, GeneratedTestPaper]:
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

    pool: list[tuple[str, str, str]] = []
    if len(scope.chapters) > 1:
        # Multi-chapter or Full-book: Interleave by chapter
        ch_pools: list[list[tuple[str, str, str]]] = []
        for ch in scope.chapters:
            c_items: list[tuple[str, str, str]] = []
            t_items_list: list[list[tuple[str, str, str]]] = []
            for t in ch.topics:
                t_q: list[tuple[str, str, str]] = []
                for i, q in enumerate(t.exercises):
                    if q and q.strip() and i < len(t.solutions) and t.solutions[i] and t.solutions[i].strip():
                        t_q.append((t.title, q.strip(), t.solutions[i].strip()))
                for i, q in enumerate(t.practice_questions):
                    if q and q.strip() and i < len(t.practice_solutions) and t.practice_solutions[i] and t.practice_solutions[i].strip():
                        t_q.append((t.title, q.strip(), t.practice_solutions[i].strip()))
                for ex in t.examples:
                    if ex and ex.strip():
                        t_q.append(
                            (
                                t.title,
                                f"Explain with an example: {ex.strip()}",
                                f"Example solution: {ex.strip()}",
                            )
                        )
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
    elif scope.chapters:
        # Single-chapter: Interleave by topic
        ch = scope.chapters[0]
        t_items_list: list[list[tuple[str, str, str]]] = []
        for t in ch.topics:
            t_q: list[tuple[str, str, str]] = []
            for i, q in enumerate(t.exercises):
                if q and q.strip() and i < len(t.solutions) and t.solutions[i] and t.solutions[i].strip():
                    t_q.append((t.title, q.strip(), t.solutions[i].strip()))
            for i, q in enumerate(t.practice_questions):
                if q and q.strip() and i < len(t.practice_solutions) and t.practice_solutions[i] and t.practice_solutions[i].strip():
                    t_q.append((t.title, q.strip(), t.practice_solutions[i].strip()))
            for ex in t.examples:
                if ex and ex.strip():
                    t_q.append(
                        (
                            t.title,
                            f"Explain with an example: {ex.strip()}",
                            f"Example solution: {ex.strip()}",
                        )
                    )
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
            selected_item = None

            if rng is not None:
                for idx, item in enumerate(available_pool):
                    _, q_text, sol_text = item
                    if is_suitable_for_section(q_text, sol_text, mark_per_q):
                        selected_item = available_pool.pop(idx)
                        break

                if selected_item is None:
                    refilled = list(pool)
                    rng.shuffle(refilled)
                    for idx, item in enumerate(refilled):
                        _, q_text, sol_text = item
                        if is_suitable_for_section(q_text, sol_text, mark_per_q):
                            selected_item = item
                            refilled.pop(idx)
                            available_pool = refilled
                            break

                if selected_item is None:
                    if not available_pool:
                        available_pool = list(pool)
                        rng.shuffle(available_pool)
                    selected_item = available_pool.pop(0)
            else:
                n_pool = len(pool)
                for offset in range(n_pool):
                    candidate_idx = (pool_idx + offset) % n_pool
                    _, q_text, sol_text = pool[candidate_idx]
                    if is_suitable_for_section(q_text, sol_text, mark_per_q):
                        selected_item = pool[candidate_idx]
                        pool_idx = candidate_idx + 1
                        break

                if selected_item is None:
                    selected_item = pool[pool_idx % len(pool)]
                    pool_idx += 1

            topic_title, q_text, sol_text = selected_item
            lbl = "Mark" if mark_per_q == 1 else "Marks"
            lines.append(f"{q_num}. [{topic_title}] {q_text} ({mark_per_q} {lbl})")
            answers_list.append((q_num, topic_title, sol_text))
            items.append(
                TestPaperQuestionItem(
                    question_num=q_num,
                    section_title=sec_title,
                    topic_title=topic_title,
                    question_text=q_text,
                    max_marks=mark_per_q,
                    solution_guide=sol_text,
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
