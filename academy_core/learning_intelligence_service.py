from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Sequence, Tuple

from .exam_readiness import ExamReadinessCalculator
from .intelligent_revision_planner import IntelligentRevisionPlanner
from .learning_intelligence_models import (ConceptIntelligence, IntelligenceSummary, LearningIntelligenceProfile,
    SubjectIntelligence, TrendDirection)
from .mastery_analytics import (consistency_score, events_by_subject, learning_velocity, mastery_score,
    syllabus_coverage, trend_direction)
from .memory_models import MasteryLevel
from .long_term_memory_service import LongTermStudentMemoryService


class LearningIntelligenceService:
    def __init__(self, memory: LongTermStudentMemoryService, *, readiness=None, planner=None) -> None:
        self.memory=memory
        self.readiness=readiness or ExamReadinessCalculator()
        self.planner=planner or IntelligentRevisionPlanner()

    def build_profile(self, student_id: str, *, now: datetime|None=None) -> LearningIntelligenceProfile:
        generated=(now or datetime.now(timezone.utc)).isoformat()
        graph=self.memory.graph_for(student_id)
        nodes=graph.all_nodes(); events=self.memory.repository.events_for_student(student_id)
        blocked=set(graph.blocked_concepts())
        concepts=[]
        for node in nodes:
            downstream=sum(1 for other in nodes if node.concept_id in other.prerequisite_ids)
            prereq_impact=min(1.0, downstream/max(1,len(nodes)-1))
            due=self.memory.scheduler.forgetting_risk(node, now=now)
            reasons=[]
            if node.concept_id in blocked: reasons.append("A prerequisite is not yet secure.")
            if node.misconception_ids: reasons.append("A known misconception needs repair.")
            if due: reasons.append("Revision is due to reduce forgetting risk.")
            ms=mastery_score(node)
            priority=round(min(100,(1-ms)*55 + prereq_impact*25 + (15 if due else 0) + (15 if node.misconception_ids else 0)))
            ci=ConceptIntelligence(node.concept_id,node.subject,node.name,ms,node.evidence_count,node.confidence_score,
                                   round(prereq_impact,4),due,priority,tuple(reasons)); ci.validate(); concepts.append(ci)
        concept_map={c.concept_id:c for c in concepts}
        grouped_nodes=defaultdict(list)
        for node in nodes: grouped_nodes[node.subject].append(node)
        grouped_events=events_by_subject(nodes,events)
        subjects=[]
        for subject,snodes in sorted(grouped_nodes.items()):
            sevents=grouped_events.get(subject,[]); vel=learning_velocity(sevents)
            priorities=tuple(c.concept_id for c in sorted((concept_map[n.concept_id] for n in snodes),key=lambda x:-x.priority_score)[:3])
            subjects.append(SubjectIntelligence(subject,round(mean(mastery_score(n) for n in snodes),4),syllabus_coverage(snodes),
                len(sevents),consistency_score(sevents),vel,trend_direction(vel,len(sevents)),priorities))
        overall_consistency=consistency_score(events); overall_velocity=learning_velocity(events)
        prerequisite_health=1.0-(len(blocked)/len(nodes)) if nodes else 0.0
        due_count=sum(1 for c in concepts if c.revision_due)
        revision_completion=1.0-(due_count/len(nodes)) if nodes else 0.0
        priority=tuple(c.concept_id for c in sorted(concepts,key=lambda x:-x.priority_score)[:5])
        exam=self.readiness.calculate(student_id=student_id,mastery_scores=[c.mastery_score for c in concepts],
            syllabus_coverage=syllabus_coverage(nodes),consistency_score=overall_consistency,
            prerequisite_health=prerequisite_health,revision_completion=revision_completion,evidence_count=len(events),
            generated_at=generated,priority_concepts=priority)
        plan=self.planner.build(graph,concepts)
        return LearningIntelligenceProfile(student_id,tuple(concepts),tuple(subjects),exam,plan,overall_velocity,
            overall_consistency,trend_direction(overall_velocity,len(events)),generated)

    def summary(self, profile: LearningIntelligenceProfile, audience: str) -> IntelligenceSummary:
        role=audience.strip().lower()
        allowed={"teacher","class_teacher","principal","guardian"}
        if role not in allowed: raise ValueError("unsupported intelligence-summary audience")
        strongest=sorted(profile.concepts,key=lambda c:c.mastery_score,reverse=True)[:3]
        priority=sorted(profile.concepts,key=lambda c:c.priority_score,reverse=True)[:3]
        strengths=tuple(c.name for c in strongest if c.mastery_score>=0.65)
        support=tuple(c.name for c in priority if c.priority_score>=45)
        actions=tuple(f"Support {item.name} with {item.suggested_action}." for item in profile.revision_plan[:3])
        band=profile.exam_readiness.readiness_band.value.replace("_"," ")
        headline=f"Current evidence suggests {band}; this is a support estimate, not a fixed prediction."
        if role=="guardian":
            support=tuple(f"Support area: {name}" for name in support)
            caution="Use this summary to support the learner without comparison, pressure, or permanent labels."
        else:
            caution="Interpret readiness with the listed uncertainty and review fresh evidence before decisions."
        return IntelligenceSummary(role,profile.student_id,headline,strengths,support,actions,caution)
