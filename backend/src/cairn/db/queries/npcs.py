import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.npc import NPC
from cairn.domain.exceptions import NotFoundError


async def create_npc(session: AsyncSession, *, campaign_id: uuid.UUID, **fields: Any) -> NPC:
    npc = NPC(campaign_id=campaign_id, **fields)
    session.add(npc)
    await session.flush()
    return npc


async def get_npcs_by_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> list[NPC]:
    result = await session.execute(select(NPC).where(NPC.campaign_id == campaign_id).order_by(NPC.name))
    return list(result.scalars().all())


async def get_npc(session: AsyncSession, npc_id: uuid.UUID) -> NPC:
    result = await session.execute(select(NPC).where(NPC.id == npc_id))
    npc = result.scalar_one_or_none()
    if npc is None:
        raise NotFoundError(f"npc {npc_id} not found", code="npc_not_found")
    return npc


async def find_by_name(session: AsyncSession, campaign_id: uuid.UUID, name_hint: str) -> NPC | None:
    """Fuzzy match: finds the first NPC whose name contains the hint or vice versa."""
    npcs = await get_npcs_by_campaign(session, campaign_id)
    hint = name_hint.lower()
    for npc in npcs:
        npc_lower = npc.name.lower()
        if hint in npc_lower or npc_lower in hint:
            return npc
    return None


async def update_disposition(session: AsyncSession, npc_id: uuid.UUID, disposition: str) -> NPC:
    npc = await get_npc(session, npc_id)
    npc.disposition = disposition
    await session.flush()
    return npc
