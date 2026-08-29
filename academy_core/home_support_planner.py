from __future__ import annotations

from typing import Tuple

from .parent_reporting_models import HomeSupportAction, LearningReportInput


class HomeSupportPlanner:
    def build(self, report_input: LearningReportInput) -> Tuple[HomeSupportAction, ...]:
        actions = []

        for topic in report_input.revision_priorities[:2]:
            actions.append(
                HomeSupportAction(
                    title=f"Short revision: {topic}",
                    instruction=(
                        f"Ask the student to explain {topic} in their own words, "
                        "then solve one small example. Offer hints before answers."
                    ),
                    estimated_minutes=12,
                    reason="Current revision priority",
                )
            )

        if report_input.support_areas:
            actions.append(
                HomeSupportAction(
                    title="Pressure-free support conversation",
                    instruction=(
                        "Ask what felt difficult and what kind of explanation would help. "
                        "Do not compare marks or use permanent labels."
                    ),
                    estimated_minutes=8,
                    reason="A support area was observed",
                )
            )

        if report_input.interests:
            interest = report_input.interests[0]
            actions.append(
                HomeSupportAction(
                    title=f"Interest connection: {interest}",
                    instruction=(
                        f"Connect one school concept with {interest} through a simple "
                        "question, story, or real-life example."
                    ),
                    estimated_minutes=10,
                    reason="Build motivation through a current interest signal",
                )
            )

        if not actions:
            actions.append(
                HomeSupportAction(
                    title="Celebrate learning effort",
                    instruction=(
                        "Ask the student to share one thing learned and appreciate the "
                        "effort or persistence shown."
                    ),
                    estimated_minutes=5,
                    reason="Maintain a healthy learning routine",
                )
            )

        return tuple(actions[:4])
