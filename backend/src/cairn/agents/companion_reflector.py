"""Companion reflector — the post-turn approval judge.

A fire-and-forget pass that runs after each completed turn (same slot as LoreKeeper),
only when ≥1 companion is present. It weighs what happened against *each companion's own*
personality / prejudices / personal_goal — not an objective morality — and returns the
approval deltas their standing should move by. Structured output, not a tool loop.

Parse-fail safe: an unparseable response degrades to "no deltas" rather than raising, so a
flaky reflector never disturbs a turn.
"""

import json

import structlog
from pydantic import BaseModel

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.types import ApprovalDelta

log = structlog.get_logger()


class _Delta(BaseModel):
    companion_id: str
    delta: int
    reason: str


class _Reflection(BaseModel):
    deltas: list[_Delta] = []


async def run(
    *,
    player_input: str,
    dm_response: str,
    events: list[dict],
    companions: list[dict],
) -> list[ApprovalDelta]:
    """Judge a completed turn per-companion. Returns one delta per companion whose standing moved."""
    prompt, model, fallbacks = agent_setup("companion_reflector")
    try:
        result = await complete_to_model(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": prompt.render(
                        player_input=player_input,
                        dm_response=dm_response,
                        events_json=json.dumps(events, default=str),
                        companions=companions,
                    ),
                }
            ],
            model_cls=_Reflection,
            agent="companion_reflector",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except AgentError:
        log.warning("companion_reflector_parse_failed")
        return []

    return [{"companion_id": d.companion_id, "delta": d.delta, "reason": d.reason} for d in result.deltas]
