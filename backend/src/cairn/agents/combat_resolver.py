import json
import uuid
from collections.abc import AsyncIterator

import structlog

from cairn.agents import scene_narrator
from cairn.config import get_settings
from cairn.db import client as db_client
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import AgentError, ToolError
from cairn.llm.client import complete_with_tools
from cairn.llm.router import get_model
from cairn.mcp.tools.combat import (
    advance_turn,
    apply_condition,
    apply_damage,
    apply_healing,
    end_combat,
    remove_condition,
    roll_death_save,
)
from cairn.mcp.tools.dice import roll_d20, roll_damage
from cairn.mcp.tools.game_state import _character_to_dict, get_npc
from cairn.mcp.tools.resources import (
    consume_spell_slot,
    drop_concentration,
    restore_resource,
    restore_spell_slot,
    roll_concentration_check,
    set_concentration,
    spend_movement,
    use_action,
    use_bonus_action,
    use_reaction,
    use_resource,
)
from cairn.mcp.tools.srd import (
    lookup_condition,
    lookup_feature,
    lookup_monster,
    lookup_spell,
    lookup_weapon,
)
from cairn.prompts.registry import load_prompt, resolve_version

log = structlog.get_logger()

# get_combat_state / get_character / get_party are excluded — injected into prompt instead
_COMBAT_TOOLS = [
    # Dice
    roll_d20,
    roll_damage,
    # SRD lookups
    lookup_spell,
    lookup_weapon,
    lookup_monster,
    lookup_condition,
    lookup_feature,
    # Game state
    get_npc,
    # HP & conditions
    apply_damage,
    apply_healing,
    apply_condition,
    remove_condition,
    roll_death_save,
    # Turn flow
    advance_turn,
    end_combat,
    # Resources & economy
    consume_spell_slot,
    restore_spell_slot,
    use_resource,
    restore_resource,
    set_concentration,
    drop_concentration,
    roll_concentration_check,
    use_action,
    use_bonus_action,
    use_reaction,
    spend_movement,
]


async def run(
    player_input: str,
    session_id: str,
    context: str = "",
) -> AsyncIterator[str]:
    """Resolve a combat action and stream the narrative.

    Phase 1: Tool loop - LLM calls MCP tools to resolve all D&D mechanics.
    Phase 2: Narration - scene_narrator streams a vivid description.
    """
    resolution_summary = await _resolve_mechanics(player_input, session_id, context)

    narrative_context = f"[COMBAT RESOLUTION]\n{resolution_summary}"
    if context:
        narrative_context += f"\n\n{context}"

    async for chunk in scene_narrator.run(player_input, context=narrative_context):
        yield chunk


async def _fetch_combat_context(session_id: str) -> tuple[dict | None, list[dict]]:
    """Return (combat_state, party_stat_blocks) fetched in one DB round-trip."""
    sid = uuid.UUID(session_id)
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        combat_state = session.combat_state if session.combat_active else None
        characters = await party_queries.get_party(db, sid)
        party = [_character_to_dict(c) for c in characters]
    return combat_state, party


async def _resolve_mechanics(
    player_input: str,
    session_id: str,
    context: str,
) -> str:
    settings = get_settings()
    version = resolve_version("combat_resolver", settings.llm_prompt_versions)
    prompt = load_prompt("combat_resolver", version)
    model, fallbacks = get_model("combat_resolver", settings.llm_env)

    combat_state, party = await _fetch_combat_context(session_id)

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
    except ToolError:
        raise
    except Exception as exc:
        log.error("combat_resolver_failed", error=str(exc))
        raise AgentError(f"CombatResolver failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("combat_resolver_non_json_response", raw=final_text[:200])
        return final_text
