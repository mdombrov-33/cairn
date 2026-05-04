import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.exceptions import AgentError, ConflictError, NotFoundError
from cairn.pipelines import turn_graph

log = structlog.get_logger()


async def prepare(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    player_input: str,
) -> tuple[Turn, str, str | None, uuid.UUID, str]:
    """Create turn row and classify intent. Returns (turn, intent, npc_name, campaign_id, namespace)."""
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)

    existing = await turn_queries.list_turns(db, session_id)
    idx = len(existing)

    turn = await turn_queries.create_turn(
        db, session_id=session_id, idx=idx, player_input=player_input
    )

    intent, npc_name = await turn_graph.run(player_input, session_id)
    if intent is None:
        raise AgentError("IntentRouter returned no intent")

    log.info("turn_prepared", session_id=str(session_id), idx=idx, intent=intent, npc_name=npc_name)
    return turn, intent, npc_name, db_session.campaign_id, campaign.world_bible_namespace


async def list_turns(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> list[Turn]:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return await turn_queries.list_turns(db, session_id)


async def get_campaign_info(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> tuple[uuid.UUID, str]:
    """Returns (campaign_id, world_bible_namespace) for the session."""
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign(db, db_session.campaign_id)
    return db_session.campaign_id, campaign.world_bible_namespace


async def prepare_resolve(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    owner_id: str,
) -> tuple[Turn, dict]:
    """Verify ownership and that the turn has a pending check. Returns (turn, check_data)."""
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    turn = await turn_queries.get_turn(db, turn_id)

    if turn.session_id != session_id:
        raise NotFoundError(f"turn {turn_id} not found", code="turn_not_found")

    check = turn.check_data
    if not check or check.get("status") != "pending":
        raise ConflictError("no pending check on this turn", code="no_pending_check")

    return turn, check
