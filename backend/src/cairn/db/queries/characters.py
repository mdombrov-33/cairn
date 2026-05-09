import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.domain.exceptions import NotFoundError


async def create_character(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    **kwargs: Any,
) -> Character:
    character = Character(campaign_id=campaign_id, owner_id=owner_id, **kwargs)
    session.add(character)
    await session.flush()
    return character


async def get_character(session: AsyncSession, character_id: uuid.UUID) -> Character:
    result = await session.execute(select(Character).where(Character.id == character_id))
    character = result.scalar_one_or_none()
    if character is None:
        raise NotFoundError(f"character {character_id} not found", code="character_not_found")
    return character


async def list_characters_by_campaign(
    session: AsyncSession,
    campaign_id: uuid.UUID,
) -> list[Character]:
    result = await session.execute(select(Character).where(Character.campaign_id == campaign_id))
    return list(result.scalars().all())


async def delete_character(session: AsyncSession, character_id: uuid.UUID) -> None:
    character = await get_character(session, character_id)
    await session.delete(character)
    await session.flush()
