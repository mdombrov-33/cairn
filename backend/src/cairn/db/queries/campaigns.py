import uuid

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


async def get_campaign_by_id(session: AsyncSession, campaign_id: uuid.UUID) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise NotFoundError(
            f"campaign {campaign_id} not found", code="campaign_not_found"
        )
    return campaign
