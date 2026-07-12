import uuid
from typing import Annotated

from cairn.api.v1.schemas.characters import CharacterResponse
from cairn.api.v1.schemas.npcs import NPCResponse
from cairn.application import loot as loot_service
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.characters import InventoryItem
from cairn.domain.combat import CombatState
from cairn.domain.combat_rules import empty_combat_state
from cairn.tools.registry import register


def character_to_dict(c: Character) -> dict:
    data = CharacterResponse.model_validate(c).model_dump(by_alias=True, mode="json")
    data["type"] = "character"
    return data


def npc_to_dict(n: NPC) -> dict:
    data = NPCResponse.model_validate(n).model_dump(by_alias=True, mode="json")
    data["type"] = "npc"
    return data


@register
async def get_character(
    character_id: Annotated[str, "The character's UUID."],
) -> dict:
    """Get a player character's full combat sheet: stats, current HP, AC, spell slots, and inventory."""
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(character_id))
        return character_to_dict(char)


@register
async def get_npc(
    npc_id: Annotated[str, "The NPC's UUID."],
) -> dict:
    """Get an NPC's full stat block: current HP, AC, conditions, disposition, and spells."""
    async with db_client.get_session() as db:
        npc = await npc_queries.get_npc(db, uuid.UUID(npc_id))
        return npc_to_dict(npc)


@register
async def get_party(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Get all party members' current combat stats for a session: HP, AC, conditions, and spell slots."""
    async with db_client.get_session() as db:
        characters = await character_queries.get_party_for_session(db, uuid.UUID(session_id))
        return {"party": [character_to_dict(c) for c in characters]}


@register
async def get_combat_state(
    session_id: Annotated[str, "The session UUID."],
) -> dict:
    """Get the full active combat state: initiative order, combatant HP, conditions, zones, and current round."""
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        if not session.combat_active:
            return {"combat_active": False}
        return {"combat_active": True, "combat_state": session.combat_state}


@register
async def loot_item(
    session_id: Annotated[str, "The session UUID."],
    npc_id: Annotated[str, "The NPC's UUID to loot from."],
    item_name: Annotated[str, "Name of the item to transfer."],
    character_id: Annotated[str, "The character UUID who receives the item."],
) -> InventoryItem:
    """Move an item from an NPC's inventory into a character's inventory. Item is not auto-equipped."""
    async with db_client.get_session() as db:
        result = await loot_service.loot_item(
            db,
            session_id=uuid.UUID(session_id),
            npc_id=uuid.UUID(npc_id),
            item_name=item_name,
            character_id=uuid.UUID(character_id),
        )
    return result


async def fetch_combat_context(session_id: str) -> tuple[CombatState, list[dict]]:
    """Return (combat_state, party_stat_blocks) for a session."""
    sid = uuid.UUID(session_id)
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        combat_state = session.combat_state or empty_combat_state()
        characters = await character_queries.get_party_for_session(db, sid)
        party = [character_to_dict(c) for c in characters]
    return combat_state, party
