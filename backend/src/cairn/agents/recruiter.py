"""Recruiter — adjudicates a bid to bring an NPC into the party.

Not a numeric gate: the candidate weighs the ask against their own profile (goals, prejudices,
personality), their current disposition/approval, recent events, and what the player offered or
proved, then returns a structured decision — accept / refuse / conditional. The resolver acts on
it (conversion, condition-tracking); this agent only decides and voices the reply.
"""

from typing import Literal

import structlog
from pydantic import BaseModel

from cairn.domain.services.narrative_profile import format_profile
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.types import NarrativeProfile

log = structlog.get_logger()


class RecruitDecision(BaseModel):
    decision: Literal["accept", "refuse", "conditional"]
    line: str
    condition: str = ""


async def run(
    player_input: str,
    *,
    profile: NarrativeProfile,
    disposition: str,
    context: str = "",
    approval_band: str | None = None,
    recruitment_condition: str | None = None,
) -> RecruitDecision:
    prompt, model, fallbacks = agent_setup("recruiter")

    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    profile=format_profile(profile),
                    disposition=disposition,
                    context=context,
                    approval_band=approval_band,
                    recruitment_condition=recruitment_condition,
                    player_input=player_input,
                ),
            }
        ],
        model_cls=RecruitDecision,
        agent="recruiter",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
