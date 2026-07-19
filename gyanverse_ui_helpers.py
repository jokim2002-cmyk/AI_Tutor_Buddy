from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_STUDENT_ID = os.getenv("AI_TUTOR_STUDENT_ID", "student-1").strip() or "student-1"

@dataclass(frozen=True)
class StudentProfile:
    student_id: str = DEFAULT_STUDENT_ID
    name: str = "Student"
    grade: int = 7
    board: str = "CBSE"
    language: str = "English (India)"

def command_help() -> str:
    return (
        "Available study tools:\n"
        "• Daily Sync — save what school taught today\n"
        "• Homework — create adaptive practice\n"
        "• Progress — view mastery and activity\n"
        "• Revision — view due revision topics\n"
        "• Mistakes — review misconception patterns\n"
        "• Diagnostic — create a baseline check"
    )

def safe_text(value: object) -> str:
    text = str(value or "").strip()
    return text if text else "No information available yet."
