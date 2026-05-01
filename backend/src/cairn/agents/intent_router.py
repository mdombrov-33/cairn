from typing import Literal, cast

import structlog

from cairn.config import get_settings
from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete
from cairn.llm.router import get_model
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()

Intent = Literal["narrative_action", "skill_check", "npc_dialogue"]
_VALID_INTENTS = {"narrative_action", "skill_check", "npc_dialogue"}


async def run(player_input: str) -> Intent:
    settings = get_settings()
    version = resolve_version("intent_router", settings.llm_prompt_versions)
    prompt = load_prompt("intent_router", version)
    model, fallbacks = get_model("intent_router", settings.llm_env)

    result = await complete(
        model=model,
        messages=[{"role": "user", "content": prompt.render(player_input=player_input)}],
        agent="intent_router",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )

    intent = result.strip().lower()
    if intent not in _VALID_INTENTS:
        log.warning("intent_router_unexpected", raw=result)
        raise AgentError(f"IntentRouter returned unexpected value: {result!r}")

    return cast(Intent, intent)
