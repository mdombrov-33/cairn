import json

import structlog
from pydantic import BaseModel

from cairn.config import get_settings
from cairn.llm.client import complete
from cairn.llm.router import get_model
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()

_VALID_TYPES = {"NPC", "PLACE", "EVENT", "QUEST"}


class LoreEntry(BaseModel):
    type: str
    key: str
    content: str


async def run(dm_response: str) -> list[LoreEntry]:
    settings = get_settings()
    version = resolve_version("lore_keeper", settings.llm_prompt_versions)
    prompt = load_prompt("lore_keeper", version)
    model, fallbacks = get_model("lore_keeper", settings.llm_env)

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
        log.warning("lore_keeper_bad_output", raw=raw, error=str(exc))
        return []
