import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.character import Character
from cairn.db.models.party_member import PartyMember


async def add_member(
    session: AsyncSession, *, session_id: uuid.UUID, character_id: uuid.UUID
) -> PartyMember:
    member = PartyMember(session_id=session_id, character_id=character_id)
    session.add(member)
    await session.flush()
    return member


async def enroll_campaign_characters(
    session: AsyncSession, *, session_id: uuid.UUID, campaign_id: uuid.UUID
) -> list[PartyMember]:
    result = await session.execute(select(Character).where(Character.campaign_id == campaign_id))
    characters = list(result.scalars().all())
    enrolled = []
    for char in characters:
        member = PartyMember(session_id=session_id, character_id=char.id)
        session.add(member)
        enrolled.append(member)
    await session.flush()
    return enrolled


async def get_party(session: AsyncSession, session_id: uuid.UUID) -> list[Character]:
    result = await session.execute(
        select(Character)
        .join(PartyMember, PartyMember.character_id == Character.id)
        .where(PartyMember.session_id == session_id)
    )
    return list(result.scalars().all())
