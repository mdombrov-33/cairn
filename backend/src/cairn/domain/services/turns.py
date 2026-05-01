import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.exceptions import AgentError
from cairn.pipelines import turn_graph

log = structlog.get_logger()


async def _verify_ownership(db: AsyncSession, session_id: uuid.UUID, owner_id: str) -> None:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)


async def prepare(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    player_input: str,
) -> tuple[Turn, str]:
    """Create turn row and classify intent. Returns (turn, intent)."""
    await _verify_ownership(db, session_id, owner_id)

    existing = await turn_queries.list_turns(db, session_id)
    idx = len(existing)

    turn = await turn_queries.create_turn(
        db, session_id=session_id, idx=idx, player_input=player_input
    )

    intent = await turn_graph.run(player_input, session_id)
    if intent is None:
        raise AgentError("IntentRouter returned no intent")
    log.info("turn_prepared", session_id=str(session_id), idx=idx, intent=intent)
    return turn, intent


async def list_turns(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> list[Turn]:
    await _verify_ownership(db, session_id, owner_id)
    return await turn_queries.list_turns(db, session_id)
