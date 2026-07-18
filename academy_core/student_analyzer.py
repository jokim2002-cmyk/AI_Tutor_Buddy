from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class ConfidenceLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


class UnderstandingState(str, Enum):
    CONFUSED = "confused"
    GUESSING = "guessing"
    DEVELOPING = "developing"
    UNDERSTOOD = "understood"
    UNKNOWN = "unknown"


class RevisionNeed(str, Enum):
    NONE = "none"
    SOON = "soon"
    URGENT = "urgent"


@dataclass(frozen=True)
class LearningEvidence:
    source: str
    signal: str
    weight: float
    detail: str = ""

    def validate(self) -> None:
        if not self.source.strip():
            raise ValueError("evidence source is required")
        if not self.signal.strip():
            raise ValueError("evidence signal is required")
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("evidence weight must be between 0 and 1")


@dataclass(frozen=True)
class StudentContext:
    student_id: str = "default"
    class_level: Optional[int] = None
    preferred_language: str = "auto"
    subject: str = ""
    topic: str = ""
    recent_accuracy: Optional[float] = None
    attempts_on_topic: int = 0
    hints_used: int = 0
    repeated_mistakes: int = 0
    days_since_last_practice: Optional[int] = None
    prior_mastery: Optional[float] = None
    helpful_methods: Tuple[str, ...] = ()
    recent_messages: Tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.student_id.strip():
            raise ValueError("student_id is required")
        if self.class_level is not None and not 1 <= self.class_level <= 12:
            raise ValueError("class_level must be between 1 and 12")
        for name, value in (
            ("recent_accuracy", self.recent_accuracy),
            ("prior_mastery", self.prior_mastery),
        ):
            if value is not None and not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        for name, value in (
            ("attempts_on_topic", self.attempts_on_topic),
            ("hints_used", self.hints_used),
            ("repeated_mistakes", self.repeated_mistakes),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.days_since_last_practice is not None and self.days_since_last_practice < 0:
            raise ValueError("days_since_last_practice cannot be negative")


@dataclass(frozen=True)
class StudentAnalysis:
    student_id: str
    class_level: Optional[int]
    preferred_language: str
    subject: str
    topic: str
    confidence: ConfidenceLevel
    understanding: UnderstandingState
    revision_need: RevisionNeed
    recommended_teacher_subject: str
    recommended_methods: Tuple[str, ...]
    needs_prerequisite_check: bool
    should_ask_clarifying_question: bool
    evidence: Tuple[LearningEvidence, ...] = field(default_factory=tuple)
    safe_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["confidence"] = self.confidence.value
        data["understanding"] = self.understanding.value
        data["revision_need"] = self.revision_need.value
        data["evidence"] = [asdict(item) for item in self.evidence]
        return data


SUBJECT_PATTERNS: Mapping[str, Tuple[str, ...]] = {
    "maths": (
        "math", "maths", "mathematics", "ganit", "fraction", "decimal",
        "percentage", "ratio", "algebra", "geometry", "equation",
    ),
    "science": (
        "science", "physics", "chemistry", "biology", "experiment",
        "force", "atom", "plant", "cell", "electricity",
    ),
    "english": (
        "english", "grammar", "pronunciation", "essay", "sentence",
        "reading", "vocabulary", "tense",
    ),
    "hindi": (
        "hindi", "vyakaran", "kavita", "nibandh", "sangya", "sarvanam",
    ),
    "computer": (
        "computer", "coding", "python", "programming", "software",
        "algorithm", "debug", "flowchart",
    ),
    "social_science": (
        "history", "geography", "civics", "social science", "sst",
        "constitution", "map", "civilization",
    ),
}

CONFUSION_PHRASES = (
    "samajh nahi", "samaj nahi", "confused", "i don't understand",
    "i do not understand", "not clear", "dobara samjhao", "again explain",
    "mujhe nahi aata", "mujhe nahi samajh",
)
GUESSING_PHRASES = (
    "shayad", "maybe", "i think", "guess", "andaza", "probably",
)
LOW_CONFIDENCE_PHRASES = (
    "dar lag", "i am scared", "i'm scared", "mujhse nahi hoga",
    "i can't", "i cannot", "bahut difficult", "too difficult",
    "main weak hoon", "fail ho jaunga", "fail ho jaungi",
)
HIGH_CONFIDENCE_PHRASES = (
    "samajh gaya", "samajh gayi", "i understand", "got it",
    "easy hai", "i can solve", "clear hai",
)


class StudentAnalyzer:
    """Produces evidence-based, non-diagnostic student learning context."""

    def analyze(
        self,
        context: StudentContext,
        *,
        current_message: str = "",
    ) -> StudentAnalysis:
        context.validate()
        text = self._normalize(" ".join((*context.recent_messages, current_message)))
        subject = self._infer_subject(context.subject, context.topic, text)
        topic = context.topic.strip()
        evidence: List[LearningEvidence] = []

        confidence = self._infer_confidence(context, text, evidence)
        understanding = self._infer_understanding(context, text, evidence)
        revision_need = self._infer_revision_need(context, evidence)

        needs_prerequisite_check = (
            context.repeated_mistakes >= 2
            or understanding == UnderstandingState.CONFUSED
            or (context.prior_mastery is not None and context.prior_mastery < 0.45)
        )
        if needs_prerequisite_check:
            evidence.append(LearningEvidence(
                source="student_analyzer",
                signal="prerequisite_check_recommended",
                weight=0.75,
                detail="Repeated difficulty or low prior mastery suggests checking foundations.",
            ))

        should_ask_clarifying_question = not subject or (
            not topic and understanding == UnderstandingState.UNKNOWN
        )

        methods = self._recommend_methods(
            context=context,
            confidence=confidence,
            understanding=understanding,
        )

        for item in evidence:
            item.validate()

        summary = self._build_safe_summary(
            confidence=confidence,
            understanding=understanding,
            revision_need=revision_need,
            subject=subject,
            topic=topic,
        )

        return StudentAnalysis(
            student_id=context.student_id,
            class_level=context.class_level,
            preferred_language=context.preferred_language or "auto",
            subject=subject,
            topic=topic,
            confidence=confidence,
            understanding=understanding,
            revision_need=revision_need,
            recommended_teacher_subject=subject or "class_guidance",
            recommended_methods=methods,
            needs_prerequisite_check=needs_prerequisite_check,
            should_ask_clarifying_question=should_ask_clarifying_question,
            evidence=tuple(evidence),
            safe_summary=summary,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        value = value.lower()
        value = re.sub(r"[^a-z0-9\u0900-\u097f\u0A80-\u0AFF' ]+", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def _infer_subject(self, explicit_subject: str, topic: str, text: str) -> str:
        combined = self._normalize(f"{explicit_subject} {topic} {text}")
        for subject, keywords in SUBJECT_PATTERNS.items():
            if any(keyword in combined for keyword in keywords):
                return subject
        return self._normalize(explicit_subject).replace(" ", "_")

    def _infer_confidence(
        self,
        context: StudentContext,
        text: str,
        evidence: List[LearningEvidence],
    ) -> ConfidenceLevel:
        if any(phrase in text for phrase in LOW_CONFIDENCE_PHRASES):
            evidence.append(LearningEvidence(
                source="message",
                signal="low_confidence_language",
                weight=0.9,
                detail="Student message includes low-confidence wording.",
            ))
            return ConfidenceLevel.LOW

        if any(phrase in text for phrase in HIGH_CONFIDENCE_PHRASES):
            evidence.append(LearningEvidence(
                source="message",
                signal="high_confidence_language",
                weight=0.8,
                detail="Student reports understanding or readiness.",
            ))
            return ConfidenceLevel.HIGH

        if context.recent_accuracy is not None:
            if context.recent_accuracy < 0.45 or context.hints_used >= 3:
                evidence.append(LearningEvidence(
                    source="performance",
                    signal="confidence_support_needed",
                    weight=0.7,
                    detail="Recent accuracy or repeated hint use suggests gentle support.",
                ))
                return ConfidenceLevel.LOW
            if context.recent_accuracy >= 0.8 and context.hints_used == 0:
                evidence.append(LearningEvidence(
                    source="performance",
                    signal="independent_success",
                    weight=0.75,
                    detail="Recent independent accuracy is high.",
                ))
                return ConfidenceLevel.HIGH
            return ConfidenceLevel.MEDIUM

        return ConfidenceLevel.UNKNOWN

    def _infer_understanding(
        self,
        context: StudentContext,
        text: str,
        evidence: List[LearningEvidence],
    ) -> UnderstandingState:
        if any(phrase in text for phrase in CONFUSION_PHRASES):
            evidence.append(LearningEvidence(
                source="message",
                signal="explicit_confusion",
                weight=0.95,
                detail="Student explicitly reports confusion.",
            ))
            return UnderstandingState.CONFUSED

        if any(phrase in text for phrase in GUESSING_PHRASES):
            evidence.append(LearningEvidence(
                source="message",
                signal="possible_guessing",
                weight=0.75,
                detail="Student language suggests uncertainty or guessing.",
            ))
            return UnderstandingState.GUESSING

        if any(phrase in text for phrase in HIGH_CONFIDENCE_PHRASES):
            return UnderstandingState.UNDERSTOOD

        if context.repeated_mistakes >= 2:
            evidence.append(LearningEvidence(
                source="performance",
                signal="repeated_misconception",
                weight=0.85,
                detail="Same or related mistake appears repeatedly.",
            ))
            return UnderstandingState.CONFUSED

        if context.recent_accuracy is not None:
            if context.recent_accuracy >= 0.8:
                return UnderstandingState.UNDERSTOOD
            if context.recent_accuracy >= 0.5:
                return UnderstandingState.DEVELOPING
            return UnderstandingState.CONFUSED

        return UnderstandingState.UNKNOWN

    def _infer_revision_need(
        self,
        context: StudentContext,
        evidence: List[LearningEvidence],
    ) -> RevisionNeed:
        urgent = (
            context.repeated_mistakes >= 3
            or (context.prior_mastery is not None and context.prior_mastery < 0.35)
            or (
                context.days_since_last_practice is not None
                and context.days_since_last_practice >= 21
            )
        )
        if urgent:
            evidence.append(LearningEvidence(
                source="memory",
                signal="urgent_revision",
                weight=0.9,
                detail="Mastery, repeated mistakes, or long practice gap requires revision.",
            ))
            return RevisionNeed.URGENT

        soon = (
            context.repeated_mistakes >= 1
            or (context.prior_mastery is not None and context.prior_mastery < 0.7)
            or (
                context.days_since_last_practice is not None
                and context.days_since_last_practice >= 7
            )
        )
        if soon:
            evidence.append(LearningEvidence(
                source="memory",
                signal="revision_due_soon",
                weight=0.7,
                detail="Topic should be reinforced soon.",
            ))
            return RevisionNeed.SOON

        return RevisionNeed.NONE

    def _recommend_methods(
        self,
        *,
        context: StudentContext,
        confidence: ConfidenceLevel,
        understanding: UnderstandingState,
    ) -> Tuple[str, ...]:
        methods: List[str] = list(context.helpful_methods)

        if understanding == UnderstandingState.CONFUSED:
            methods.extend(("prerequisite_check", "worked_example", "understanding_check"))
        elif understanding == UnderstandingState.GUESSING:
            methods.extend(("explain_reasoning", "confidence_check", "guided_practice"))
        elif understanding == UnderstandingState.DEVELOPING:
            methods.extend(("guided_practice", "retrieval_question"))
        elif understanding == UnderstandingState.UNDERSTOOD:
            methods.extend(("independent_practice", "transfer_question"))
        else:
            methods.extend(("clarifying_question", "simple_example"))

        if confidence == ConfidenceLevel.LOW:
            methods.insert(0, "gentle_encouragement")
        if context.hints_used >= 2:
            methods.append("smaller_steps")

        return tuple(dict.fromkeys(methods))

    @staticmethod
    def _build_safe_summary(
        *,
        confidence: ConfidenceLevel,
        understanding: UnderstandingState,
        revision_need: RevisionNeed,
        subject: str,
        topic: str,
    ) -> str:
        target = topic or subject or "current learning task"
        return (
            f"For {target}, current evidence suggests confidence={confidence.value}, "
            f"understanding={understanding.value}, revision={revision_need.value}. "
            "These are temporary learning signals, not permanent labels."
        )
