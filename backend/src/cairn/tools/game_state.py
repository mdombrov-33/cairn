import uuid
from typing import Annotated

from langchain_core.tools import tool

from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries


def character_to_dict(c: Character) -> dict:
    return {
        "id": str(c.id),
        "type": "character",
        "name": c.name,
        "race": c.race,
        "class": getattr(c, "class_", None),
        "level": c.level,
        "hp": c.hp,
        "max_hp": c.max_hp,
        "temp_hp": c.temp_hp,
        "ac": c.ac,
        "speed": c.speed,
        "initiative_modifier": c.initiative,
        "proficiency_bonus": c.proficiency_bonus,
        "stats": c.stats,
        "saving_throw_proficiencies": c.saving_throw_proficiencies,
        "skill_proficiencies": c.skill_proficiencies,
        "spellcasting_ability": c.spellcasting_ability,
        "spell_slots": c.spell_slots,
        "spells_known": c.spells_known,
        "concentration": c.concentration,
        "resources": c.resources,
        "death_save_successes": c.death_save_successes,
        "death_save_failures": c.death_save_failures,
        "features": c.features,
        "inventory": c.inventory,
        "is_companion": c.is_companion,
        "bio": c.bio,
        "personality": c.personality,
        "voice_traits": c.voice_traits,
    }


def npc_to_dict(n: NPC) -> dict:
    return {
        "id": str(n.id),
        "type": "npc",
        "name": n.name,
        "race": n.race,
        "class": getattr(n, "class_", None),
        "level": n.level,
        "hp": n.hp,
        "max_hp": n.max_hp,
        "temp_hp": n.temp_hp,
        "ac": n.ac,
        "speed": n.speed,
        "initiative_modifier": n.initiative,
        "proficiency_bonus": n.proficiency_bonus,
        "cr": n.cr,
        "stats": n.stats,
        "saving_throw_proficiencies": n.saving_throw_proficiencies,
        "spellcasting_ability": n.spellcasting_ability,
        "spell_slots": n.spell_slots,
        "spells_known": n.spells_known,
        "conditions": n.conditions,
        "disposition": n.disposition,
        "bio": n.bio,
        "personality": n.personality,
        "voice_traits": n.voice_traits,
    }


@tool
async def get_character(
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """Get a player character's full combat sheet: stats, current HP, AC, spell slots, and inventory."""  # noqa: E501
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        return character_to_dict(char)


@tool
async def get_npc(
    npc_id: Annotated[str, "The NPC's UUID."],
) -> dict:
    """Get an NPC's full stat block: current HP, AC, conditions, disposition, and spells."""
    async with db_client.get_session() as db:
        npc = await npc_queries.get_npc(db, uuid.UUID(npc_id))
        return npc_to_dict(npc)


@tool
async def get_party(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Get all party members' current combat stats for a session: HP, AC, conditions, and spell slots."""  # noqa: E501
    async with db_client.get_session() as db:
        characters = await party_queries.get_party(db, uuid.UUID(session_id))
        return {"party": [character_to_dict(c) for c in characters]}


@tool
async def get_combat_state(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Get the full active combat state: initiative order, combatant HP, conditions, zones, and current round."""  # noqa: E501
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        if not session.combat_active:
            return {"combat_active": False}
        return {"combat_active": True, "combat_state": session.combat_state}


async def fetch_combat_context(session_id: str) -> tuple[dict, list[dict]]:
    """Return (combat_state, party_stat_blocks) for a session."""
    sid = uuid.UUID(session_id)
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        combat_state = session.combat_state or {}
        characters = await party_queries.get_party(db, sid)
        party = [character_to_dict(c) for c in characters]
    return combat_state, party
