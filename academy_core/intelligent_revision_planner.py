from __future__ import annotations

from typing import Dict, Sequence, Tuple
from .knowledge_graph import StudentKnowledgeGraph
from .learning_intelligence_models import ConceptIntelligence, RevisionPlanItem


class IntelligentRevisionPlanner:
    def build(self, graph: StudentKnowledgeGraph, concepts: Sequence[ConceptIntelligence], *, limit: int = 10) -> Tuple[RevisionPlanItem,...]:
        nodes={n.concept_id:n for n in graph.all_nodes()}
        ordered=sorted(concepts,key=lambda c:(-c.priority_score,c.subject,c.name))[:limit]
        items=[]
        for item in ordered:
            node=nodes[item.concept_id]
            prereqs=tuple(cid for cid in graph.learning_path(item.concept_id)[:-1]
                          if nodes[cid].confidence_score < 0.7)
            action="targeted misconception repair" if node.misconception_ids else (
                "guided retrieval practice" if item.mastery_score < 0.6 else "timed spaced recall")
            minutes=20 if item.priority_score>=80 else 15 if item.priority_score>=55 else 10
            reason="; ".join(item.reasons) or "Consolidate learning evidence."
            items.append(RevisionPlanItem(item.concept_id,item.subject,item.name,item.priority_score,reason,action,minutes,prereqs))
        return tuple(items)
