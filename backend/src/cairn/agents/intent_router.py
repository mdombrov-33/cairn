import json
from typing import Literal, cast

import structlog

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete
from cairn.llm.router import agent_setup

log = structlog.get_logger()

Intent = Literal[
    "narrative_action", "skill_check", "npc_dialogue", "rest_action", "recruit_attempt", "dismiss_companion"
]
_VALID_INTENTS = {
    "narrative_action",
    "skill_check",
    "npc_dialogue",
    "rest_action",
    "recruit_attempt",
    "dismiss_companion",
}


async def run(player_input: str) -> tuple[Intent, str | None]:
    prompt, model, fallbacks = agent_setup("intent_router")

    result = await complete(
        model=model,
        messages=[{"role": "user", "content": prompt.render(player_input=player_input)}],
        agent="intent_router",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )

    cleaned = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(cleaned)
        intent = str(data["intent"]).lower()
        npc_name: str | None = data.get("npc_name") or None
    except json.JSONDecodeError, KeyError:
        intent = cleaned.lower()
        npc_name = None

    if intent not in _VALID_INTENTS:
        log.error("intent_router_unexpected", raw=result)
        raise AgentError(f"IntentRouter returned unexpected intent: {intent!r}")

    return cast(Intent, intent), npc_name
