import uuid

import structlog
from langchain_core.tools import tool

from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries

log = structlog.get_logger()


def _character_to_dict(c: Character) -> dict:
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
    }


def _npc_to_dict(n: NPC) -> dict:
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
    }


@tool
async def get_character(character_id: str) -> dict:
    """Get a player character's full combat sheet: stats, current HP, AC, spell slots, and inventory.

    Args:
        character_id: The character's UUID.
    """  # noqa: E501
    async with db_client.get_session() as db:
        try:
            char = await character_queries.get_character(db, uuid.UUID(character_id))
            return _character_to_dict(char)
        except Exception as exc:
            log.error("tool_error", tool=__name__, error=str(exc))
            return {"error": str(exc)}


@tool
async def get_npc(npc_id: str) -> dict:
    """Get an NPC's full stat block: current HP, AC, conditions, disposition, and spells.

    Use this when an NPC is involved in combat (either as an enemy or an ally being attacked).

    Args:
        npc_id: The NPC's UUID.
    """
    async with db_client.get_session() as db:
        try:
            npc = await npc_queries.get_npc(db, uuid.UUID(npc_id))
            return _npc_to_dict(npc)
        except Exception as exc:
            log.error("tool_error", tool=__name__, error=str(exc))
            return {"error": str(exc)}


@tool
async def get_party(session_id: str) -> dict:
    """Get all party members' current combat stats for a session.

    Returns HP, AC, conditions, and spell slots for every character in the party.
    Use at the start of combat or when assessing party status.

    Args:
        session_id: The session UUID.
    """
    async with db_client.get_session() as db:
        try:
            characters = await party_queries.get_party(db, uuid.UUID(session_id))
            return {"party": [_character_to_dict(c) for c in characters]}
        except Exception as exc:
            log.error("tool_error", tool=__name__, error=str(exc))
            return {"error": str(exc)}


@tool
async def get_combat_state(session_id: str) -> dict:
    """Get the full active combat state: initiative order, combatant HP, conditions, zones, and current round.

    Args:
        session_id: The session UUID.
    """  # noqa: E501
    async with db_client.get_session() as db:
        try:
            session = await session_queries.get_session(db, uuid.UUID(session_id))
            if not session.combat_active:
                return {"combat_active": False}
            return {
                "combat_active": True,
                "combat_state": session.combat_state,
            }
        except Exception as exc:
            log.error("tool_error", tool=__name__, error=str(exc))
            return {"error": str(exc)}
