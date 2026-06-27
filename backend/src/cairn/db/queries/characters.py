import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
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


async def get_character_for_campaign_owned_by(
    session: AsyncSession,
    character_id: uuid.UUID,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> Character:
    """Fetch a character, verifying it belongs to the campaign and the campaign belongs to owner."""
    result = await session.execute(
        select(Character)
        .join(Campaign, Campaign.id == Character.campaign_id)
        .where(
            Character.id == character_id,
            Character.campaign_id == campaign_id,
            Campaign.owner_id == owner_id,
        )
    )
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


async def get_party_for_session(session: AsyncSession, session_id: uuid.UUID) -> list[Character]:
    """Party = characters in the session's campaign (PCs + companions).

    Party membership derives from Character.campaign_id — there is no per-session enrollment.
    """
    from cairn.db.models.session import Session as SessionModel

    result = await session.execute(
        select(Character)
        .join(SessionModel, SessionModel.campaign_id == Character.campaign_id)
        .where(SessionModel.id == session_id)
    )
    return list(result.scalars().all())


async def find_companion_by_name(session: AsyncSession, campaign_id: uuid.UUID, name_hint: str) -> Character | None:
    """Fuzzy match a companion by name — fallback path when an NPC lookup misses in dialogue."""
    result = await session.execute(
        select(Character).where(Character.campaign_id == campaign_id, Character.is_companion.is_(True))
    )
    hint = name_hint.lower()
    for char in result.scalars().all():
        char_lower = char.name.lower()
        if hint in char_lower or char_lower in hint:
            return char
    return None


async def delete_character(session: AsyncSession, character_id: uuid.UUID) -> None:
    character = await get_character(session, character_id)
    await session.delete(character)
    await session.flush()
