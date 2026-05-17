"""
Enforces 5e slot constraints:
  - At most one armor equipped at a time.
  - At most one shield equipped at a time.
  - Shield and off-hand weapon are mutually exclusive (handled at route level when
    two-weapon fighting is implemented; not enforced here yet).

AC is re-derived after every mutation.
"""

import copy
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import characters as character_queries
from cairn.domain.exceptions import NotFoundError, ValidationError
from cairn.domain.services.ac import AcInput, derive_ac
from cairn.srd import get_armor
from cairn.types import InventoryItem

log = structlog.get_logger()


def is_armor(srd_index: str) -> bool:
    item = get_armor(srd_index)
    return item is not None and item.get("armor_category") != "Shield"


def is_shield(srd_index: str) -> bool:
    item = get_armor(srd_index)
    return item is not None and item.get("armor_category") == "Shield"


def _resolve_item(inventory: list[InventoryItem], item_name: str) -> InventoryItem | None:
    """Find an inventory item by name (case-insensitive) or srd_index."""
    name_lower = item_name.lower()
    for item in inventory:
        if item.get("name", "").lower() == name_lower:
            return item
        if item.get("srd_index", "").lower() == name_lower:
            return item
    return None


async def equip(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    item_name: str,
) -> Character:
    """
    Equip an inventory item by name. Enforces slot constraints then re-derives AC.
    Returns the updated character.
    """
    char = await character_queries.get_character_for_campaign_owned_by(
        db, character_id, campaign_id, owner_id
    )
    # Deep-copy each item dict so SQLAlchemy detects the mutation when we reassign.
    inventory = copy.deepcopy(char.inventory or [])

    target = _resolve_item(inventory, item_name)
    if target is None:
        raise NotFoundError(f"item {item_name!r} not found in inventory", code="item_not_found")

    if target.get("equipped"):
        log.info("equip_already_equipped", character_id=str(character_id), item=item_name)
        return char

    srd_index = target.get("srd_index") or target.get("name", "").lower().replace(" ", "-")
    armor_data = get_armor(srd_index)

    if armor_data is not None:
        category = armor_data.get("armor_category")
        if category == "Shield":
            for item in inventory:
                if item is not target and item.get("equipped"):
                    si = item.get("srd_index") or item.get("name", "").lower().replace(" ", "-")
                    if is_shield(si):
                        item["equipped"] = False
                        log.info("unequipped_previous_shield", item=item.get("name"))
        else:
            for item in inventory:
                if item is not target and item.get("equipped"):
                    si = item.get("srd_index") or item.get("name", "").lower().replace(" ", "-")
                    if is_armor(si):
                        item["equipped"] = False
                        log.info("unequipped_previous_armor", item=item.get("name"))

    target["equipped"] = True
    char.inventory = inventory
    char.ac = derive_ac(AcInput.from_row(char))

    log.info("item_equipped", character_id=str(character_id), item=item_name, new_ac=char.ac)
    return char


async def unequip(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    item_name: str,
) -> Character:
    """Unequip an inventory item by name, re-derive AC. Returns updated character."""
    char = await character_queries.get_character_for_campaign_owned_by(
        db, character_id, campaign_id, owner_id
    )
    inventory = copy.deepcopy(char.inventory or [])

    target = _resolve_item(inventory, item_name)
    if target is None:
        raise NotFoundError(f"item {item_name!r} not found in inventory", code="item_not_found")

    if not target.get("equipped"):
        raise ValidationError(f"item {item_name!r} is not currently equipped")

    target["equipped"] = False
    char.inventory = inventory
    char.ac = derive_ac(AcInput.from_row(char))

    log.info("item_unequipped", character_id=str(character_id), item=item_name, new_ac=char.ac)
    return char
