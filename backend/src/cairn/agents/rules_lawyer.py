import json
from typing import Literal

import structlog
from pydantic import BaseModel, ValidationError

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete
from cairn.llm.router import agent_setup

log = structlog.get_logger()


class CheckDecision(BaseModel):
    skill: str
    dc: int
    modifier: int
    roll_type: Literal["d20", "advantage", "disadvantage"]


async def run(player_input: str, character_context: str = "") -> CheckDecision:
    prompt, model, fallbacks = agent_setup("rules_lawyer")

    raw = await complete(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    player_input=player_input,
                    character_context=character_context or "No character data available.",
                ),
            }
        ],
        agent="rules_lawyer",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )

    try:
        data = json.loads(raw.strip())
        return CheckDecision.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.error("rules_lawyer_bad_output", raw=raw, error=str(exc))
        raise AgentError(f"RulesLawyer returned invalid JSON: {raw!r}") from exc
