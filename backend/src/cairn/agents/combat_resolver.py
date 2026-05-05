import json
from collections.abc import AsyncIterator

import structlog

from cairn.agents import ally_ai, enemy_ai, scene_narrator
from cairn.config import get_settings
from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete_with_tools
from cairn.llm.router import get_model
from cairn.mcp.tools.combat_tools import COMBAT_TOOLS, fetch_combat_context
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()

# get_combat_state / get_character / get_party are excluded — injected into prompt instead
_COMBAT_TOOLS = COMBAT_TOOLS


async def run(
    player_input: str,
    session_id: str,
    context: str = "",
) -> AsyncIterator[str]:
    """Resolve a combat action and stream the narrative.

    Phase 1: Resolve player action via tool loop.
    Phase 2: Loop ally/enemy turns until it's the player's character's turn again.
    Phase 3: Narrate everything together.
    """
    player_summary = await _resolve_mechanics(player_input, session_id, context)

    enemy_summaries: list[str] = []
    for _ in range(20):  # safety cap — no encounter has 20 combatants
        combat_state, _ = await fetch_combat_context(session_id)
        if not combat_state:
            break  # combat ended (victory/defeat)
        combatants = combat_state.get("combatants", [])
        if not combatants:
            break
        current = combatants[combat_state.get("turn_index", 0)]
        if not current.get("is_alive", True):
            break
        if current.get("type") == "character" and not current.get("ai_controlled"):
            break  # player's own character — stop and wait for input
        if current.get("team") == "players":
            summary = await ally_ai.run(session_id)
        else:
            summary = await enemy_ai.run(session_id)
        enemy_summaries.append(summary)

    narrative_context = f"[PLAYER ACTION]\n{player_summary}"
    for s in enemy_summaries:
        narrative_context += f"\n\n[ENEMY TURN]\n{s}"
    if context:
        narrative_context += f"\n\n{context}"

    async for chunk in scene_narrator.run(player_input, context=narrative_context):
        yield chunk


async def _resolve_mechanics(
    player_input: str,
    session_id: str,
    context: str,
) -> str:
    settings = get_settings()
    version = resolve_version("combat_resolver", settings.llm_prompt_versions)
    prompt = load_prompt("combat_resolver", version)
    model, fallbacks = get_model("combat_resolver", settings.llm_env)

    combat_state, party = await fetch_combat_context(session_id)

    rendered = prompt.render(
        session_id=session_id,
        player_input=player_input,
        context=context,
        combat_state=json.dumps(combat_state, indent=2) if combat_state else None,
        party=json.dumps(party, indent=2) if party else None,
    )
    messages = [{"role": "user", "content": rendered}]

    try:
        final_text, _ = await complete_with_tools(
            model=model,
            messages=messages,
            tools=_COMBAT_TOOLS,
            agent="combat_resolver",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except Exception as exc:
        log.error("combat_resolver_failed", error=str(exc))
        raise AgentError(f"CombatResolver failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("combat_resolver_non_json_response", raw=final_text[:200])
        return final_text
