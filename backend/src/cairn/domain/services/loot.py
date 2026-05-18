import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import NotFoundError, ValidationError
from cairn.domain.services.inventory import copy_inventory, find_item
from cairn.types import InventoryItem


async def loot_item(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    npc_id: uuid.UUID,
    item_name: str,
    character_id: uuid.UUID,
) -> InventoryItem:
    """Move item_name from npc.inventory to character.inventory. Returns the looted item.

    NPC and character must both belong to the session's campaign.
    """
    db_session = await session_queries.get_session(db, session_id)
    npc = await npc_queries.get_npc(db, npc_id)
    char = await character_queries.get_character(db, character_id)

    if npc.campaign_id != db_session.campaign_id:
        raise ValidationError("npc does not belong to this session's campaign")
    if char.campaign_id != db_session.campaign_id:
        raise ValidationError("character does not belong to this session's campaign")

    npc_inventory = copy_inventory(npc.inventory or [])
    item = find_item(npc_inventory, item_name)
    if item is None:
        raise NotFoundError(f"item {item_name!r} not in NPC inventory", code="item_not_found")

    npc_inventory.remove(item)
    npc.inventory = npc_inventory

    looted = cast(InventoryItem, {k: v for k, v in item.items() if k != "equipped"})
    char.inventory = copy_inventory(char.inventory or []) + [looted]

    await db.flush()
    return looted
