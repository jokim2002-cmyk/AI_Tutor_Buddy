from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Tuple

from .guardian_models import GuardianProfile, StudentProgressSnapshot


class GuardianAccessError(PermissionError):
    pass


class GuardianPrivacyPolicy:
    """Applies least-privilege access to parent-facing learning information."""

    def assert_child_access(
        self,
        guardian: GuardianProfile,
        student_id: str,
    ) -> None:
        guardian.validate()
        if student_id not in guardian.child_ids:
            raise GuardianAccessError(
                "Guardian is not linked to the requested student."
            )

    def sanitize_for_guardian(
        self,
        snapshot: StudentProgressSnapshot,
    ) -> StudentProgressSnapshot:
        snapshot.validate()
        # Private emotional notes are not exposed in ordinary guardian reports.
        return replace(
            snapshot,
            sensitive_notes=(),
            safety_flags=self._guardian_safe_safety_summary(snapshot.safety_flags),
        )

    @staticmethod
    def _guardian_safe_safety_summary(flags: Iterable[str]) -> Tuple[str, ...]:
        normalized = [item.strip() for item in flags if item.strip()]
        if not normalized:
            return ()
        # Exact safety details belong to controlled escalation workflows.
        return ("A wellbeing follow-up may be appropriate.",)

    @staticmethod
    def sibling_comparison_requested(question: str) -> bool:
        text = question.lower()
        comparison_markers = (
            "better than",
            "worse than",
            "more intelligent",
            "less intelligent",
            "compare",
            "comparison",
            "versus",
            "vs ",
            "who is better",
            "kaun better",
            "zyada intelligent",
            "kam intelligent",
        )
        return any(marker in text for marker in comparison_markers)

    @staticmethod
    def comparison_safe_message() -> str:
        return (
            "Har student ka learning path alag hota hai. "
            "Main dono bachchon ki individual strengths, interests aur support "
            "needs alag-alag bata sakta hoon, lekin unhe rank nahi karunga."
        )
