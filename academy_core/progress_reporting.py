from __future__ import annotations

from collections import Counter
from typing import Iterable, List, Sequence, Tuple

from .guardian_models import GuardianReport, StudentProgressSnapshot


class GuardianReportBuilder:
    def build_daily_report(
        self,
        snapshot: StudentProgressSnapshot,
        *,
        generated_by: str = "Asha Ma'am",
    ) -> GuardianReport:
        snapshot.validate()

        learned = tuple(
            f"{activity.subject.title()}: {activity.topic}"
            for activity in snapshot.activities
            if activity.completed
        )

        strengths = snapshot.strengths or self._derive_strengths(snapshot)
        support = snapshot.support_needs or self._derive_support_needs(snapshot)
        interests = snapshot.interests or self._derive_interest_signals(snapshot)

        return GuardianReport(
            student_id=snapshot.student_id,
            student_name=snapshot.student_name,
            period_label=snapshot.date_label,
            learned_today=learned,
            current_strengths=tuple(strengths),
            support_needs=tuple(support),
            interest_signals=tuple(interests),
            home_support_actions=self._home_support(snapshot, support),
            wellbeing_note=self._wellbeing_note(snapshot),
            privacy_notice=(
                "Private student conversations and sensitive emotional notes are "
                "not included in this routine guardian report."
            ),
            generated_by=generated_by,
        )

    @staticmethod
    def _derive_strengths(snapshot: StudentProgressSnapshot) -> Tuple[str, ...]:
        strengths: List[str] = []
        for activity in snapshot.activities:
            if activity.understanding.lower() == "understood":
                strengths.append(
                    f"Understood {activity.topic} in {activity.subject.title()}"
                )
            if activity.confidence.lower() == "high":
                strengths.append(
                    f"Showed confidence in {activity.subject.title()}"
                )
        return tuple(dict.fromkeys(strengths))[:4]

    @staticmethod
    def _derive_support_needs(
        snapshot: StudentProgressSnapshot,
    ) -> Tuple[str, ...]:
        needs: List[str] = []
        for activity in snapshot.activities:
            if activity.understanding.lower() in {"confused", "guessing"}:
                needs.append(
                    f"Needs guided support with {activity.topic} "
                    f"in {activity.subject.title()}"
                )
            elif activity.confidence.lower() == "low":
                needs.append(
                    f"Needs confidence-building practice in {activity.subject.title()}"
                )
        return tuple(dict.fromkeys(needs))[:4]

    @staticmethod
    def _derive_interest_signals(
        snapshot: StudentProgressSnapshot,
    ) -> Tuple[str, ...]:
        signals = list(snapshot.voluntary_questions)
        subject_counts = Counter(
            activity.subject.title()
            for activity in snapshot.activities
            if activity.duration_minutes >= 15
        )
        for subject, count in subject_counts.most_common(3):
            signals.append(
                f"Sustained engagement observed in {subject}"
            )
        return tuple(dict.fromkeys(signals))[:4]

    @staticmethod
    def _home_support(
        snapshot: StudentProgressSnapshot,
        support_needs: Sequence[str],
    ) -> Tuple[str, ...]:
        actions: List[str] = []

        if support_needs:
            actions.append(
                "Use one short 10-minute practice activity without pressure."
            )
            actions.append(
                "Ask the child to explain one idea in their own words."
            )
        else:
            actions.append(
                "Celebrate today's effort and ask what felt most interesting."
            )

        methods = {item.lower() for item in snapshot.preferred_learning_methods}
        if "visual" in methods:
            actions.append("Use a simple drawing, object, or diagram at home.")
        if "story" in methods:
            actions.append("Connect the topic to a short real-life story.")
        if "experiment" in methods:
            actions.append("Use only a safe, supervised observation activity.")

        actions.append(
            "Avoid comparing the child with siblings or classmates."
        )
        return tuple(dict.fromkeys(actions))[:4]

    @staticmethod
    def _wellbeing_note(snapshot: StudentProgressSnapshot) -> str:
        if snapshot.safety_flags:
            return (
                "A wellbeing follow-up may be appropriate. "
                "The school should use its controlled safeguarding process."
            )
        if any(
            activity.confidence.lower() == "low"
            for activity in snapshot.activities
        ):
            return (
                "Confidence support is recommended; praise effort, strategy, "
                "and small progress."
            )
        return "No routine wellbeing concern appears in today's learning snapshot."
