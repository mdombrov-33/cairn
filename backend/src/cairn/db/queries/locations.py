import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.location import Location


async def create_location(db: AsyncSession, *, campaign_id: uuid.UUID, **kwargs: object) -> Location:
    location = Location(campaign_id=campaign_id, **kwargs)
    db.add(location)
    return location


async def get_first_for_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> Location | None:
    result = await db.execute(select(Location).where(Location.campaign_id == campaign_id).limit(1))
    return result.scalar_one_or_none()


async def get_location(db: AsyncSession, location_id: uuid.UUID) -> Location | None:
    result = await db.execute(select(Location).where(Location.id == location_id))
    return result.scalar_one_or_none()


async def get_location_for_campaign(
    db: AsyncSession, location_id: uuid.UUID, campaign_id: uuid.UUID
) -> Location | None:
    result = await db.execute(select(Location).where(Location.id == location_id, Location.campaign_id == campaign_id))
    return result.scalar_one_or_none()


async def list_by_campaign(db: AsyncSession, campaign_id: uuid.UUID) -> list[Location]:
    result = await db.execute(select(Location).where(Location.campaign_id == campaign_id))
    return list(result.scalars().all())
