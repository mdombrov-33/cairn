import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.session import Session
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError


async def start(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Session:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)

    active = await session_queries.get_active_session(db, campaign_id)
    if active is not None:
        raise ConflictError("campaign already has an active session")

    return await session_queries.create_session(db, campaign_id=campaign_id)


async def get(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> Session:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return db_session


async def end(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> Session:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return await session_queries.end_session(db, session_id)
