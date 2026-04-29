import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries


async def _verify_ownership(db: AsyncSession, session_id: uuid.UUID, owner_id: str) -> None:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)


async def submit(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    player_input: str,
) -> Turn:
    await _verify_ownership(db, session_id, owner_id)

    existing = await turn_queries.list_turns(db, session_id)
    idx = len(existing)

    return await turn_queries.create_turn(
        db, session_id=session_id, idx=idx, player_input=player_input
    )


async def transcript(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> list[Turn]:
    await _verify_ownership(db, session_id, owner_id)
    return await turn_queries.list_turns(db, session_id)
