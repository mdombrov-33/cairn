import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import lore_keeper
from cairn.context import current_turn_id
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import AgentError, ConflictError, NotFoundError
from cairn.domain.services import loot as loot_service
from cairn.pipelines import turn_graph
from cairn.pipelines.turn_graph import TurnState
from cairn.types import CheckData, LootIntent

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

    scene = await scene_queries.get_current_scene(db, db_session.campaign_id)
    if scene is None:
        raise ConflictError("session has no active scene", code="no_active_scene")

    existing = await turn_queries.list_turns(db, session_id)
    turn = await turn_queries.create_turn(
        db, session_id=session_id, scene_id=scene.id, idx=len(existing), player_input=player_input
    )
    # Commit the turn before any graph/streaming work so the combat emitter (which opens
    # its own session) can append events to it. Set current_turn_id around the graph run so
    # prepare-phase nodes (e.g. rest) record their events on this turn.
    await db.commit()

    if db_session.combat_active:
        state = TurnState(
            session_id=str(session_id),
            campaign_id=str(db_session.campaign_id),
            player_input=player_input,
            intent="combat_action",
            npc_name=None,
            check=None,
            npc_context=None,
            rest_context=None,
        )
    else:
        ctx_token = current_turn_id.set(turn.id)
        try:
            state = await turn_graph.run(
                player_input=player_input,
                session_id=session_id,
                campaign_id=db_session.campaign_id,
            )
        finally:
            current_turn_id.reset(ctx_token)
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
        async with db_client.get_sessionmaker()() as session:
            existing = await world_bible_queries.list_by_campaign(session, campaign_id)
        existing_keys = [e.key for e in existing]

        entries = await lore_keeper.run(dm_response, existing_keys=existing_keys)
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


async def get_active_character(db: AsyncSession, *, session_id: uuid.UUID) -> Character | None:
    """The player's own character (first non-companion), or first party member as a fallback."""
    party = await character_queries.get_party_for_session(db, session_id)
    return next((c for c in party if not c.is_companion), party[0] if party else None)


async def resolve_pickpocket(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    loot_intent: LootIntent,
    character_id: uuid.UUID,
    success: bool,
) -> None:
    """Apply the mechanical outcome of a pickpocket check. Failure flips the NPC hostile."""
    npc_id = uuid.UUID(loot_intent["npc_id"])
    if success:
        try:
            await loot_service.loot_item(
                db,
                session_id=session_id,
                npc_id=npc_id,
                item_name=loot_intent["item_name"],
                character_id=character_id,
            )
        except NotFoundError:
            log.warning("pickpocket_item_missing", npc_id=str(npc_id), item=loot_intent["item_name"])
    else:
        await npc_queries.update_disposition(db, npc_id, "hostile")


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
