from typing import Literal

import structlog
from pydantic import BaseModel

from cairn.db.models.npc import NPC
from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup

log = structlog.get_logger()


class NPCDialogueResult(BaseModel):
    dialogue: str
    disposition_change: Literal["friendly", "neutral", "hostile"] | None = None


async def run(
    player_input: str,
    npc: NPC,
    context: str = "",
) -> NPCDialogueResult:
    prompt, model, fallbacks = agent_setup("npc_dialogue")

    voice_summary = npc.voice_traits.get("speech_pattern", "") if npc.voice_traits else ""

    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    npc_name=npc.name,
                    npc_bio=npc.bio,
                    npc_personality=npc.personality,
                    npc_voice=voice_summary,
                    npc_disposition=npc.disposition,
                    player_input=player_input,
                    context=context,
                ),
            }
        ],
        model_cls=NPCDialogueResult,
        agent="npc_dialogue",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
