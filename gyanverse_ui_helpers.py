from __future__ import annotations

import os
from dataclasses import dataclass

from phase11_core import LearningMode, StudentLearningContext

DEFAULT_STUDENT_ID = os.getenv("AI_TUTOR_STUDENT_ID", "student-1").strip() or "student-1"


@dataclass(frozen=True)
class StudentProfile:
    """Backward-compatible UI profile used by older tests and integrations."""

    student_id: str = DEFAULT_STUDENT_ID
    name: str = "Student"
    grade: int = 7
    board: str = "CBSE"
    language: str = "English (India)"
    medium: str = "English"

    @classmethod
    def from_context(cls, context: StudentLearningContext) -> "StudentProfile":
        return cls(
            student_id=context.student_id,
            name=context.name,
            grade=context.standard,
            board=context.board,
            language=context.preferred_language,
            medium=context.medium,
        )


def command_help() -> str:
    return (
        "Available study tools:\n"
        "• Tutor — ask doubts in explanation, homework, revision or exam mode\n"
        "• + Attachment — add homework photos, PDFs or documents\n"
        "• Voice — speak in Gujarati, Hindi or English when configured\n"
        "• Daily Sync — save what school taught today\n"
        "• Homework — create adaptive practice\n"
        "• Progress — view mastery and activity\n"
        "• Revision — view due revision topics\n"
        "• Mistakes — review misconception patterns\n"
        "• Diagnostic — create a baseline check"
    )


def mode_label(mode: str) -> str:
    labels = {
        LearningMode.EXPLAIN.value: "Explain",
        LearningMode.HOMEWORK.value: "Homework Help",
        LearningMode.REVISION.value: "Revision",
        LearningMode.EXAM.value: "Exam Answer",
    }
    return labels.get(str(mode), "Explain")


def safe_text(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "No information available yet."
