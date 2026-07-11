"""
Enforces 5e slot constraints:
  - At most one armor equipped at a time.
  - At most one shield equipped at a time.
  - Shield and off-hand weapon are mutually exclusive (handled at route level when
    two-weapon fighting is implemented; not enforced here yet).

AC is re-derived after every mutation.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.domain.exceptions import NotFoundError, ValidationError
from cairn.domain.services.ac import AcInput, derive_ac
from cairn.domain.services.inventory import copy_inventory, find_item, srd_index_of
from cairn.domain.services.settings import resolve_settings
from cairn.srd.catalog import catalog

if TYPE_CHECKING:
    from cairn.api.v1.schemas.characters import EquipRequest

log = structlog.get_logger()


async def _require_player_equipment_control(db: AsyncSession, char: Character, campaign_id: uuid.UUID) -> None:
    if not char.is_companion:
        return
    campaign = await campaign_queries.get_campaign(db, campaign_id)
    if resolve_settings(campaign.settings).companion.equipment != "player":
        raise ValidationError("companion equipment is AI-controlled for this campaign", code="companion_equipment_ai")


def is_armor(srd_index: str) -> bool:
    item = catalog.armor(srd_index)
    return item is not None and item.armor_category != "Shield"


def is_shield(srd_index: str) -> bool:
    item = catalog.armor(srd_index)
    return item is not None and item.armor_category == "Shield"


async def equip(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    body: EquipRequest,
) -> Character:
    """Equip an inventory item by name. Enforces slot constraints then re-derives AC."""
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)
    await _require_player_equipment_control(db, char, campaign_id)
    inventory = copy_inventory(char.inventory or [])

    target = find_item(inventory, body.item_name)
    if target is None:
        raise NotFoundError(f"item {body.item_name!r} not found in inventory", code="item_not_found")

    if target.get("equipped"):
        log.info("equip_already_equipped", character_id=str(character_id), item=body.item_name)
        return char

    armor_data = catalog.armor(srd_index_of(target))

    if armor_data is not None:
        category = armor_data.armor_category
        if category == "Shield":
            for item in inventory:
                if item is not target and item.get("equipped") and is_shield(srd_index_of(item)):
                    item["equipped"] = False
                    log.info("unequipped_previous_shield", item=item.get("name"))
        else:
            for item in inventory:
                if item is not target and item.get("equipped") and is_armor(srd_index_of(item)):
                    item["equipped"] = False
                    log.info("unequipped_previous_armor", item=item.get("name"))

    target["equipped"] = True
    char.inventory = inventory
    char.ac = derive_ac(AcInput.from_row(char))

    log.info("item_equipped", character_id=str(character_id), item=body.item_name, new_ac=char.ac)
    return char


async def unequip(
    db: AsyncSession,
    *,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
    body: EquipRequest,
) -> Character:
    """Unequip an inventory item by name, re-derive AC. Returns updated character."""
    char = await character_queries.get_character_for_campaign_owned_by(db, character_id, campaign_id, owner_id)
    await _require_player_equipment_control(db, char, campaign_id)
    inventory = copy_inventory(char.inventory or [])

    target = find_item(inventory, body.item_name)
    if target is None:
        raise NotFoundError(f"item {body.item_name!r} not found in inventory", code="item_not_found")

    if not target.get("equipped"):
        raise ValidationError(f"item {body.item_name!r} is not currently equipped")

    target["equipped"] = False
    char.inventory = inventory
    char.ac = derive_ac(AcInput.from_row(char))

    log.info("item_unequipped", character_id=str(character_id), item=body.item_name, new_ac=char.ac)
    return char
