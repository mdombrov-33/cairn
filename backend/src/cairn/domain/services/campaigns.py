import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.campaign import Campaign
from cairn.db.queries import campaigns as queries


async def create(
    db: AsyncSession,
    *,
    owner_id: str,
    name: str,
    template_id: str,
) -> Campaign:
    return await queries.create_campaign(
        db,
        owner_id=owner_id,
        name=name,
        template_id=template_id,
        world_bible_namespace=f"campaign_{uuid.uuid4().hex}",
    )


async def get(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Campaign:
    return await queries.get_campaign_owned_by(db, campaign_id, owner_id)


async def list_(db: AsyncSession, *, owner_id: str) -> list[Campaign]:
    return await queries.list_campaigns_by_owner(db, owner_id)


async def delete(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> None:
    await queries.delete_campaign_owned_by(db, campaign_id, owner_id)
