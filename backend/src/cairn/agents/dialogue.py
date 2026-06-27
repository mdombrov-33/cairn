from typing import Literal

import structlog
from pydantic import BaseModel

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
    """Voice an NPC or a party companion. The deep narrative profile lands in a later slice."""
    prompt, model, fallbacks = agent_setup("dialogue")

    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    name=entity["name"],
                    bio=entity["bio"],
                    personality=entity["personality"],
                    disposition=entity["disposition"],
                    player_input=player_input,
                    context=context,
                ),
            }
        ],
        model_cls=DialogueResult,
        agent="dialogue",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
