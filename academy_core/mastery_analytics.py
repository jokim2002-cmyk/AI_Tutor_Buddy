from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev
from typing import Dict, Mapping, Sequence, Tuple

from .memory_models import ConceptNode, LearningMemoryEvent, MasteryLevel
from .learning_intelligence_models import TrendDirection


MASTERY_SCORES = {
    MasteryLevel.UNKNOWN: 0.0,
    MasteryLevel.INTRODUCED: 0.25,
    MasteryLevel.DEVELOPING: 0.5,
    MasteryLevel.PROFICIENT: 0.8,
    MasteryLevel.MASTERED: 1.0,
    MasteryLevel.NEEDS_REVISION: 0.35,
}


def mastery_score(node: ConceptNode) -> float:
    base = MASTERY_SCORES[node.mastery]
    if node.evidence_count == 0:
        return base
    evidence_weight = min(node.evidence_count / 5.0, 1.0)
    return round((base * 0.7) + (node.confidence_score * 0.3 * evidence_weight), 4)


def syllabus_coverage(nodes: Sequence[ConceptNode]) -> float:
    if not nodes: return 0.0
    covered = sum(1 for n in nodes if n.mastery != MasteryLevel.UNKNOWN or n.evidence_count > 0)
    return round(covered / len(nodes), 4)


def consistency_score(events: Sequence[LearningMemoryEvent]) -> float:
    if len(events) < 2: return 0.0
    parsed = sorted(_parse(e.timestamp) for e in events)
    active_days = sorted({p.date() for p in parsed})
    if len(active_days) < 2: return 0.35
    gaps = [(active_days[i]-active_days[i-1]).days for i in range(1,len(active_days))]
    avg_gap = mean(gaps)
    spread = pstdev(gaps) if len(gaps)>1 else 0.0
    score = 1.0 - min((avg_gap-1.0)/10.0, 0.65) - min(spread/10.0, 0.25)
    return round(max(0.0, min(1.0, score)), 4)


def learning_velocity(events: Sequence[LearningMemoryEvent]) -> float:
    if len(events) < 2: return 0.0
    ordered = sorted(events, key=lambda e: _parse(e.timestamp))
    midpoint=max(1,len(ordered)//2)
    early=ordered[:midpoint]; late=ordered[midpoint:]
    if not late: return 0.0
    delta=mean(e.evidence_score for e in late)-mean(e.evidence_score for e in early)
    return round(max(-1.0,min(1.0,delta)),4)


def trend_direction(value: float, evidence_count: int) -> TrendDirection:
    if evidence_count < 3: return TrendDirection.INSUFFICIENT_EVIDENCE
    if value >= 0.08: return TrendDirection.IMPROVING
    if value <= -0.08: return TrendDirection.DECLINING
    return TrendDirection.STABLE


def events_by_subject(nodes: Sequence[ConceptNode], events: Sequence[LearningMemoryEvent]):
    subjects={n.concept_id:n.subject for n in nodes}
    grouped=defaultdict(list)
    for event in events:
        subject=subjects.get(event.concept_id)
        if subject: grouped[subject].append(event)
    return grouped


def _parse(value: str) -> datetime:
    dt=datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
