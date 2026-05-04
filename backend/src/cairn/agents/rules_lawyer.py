import json
from typing import Literal

import structlog
from pydantic import BaseModel, ValidationError

from cairn.config import get_settings
from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete
from cairn.llm.router import get_model
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()


class CheckDecision(BaseModel):
    skill: str
    dc: int
    modifier: int
    roll_type: Literal["d20", "advantage", "disadvantage"]


async def run(player_input: str, character_context: str = "") -> CheckDecision:
    settings = get_settings()
    version = resolve_version("rules_lawyer", settings.llm_prompt_versions)
    prompt = load_prompt("rules_lawyer", version)
    model, fallbacks = get_model("rules_lawyer", settings.llm_env)

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
