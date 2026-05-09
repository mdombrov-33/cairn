import uuid
from typing import Annotated

from langchain_core.tools import tool

from cairn.api.v1.schemas.characters import CharacterResponse
from cairn.api.v1.schemas.npcs import NPCResponse
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.npc import NPC
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import party_members as party_queries
from cairn.db.queries import sessions as session_queries


def character_to_dict(c: Character) -> dict:
    data = CharacterResponse.model_validate(c).model_dump(by_alias=True, mode="json")
    data["type"] = "character"
    return data


def npc_to_dict(n: NPC) -> dict:
    data = NPCResponse.model_validate(n).model_dump(by_alias=True, mode="json")
    data["type"] = "npc"
    return data


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
