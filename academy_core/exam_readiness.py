from __future__ import annotations

from statistics import mean
from typing import Sequence, Tuple

from .learning_intelligence_models import ExamReadinessReport, ReadinessBand


class ExamReadinessCalculator:
    def calculate(self, *, student_id: str, mastery_scores: Sequence[float], syllabus_coverage: float,
                  consistency_score: float, prerequisite_health: float, revision_completion: float,
                  evidence_count: int, generated_at: str, priority_concepts: Sequence[str]) -> ExamReadinessReport:
        mastery = mean(mastery_scores) if mastery_scores else 0.0
        evidence_confidence = min(evidence_count / max(5, len(mastery_scores)*2), 1.0) if mastery_scores else 0.0
        raw=(mastery*0.35 + syllabus_coverage*0.2 + consistency_score*0.12 + prerequisite_health*0.18 + revision_completion*0.15)
        readiness=round(raw*evidence_confidence,4)
        uncertainty=[]
        if evidence_count < 3: uncertainty.append("Too little recent evidence for a confident readiness estimate.")
        if syllabus_coverage < 0.5: uncertainty.append("Less than half of the registered syllabus has evidence.")
        if evidence_confidence < 0.6: uncertainty.append("Readiness confidence is limited by sparse evidence.")
        return ExamReadinessReport(student_id, readiness, self._band(readiness,evidence_confidence), round(evidence_confidence,4),
            round(syllabus_coverage,4), round(mastery,4), round(consistency_score,4), round(prerequisite_health,4),
            round(revision_completion,4), tuple(uncertainty), tuple(priority_concepts), generated_at)

    @staticmethod
    def _band(score: float, confidence: float) -> ReadinessBand:
        if confidence < 0.3: return ReadinessBand.INSUFFICIENT_EVIDENCE
        if score < 0.35: return ReadinessBand.FOUNDATION_NEEDED
        if score < 0.55: return ReadinessBand.DEVELOPING
        if score < 0.72: return ReadinessBand.APPROACHING_READY
        return ReadinessBand.READY_WITH_REVISION
