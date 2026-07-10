from typing import Literal

import structlog
from pydantic import BaseModel

from cairn.context import current_campaign_settings
from cairn.domain.services.narrative_profile import format_profile
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.types import DialogueEntity

log = structlog.get_logger()


class DialogueResult(BaseModel):
    dialogue: str
    disposition_change: Literal["friendly", "neutral", "hostile"] | None = None


async def run(
    player_input: str,
    entity: DialogueEntity,
    context: str = "",
) -> DialogueResult:
    """Voice an NPC or a party companion straight from their narrative profile."""
    prompt, model, fallbacks = agent_setup("dialogue")
    content = (current_campaign_settings.get() or {}).get("content", {})

    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    name=entity["name"],
                    profile=format_profile(entity["profile"]),
                    disposition=entity["disposition"],
                    approval_band=entity.get("approval_band"),
                    mood=entity.get("mood"),
                    player_input=player_input,
                    context=context,
                    content=content,
                ),
            }
        ],
        model_cls=DialogueResult,
        agent="dialogue",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
