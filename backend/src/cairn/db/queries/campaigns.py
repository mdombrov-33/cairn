import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.domain.exceptions import NotFoundError


async def create_campaign(
    session: AsyncSession,
    *,
    owner_id: str,
    name: str,
    template_id: str,
    world_bible_namespace: str,
) -> Campaign:
    campaign = Campaign(
        owner_id=owner_id,
        name=name,
        template_id=template_id,
        world_bible_namespace=world_bible_namespace,
    )
    session.add(campaign)
    await session.flush()
    return campaign


async def get_campaign(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise NotFoundError(f"campaign {campaign_id} not found", code="campaign_not_found")
    return campaign


async def get_campaign_owned_by(session: AsyncSession, campaign_id: uuid.UUID, owner_id: str) -> Campaign:
    result = await session.execute(select(Campaign).where(Campaign.id == campaign_id, Campaign.owner_id == owner_id))
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise NotFoundError(f"campaign {campaign_id} not found", code="campaign_not_found")
    return campaign


async def list_campaigns_by_owner(session: AsyncSession, owner_id: str) -> list[Campaign]:
    result = await session.execute(
        select(Campaign).where(Campaign.owner_id == owner_id).order_by(Campaign.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_campaign_owned_by(session: AsyncSession, campaign_id: uuid.UUID, owner_id: str) -> None:
    campaign = await get_campaign_owned_by(session, campaign_id, owner_id)
    await session.delete(campaign)
