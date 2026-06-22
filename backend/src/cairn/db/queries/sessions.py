import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from cairn.db.models.session import Session
from cairn.domain.exceptions import NotFoundError
from cairn.types import CombatState


async def create_session(
    session: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    current_location_id: uuid.UUID | None = None,
    rng_seed: int = 0,
) -> Session:
    db_session = Session(
        campaign_id=campaign_id,
        current_location_id=current_location_id,
        rng_seed=rng_seed,
    )
    session.add(db_session)
    await session.flush()
    return db_session


async def get_session(session: AsyncSession, session_id: uuid.UUID) -> Session:
    result = await session.execute(select(Session).where(Session.id == session_id))
    db_session = result.scalar_one_or_none()
    if db_session is None:
        raise NotFoundError(f"session {session_id} not found", code="session_not_found")
    return db_session


async def get_active_session(session: AsyncSession, campaign_id: uuid.UUID) -> Session | None:
    result = await session.execute(
        select(Session).where(
            Session.campaign_id == campaign_id,
            Session.ended_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def update_combat_state(
    session: AsyncSession,
    session_id: uuid.UUID,
    *,
    combat_state: CombatState | None,
    combat_active: bool,
) -> Session:
    db_session = await get_session(session, session_id)
    db_session.combat_active = combat_active
    db_session.combat_state = combat_state
    flag_modified(db_session, "combat_state")
    await session.flush()
    return db_session
