import json
import uuid

import structlog

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
    apply_effect,
    apply_healing,
    end_combat,
    remove_condition,
    remove_effect,
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

_ENEMY_TOOLS = [
    roll_d20,
    roll_damage,
    lookup_spell,
    lookup_weapon,
    lookup_monster,
    lookup_condition,
    lookup_feature,
    get_npc,
    apply_damage,
    apply_healing,
    apply_condition,
    remove_condition,
    roll_death_save,
    advance_turn,
    end_combat,
    apply_effect,
    remove_effect,
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


async def _fetch_context(session_id: str) -> tuple[dict, list[dict]]:
    sid = uuid.UUID(session_id)
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        combat_state = session.combat_state or {}
        characters = await party_queries.get_party(db, sid)
        party = [_character_to_dict(c) for c in characters]
    return combat_state, party


async def run(session_id: str) -> str:
    """Resolve one enemy turn. Returns a resolution summary string."""
    combat_state, party = await _fetch_context(session_id)

    idx = combat_state.get("turn_index", 0)
    combatants = combat_state.get("combatants", [])
    if not combatants:
        return "No combatants found."
    current = combatants[idx]

    settings = get_settings()
    version = resolve_version("enemy_ai", settings.llm_prompt_versions)
    prompt = load_prompt("enemy_ai", version)
    model, fallbacks = get_model("enemy_ai", settings.llm_env)

    rendered = prompt.render(
        session_id=session_id,
        combatant_name=current["name"],
        combatant_type=current["type"],
        combatant_id=current["id"],
        combat_state=json.dumps(combat_state, indent=2),
        party=json.dumps(party, indent=2),
    )

    try:
        final_text, _ = await complete_with_tools(
            model=model,
            messages=[{"role": "user", "content": rendered}],
            tools=_ENEMY_TOOLS,
            agent="enemy_ai",
            fallbacks=fallbacks,
            temperature=prompt.temperature,
        )
    except ToolError:
        raise
    except Exception as exc:
        log.error("enemy_ai_failed", error=str(exc))
        raise AgentError(f"EnemyAI failed: {exc}") from exc

    try:
        data = json.loads(final_text.strip())
        return str(data.get("summary", final_text))
    except json.JSONDecodeError:
        log.warning("enemy_ai_non_json_response", raw=final_text[:200])
        return final_text
