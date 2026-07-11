import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.world_bible_entry import WorldBibleEntry
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import world_bible as world_bible_queries


async def list_lore(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
    type_: str | None = None,
) -> list[WorldBibleEntry]:
    """World bible entries the player can see, scoped to a campaign they own."""
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await world_bible_queries.list_by_campaign(db, campaign_id, type_=type_)


async def list_calendar(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    owner_id: str,
) -> list[WorldBibleEntry]:
    """DAY_SUMMARY entries in calendar order, scoped to a campaign they own."""
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)
    return await world_bible_queries.list_day_summaries(db, campaign_id)
