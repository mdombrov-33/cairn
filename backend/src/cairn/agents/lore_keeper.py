import json

import structlog
from pydantic import BaseModel

from cairn.llm.client import complete
from cairn.llm.router import agent_setup

log = structlog.get_logger()

_VALID_TYPES = {"NPC", "PLACE", "EVENT", "QUEST"}


class LoreEntry(BaseModel):
    type: str
    key: str
    content: str


async def run(dm_response: str) -> list[LoreEntry]:
    prompt, model, fallbacks = agent_setup("lore_keeper")

    raw = await complete(
        model=model,
        messages=[{"role": "user", "content": prompt.render(dm_response=dm_response)}],
        agent="lore_keeper",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )

    try:
        data = json.loads(raw.strip())
        entries = [LoreEntry.model_validate(e) for e in data if e.get("type") in _VALID_TYPES]
        return entries
    except Exception as exc:
        log.info("lore_keeper_bad_output", raw=raw, error=str(exc))
        return []
