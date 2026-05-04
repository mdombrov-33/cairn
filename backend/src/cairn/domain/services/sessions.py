import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.session import Session
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import party_members as sc_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError
from cairn.domain.services import campaigns as campaign_service


async def start(db: AsyncSession, *, campaign_id: uuid.UUID, owner_id: str) -> Session:
    await campaign_queries.get_campaign_owned_by(db, campaign_id, owner_id)

    active = await session_queries.get_active_session(db, campaign_id)
    if active is not None:
        raise ConflictError("campaign already has an active session")

    starting_location = await campaign_service.get_starting_location(db, campaign_id)

    db_session = await session_queries.create_session(
        db,
        campaign_id=campaign_id,
        current_location_id=starting_location.id if starting_location else None,
    )

    await sc_queries.enroll_campaign_characters(
        db, session_id=db_session.id, campaign_id=campaign_id
    )

    return db_session


async def get(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> Session:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return db_session


async def end(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> Session:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return await session_queries.end_session(db, session_id)
