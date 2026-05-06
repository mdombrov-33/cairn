"""Shared tool list and context helpers used by combat agents."""

import uuid

from cairn.db import client as db_client
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries
from cairn.mcp.tools.base import Tool
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

COMBAT_TOOLS: list[Tool] = [
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


async def fetch_combat_context(session_id: str) -> tuple[dict, list[dict]]:
    """Return (combat_state, party_stat_blocks) for a session. combat_state is {} if no active combat."""  # noqa: E501
    sid = uuid.UUID(session_id)
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        combat_state = session.combat_state or {}
        characters = await party_queries.get_party(db, sid)
        party = [_character_to_dict(c) for c in characters]
    return combat_state, party
