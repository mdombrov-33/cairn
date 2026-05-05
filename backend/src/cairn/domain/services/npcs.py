import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.npc import NPC
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import npcs as npc_queries


async def list_by_campaign(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> list[NPC]:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await npc_queries.get_npcs_by_campaign(db, campaign_id)


async def get(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    npc_id: uuid.UUID,
    owner_id: str,
) -> NPC:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await npc_queries.get_npc(db, npc_id)
