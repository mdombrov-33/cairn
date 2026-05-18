import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import lore_keeper
from cairn.db import client as db_client
from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import AgentError, ConflictError, NotFoundError
from cairn.pipelines import turn_graph
from cairn.pipelines.turn_graph import TurnState
from cairn.types import CheckData

log = structlog.get_logger()


async def prepare(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    owner_id: str,
    player_input: str,
) -> tuple[Turn, TurnState, str]:
    """Create turn row, classify intent, and run non-streaming pre-processing.

    Returns (turn, graph_state, world_bible_namespace).
    """
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)

    existing = await turn_queries.list_turns(db, session_id)
    turn = await turn_queries.create_turn(db, session_id=session_id, idx=len(existing), player_input=player_input)

    if db_session.combat_active:
        state = TurnState(
            session_id=str(session_id),
            campaign_id=str(db_session.campaign_id),
            player_input=player_input,
            intent="combat_action",
            npc_name=None,
            check=None,
            npc_context=None,
        )
    else:
        state = await turn_graph.run(
            player_input=player_input,
            session_id=session_id,
            campaign_id=db_session.campaign_id,
        )
        if state["intent"] is None:
            raise AgentError("IntentRouter returned no intent")

    log.info(
        "turn_prepared",
        session_id=str(session_id),
        idx=len(existing),
        intent=state["intent"],
    )
    return turn, state, campaign.world_bible_namespace


async def run_lore_keeper(
    dm_response: str,
    campaign_id: uuid.UUID,
    namespace: str,
    source_turn_id: uuid.UUID,
) -> None:
    """Extract and persist world bible entries from a completed DM response. Fire-and-forget."""

    try:
        entries = await lore_keeper.run(dm_response)
        if not entries:
            return
        async with db_client.get_sessionmaker()() as session, session.begin():
            for entry in entries:
                await world_bible_queries.upsert_entry(
                    session,
                    campaign_id=campaign_id,
                    namespace=namespace,
                    type_=entry.type,
                    key=entry.key,
                    content=entry.content,
                    source_turn_id=source_turn_id,
                )
        log.info("lore_keeper_done", count=len(entries), campaign_id=str(campaign_id))
    except Exception as exc:
        log.error("lore_keeper_failed", error=str(exc), campaign_id=str(campaign_id))


def schedule_lore_keeper(
    dm_response: str,
    campaign_id: uuid.UUID,
    namespace: str,
    source_turn_id: uuid.UUID,
) -> None:
    asyncio.create_task(run_lore_keeper(dm_response, campaign_id, namespace, source_turn_id))


async def list_turns(db: AsyncSession, *, session_id: uuid.UUID, owner_id: str) -> list[Turn]:
    db_session = await session_queries.get_session(db, session_id)
    await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    return await turn_queries.list_turns(db, session_id)


async def get_campaign_info(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
) -> tuple[uuid.UUID, str]:
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign(db, db_session.campaign_id)
    return db_session.campaign_id, campaign.world_bible_namespace


async def save_turn_narrative(
    db: AsyncSession,
    *,
    turn_id: uuid.UUID,
    dm_response: str,
) -> None:
    await turn_queries.update_turn_response(db, turn_id, dm_response=dm_response)


async def save_check_setup(
    db: AsyncSession,
    *,
    turn_id: uuid.UUID,
    check: CheckData,
    setup_prose: str,
) -> None:
    updated: CheckData = {**check, "setup_prose": setup_prose}
    await turn_queries.update_turn_check(db, turn_id, check_data=updated)


async def save_resolved_check(
    db: AsyncSession,
    *,
    turn_id: uuid.UUID,
    check: CheckData,
    roll: int,
    total: int,
    success: bool,
    dm_response: str,
) -> None:
    await turn_queries.update_turn_response(db, turn_id, dm_response=dm_response)
    updated: CheckData = {
        **check,
        "status": "resolved",
        "roll": roll,
        "total": total,
        "success": success,
    }
    await turn_queries.update_turn_check(db, turn_id, check_data=updated)


async def prepare_resolve(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    owner_id: str,
) -> tuple[Turn, CheckData]:
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
