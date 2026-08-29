from __future__ import annotations

from collections import Counter
from typing import Dict, List, Mapping, Sequence, Tuple

from .guardian_models import FuturePathSuggestion, StudentProgressSnapshot


class FuturePathAdvisor:
    """Creates exploration suggestions, never deterministic career assignments."""

    _SUBJECT_PATHS: Mapping[str, Tuple[str, ...]] = {
        "maths": (
            "mathematical problem solving",
            "data and analytical thinking",
            "engineering exploration",
        ),
        "science": (
            "scientific investigation",
            "health and life-science exploration",
            "environment and technology projects",
        ),
        "computer": (
            "coding and software creation",
            "robotics and automation",
            "digital design and problem solving",
        ),
        "english": (
            "communication and storytelling",
            "media and content creation",
            "research and public speaking",
        ),
        "hindi": (
            "language, literature, and communication",
            "creative writing",
            "culture and media exploration",
        ),
        "social_science": (
            "history and society research",
            "law, policy, and civic exploration",
            "geography and community projects",
        ),
    }

    def suggest(
        self,
        snapshot: StudentProgressSnapshot,
    ) -> FuturePathSuggestion:
        snapshot.validate()

        subject_scores: Counter[str] = Counter()
        evidence: List[str] = []

        for activity in snapshot.activities:
            subject = activity.subject.lower()
            if activity.understanding.lower() == "understood":
                subject_scores[subject] += 2
            if activity.confidence.lower() == "high":
                subject_scores[subject] += 1
            if activity.duration_minutes >= 15:
                subject_scores[subject] += 1

        for item in snapshot.interests:
            lowered = item.lower()
            for subject in self._SUBJECT_PATHS:
                if subject in lowered:
                    subject_scores[subject] += 3

        for question in snapshot.voluntary_questions:
            lowered = question.lower()
            for subject in self._SUBJECT_PATHS:
                if subject in lowered:
                    subject_scores[subject] += 2

        ranked_subjects = [
            subject for subject, score in subject_scores.most_common()
            if score > 0
        ][:3]

        paths: List[str] = []
        activities: List[str] = []

        for subject in ranked_subjects:
            paths.extend(self._SUBJECT_PATHS.get(subject, ()))
            evidence.append(
                f"Repeated positive learning signals observed in {subject.title()}."
            )
            activities.extend(self._activities_for_subject(subject))

        if snapshot.persistence_signals:
            evidence.append(
                "Persistence signals suggest the student may benefit from "
                "longer open-ended projects."
            )

        if not paths:
            paths = [
                "broad multidisciplinary exploration",
                "creative and practical projects",
                "guided interest discovery",
            ]
            evidence.append(
                "Current evidence is not strong enough to prioritize one field."
            )
            activities = [
                "Try one small activity from science, arts, language, and technology.",
                "Ask the student which activity they would voluntarily repeat.",
            ]

        confidence = (
            "emerging"
            if len(ranked_subjects) <= 1
            else "moderate"
        )

        return FuturePathSuggestion(
            student_id=snapshot.student_id,
            exploration_areas=tuple(dict.fromkeys(paths))[:6],
            evidence_summary=tuple(evidence)[:5],
            suggested_activities=tuple(dict.fromkeys(activities))[:6],
            caution=(
                "This is an exploration map, not a career decision. "
                "Do not force a subject stream or profession. Re-evaluate with "
                "the student's own choices and long-term evidence."
            ),
            confidence=confidence,
        )

    @staticmethod
    def _activities_for_subject(subject: str) -> Tuple[str, ...]:
        mapping: Dict[str, Tuple[str, ...]] = {
            "maths": (
                "Try logic puzzles and real-life measurement projects.",
                "Explore beginner data activities.",
            ),
            "science": (
                "Try safe supervised observations and science projects.",
                "Visit a science museum or use a virtual lab.",
            ),
            "computer": (
                "Try beginner coding, robotics, or digital design.",
                "Build a tiny interactive project.",
            ),
            "english": (
                "Create a short story, podcast, or presentation.",
                "Join a reading or speaking activity.",
            ),
            "hindi": (
                "Write a short story, poem, or dialogue.",
                "Explore theatre, narration, or literature.",
            ),
            "social_science": (
                "Create a local-history or community project.",
                "Build a timeline or map-based investigation.",
            ),
        }
        return mapping.get(subject, ())
