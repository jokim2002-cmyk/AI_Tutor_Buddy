from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
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


SUPPORTED_BOARDS = ("GSEB", "CBSE", "ICSE", "Other")
SUPPORTED_MEDIUMS = ("Gujarati", "English", "Hindi")
SUPPORTED_LANGUAGES = ("Gujarati", "Hindi", "English")
SUPPORTED_STANDARDS = tuple(range(1, 13))
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
        board = clean_student_text(self.board, max_length=40) or "GSEB"
        medium = clean_student_text(self.medium, max_length=40) or "Gujarati"
        language = clean_student_text(self.preferred_language, max_length=40) or medium
        subject = clean_student_text(self.current_subject, max_length=100)
        chapter = clean_student_text(self.current_chapter, max_length=180)
        topic = clean_student_text(self.current_topic, max_length=300)
        try:
            standard = int(self.standard)
        except (TypeError, ValueError) as exc:
            raise Phase11Error("Standard must be a number from 1 to 12.") from exc
        if standard not in SUPPORTED_STANDARDS:
            raise Phase11Error("Standard must be between 1 and 12.")
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
    learning_objectives: tuple[str, ...] = ()
    explanation: str = ""
    examples: tuple[str, ...] = ()
    exercises: tuple[str, ...] = ()
    solutions: tuple[str, ...] = ()
    practice_questions: tuple[str, ...] = ()
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
            learning_objectives=values("learning_objectives"),
            explanation=clean_student_text(payload.get("explanation"), max_length=10_000),
            examples=values("examples"),
            exercises=values("exercises"),
            solutions=values("solutions"),
            practice_questions=values("practice_questions"),
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
class GSEBSyllabus:
    schema_version: int
    board: str
    medium: str
    standard: int
    subject: str
    textbook: str
    source: SyllabusSource
    chapters: tuple[SyllabusChapter, ...]

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GSEBSyllabus":
        if clean_student_text(payload.get("board"), max_length=20).upper() != "GSEB":
            raise Phase11Error("This importer accepts only GSEB syllabus documents.")
        try:
            standard = int(payload.get("standard"))
        except (TypeError, ValueError) as exc:
            raise Phase11Error("Syllabus standard must be a number from 1 to 12.") from exc
        if standard not in SUPPORTED_STANDARDS:
            raise Phase11Error("Syllabus standard must be between 1 and 12.")
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
            board="GSEB",
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

    @property
    def key(self) -> str:
        return f"gseb-{self.medium.lower()}-{self.standard}-{safe_filename(self.subject).lower()}"

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
            "chapters": len(self.chapters),
            "topics": total,
            "content_topics": len(content_topics),
            "official_topics": len(official_topics),
            "coverage_percent": round((len(content_topics) / total) * 100, 2) if total else 0.0,
            "official_coverage_percent": round((len(official_topics) / total) * 100, 2)
            if total
            else 0.0,
        }


class GSEBSyllabusRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def import_json(self, path: str | Path) -> GSEBSyllabus:
        source_path = Path(path)
        try:
            payload = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise Phase11Error(f"Unable to read syllabus JSON: {exc}") from exc
        syllabus = GSEBSyllabus.from_dict(payload)
        target = self.root / f"{syllabus.key}.json"
        target.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return syllabus

    def install_payload(self, payload: Mapping[str, Any]) -> GSEBSyllabus:
        syllabus = GSEBSyllabus.from_dict(payload)
        target = self.root / f"{syllabus.key}.json"
        target.write_text(
            json.dumps(dict(payload), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return syllabus

    def all(self) -> list[GSEBSyllabus]:
        results: list[GSEBSyllabus] = []
        for path in sorted(self.root.glob("gseb-*.json")):
            try:
                results.append(GSEBSyllabus.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, Phase11Error):
                continue
        return results

    def find(
        self, *, medium: str, standard: int, subject: str
    ) -> GSEBSyllabus | None:
        needle = (medium.casefold(), int(standard), subject.casefold())
        for syllabus in self.all():
            if (
                syllabus.medium.casefold(),
                syllabus.standard,
                syllabus.subject.casefold(),
            ) == needle:
                return syllabus
        return None

    def overall_coverage(self) -> dict[str, Any]:
        syllabi = self.all()
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


SUBJECT_ALIASES = {
    "math": "Mathematics",
    "maths": "Mathematics",
    "mathematics": "Mathematics",
    "ganit": "Mathematics",
    "ગણિત": "Mathematics",
    "science": "Science",
    "vigyan": "Science",
    "વિજ્ઞાન": "Science",
    "english": "English",
    "gujarati": "Gujarati",
    "ગુજરાતી": "Gujarati",
    "hindi": "Hindi",
    "social science": "Social Science",
}


def detect_context_from_message(
    text: str, current: StudentLearningContext
) -> tuple[StudentLearningContext, dict[str, str]]:
    """Conservative context extraction; only updates fields found explicitly."""

    normalized = clean_student_text(text, max_length=2_000)
    lowered = normalized.casefold()
    changes: dict[str, Any] = {}
    detected: dict[str, str] = {}

    for alias, canonical in SUBJECT_ALIASES.items():
        if re.search(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", lowered):
            changes["current_subject"] = canonical
            detected["subject"] = canonical
            break

    chapter_match = re.search(
        r"(?:chapter|chap|ch|પાઠ|અધ્યાય)\s*(?:number|no\.?|નંબર)?\s*[:#-]?\s*([\w.-]+)",
        normalized,
        flags=re.IGNORECASE,
    )
    if chapter_match:
        chapter = f"Chapter {chapter_match.group(1)}"
        changes["current_chapter"] = chapter
        detected["chapter"] = chapter

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
    text = text.replace("__", "")
    text = text.replace("```", "")

    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
