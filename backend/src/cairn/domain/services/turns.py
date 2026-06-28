import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import combat_resolver, lore_keeper, scene_director, scene_narrator
from cairn.context import recording_turn
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.session import Session
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
from cairn.domain.services import narrative_context, scene_director_context
from cairn.domain.services import time as time_service
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
    # its own session) can append events to it. Record under the turn around the graph run so
    # prepare-phase nodes (e.g. rest, scene_create) record their work on this turn.
    await db.commit()

    # The graph runs for every turn now — the Scene Director's pre-pass decides whether the
    # turn enters/continues combat, transitions scenes, or routes to a normal resolver.
    with recording_turn(turn.id):
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


def _event(type_: str, data: dict[str, Any]) -> dict[str, Any]:
    """A semantic turn event the route adapts to SSE."""
    return {"type": type_, "data": data}


def _join_context(*parts: str) -> str:
    return "\n\n".join(p for p in parts if p)


def _check_payload(check: CheckData) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "skill": check["skill"],
        "dc": check["dc"],
        "modifier": check["modifier"],
        "roll_type": check["roll_type"],
    }
    helper = check.get("helper")
    if helper:
        payload["helper"] = helper
    return payload


def _schedule_post_turn(
    dm_response: str, *, session_id: uuid.UUID, campaign_id: uuid.UUID, namespace: str, turn_id: uuid.UUID
) -> None:
    """Shared post-narration epilogue: fire the LoreKeeper and the Scene Director post-pass."""
    schedule_lore_keeper(dm_response, campaign_id, namespace, turn_id)
    schedule_scene_director_post(session_id, turn_id)


async def _narrate(
    narrator: AsyncIterator[str],
    db: AsyncSession,
    *,
    turn: Turn,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    namespace: str,
) -> AsyncGenerator[dict[str, Any]]:
    """Stream a narrator's tokens, then persist the narrative and run the epilogue."""
    chunks: list[str] = []
    async for chunk in narrator:
        chunks.append(chunk)
        yield _event("token", {"text": chunk})

    dm_response = "".join(chunks)
    await save_turn_narrative(db, turn_id=turn.id, dm_response=dm_response)
    yield _event("turn_end", {"turn_id": str(turn.id)})
    _schedule_post_turn(
        dm_response, session_id=session_id, campaign_id=campaign_id, namespace=namespace, turn_id=turn.id
    )


async def stream(
    db: AsyncSession,
    *,
    turn: Turn,
    state: TurnState,
    namespace: str,
) -> AsyncGenerator[dict[str, Any]]:
    """Resolve a prepared turn into a stream of semantic events.

    Owns the intent→narrator mapping, the layered DM-context assembly, and the shared
    post-narration epilogue. The route adapts each event to SSE; everything turn-shaped lives
    here. Wrapped in `recording_turn` so combat tools and emitters attach events to this turn.
    """
    session_id = uuid.UUID(state["session_id"])
    campaign_id = uuid.UUID(state["campaign_id"])
    intent = state["intent"]
    is_scene_entry = state["is_scene_entry"]

    with recording_turn(turn.id):
        yield _event("turn_start", {"turn_id": str(turn.id), "intent": intent})

        if intent == "combat_action":
            narrator = combat_resolver.run(state["player_input"], str(session_id))
            async for event in _narrate(
                narrator, db, turn=turn, session_id=session_id, campaign_id=campaign_id, namespace=namespace
            ):
                yield event
            return

        if intent == "rest_action":
            # Rest context uses a special prefix the narrator keys on; keep it standalone.
            narrator = scene_narrator.run(state["player_input"], context=state["rest_context"] or "")
            async for event in _narrate(
                narrator, db, turn=turn, session_id=session_id, campaign_id=campaign_id, namespace=namespace
            ):
                yield event
            return

        # Remaining intents share the layered DM context and onboarding flags.
        dm_context = await narrative_context.build_dm_context(db, session_id)
        intro_mode = await narrative_context.is_intro_mode(db, session_id)
        death_recovery = await consume_death_recovery(db, session_id=session_id)

        if intent == "skill_check":
            check = state["check"]
            assert check is not None
            setup_chunks: list[str] = []
            async for chunk in scene_narrator.run(
                state["player_input"],
                context=dm_context,
                is_scene_entry=is_scene_entry,
                intro_mode=intro_mode,
                death_recovery=death_recovery,
            ):
                setup_chunks.append(chunk)
                yield _event("token", {"text": chunk})
            await save_check_setup(db, turn_id=turn.id, check=check, setup_prose="".join(setup_chunks))
            yield _event("check_required", _check_payload(check))
            return

        # npc_dialogue folds the NPC's line into the context; narrative_action uses DM context alone.
        context = _join_context(dm_context, state["npc_context"] or "") if intent == "npc_dialogue" else dm_context

        narrator = scene_narrator.run(
            state["player_input"],
            context=context,
            is_scene_entry=is_scene_entry,
            intro_mode=intro_mode,
            death_recovery=death_recovery,
        )
        async for event in _narrate(
            narrator, db, turn=turn, session_id=session_id, campaign_id=campaign_id, namespace=namespace
        ):
            yield event


async def stream_resolve(
    db: AsyncSession,
    *,
    turn: Turn,
    check: CheckData,
    active: Character | None,
    effective_roll: int,
    advantage: bool,
    raw_roll: int,
    inspiration_roll: int | None,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
    namespace: str,
) -> AsyncGenerator[dict[str, Any]]:
    """Stream the resolution of a pending skill check: roll_result, narrated outcome, turn_end.

    The inspiration spend and its 422 rejection stay in the route (they must precede streaming);
    this owns the roll math, pickpocket settlement, narration, persistence, and epilogue.
    """
    total = effective_roll + check["modifier"]
    success = total >= check["dc"]

    roll_payload: dict[str, Any] = {"roll": effective_roll, "total": total, "success": success}
    if advantage:
        roll_payload["advantage"] = True
        roll_payload["rolls"] = [raw_roll, inspiration_roll or raw_roll]
    helper = check.get("helper")
    if helper:
        roll_payload["helper"] = helper
    yield _event("roll_result", roll_payload)

    loot_intent = check.get("loot_intent")
    if loot_intent and active is not None:
        await resolve_pickpocket(
            db, session_id=session_id, loot_intent=loot_intent, character_id=active.id, success=success
        )

    # setup_prose is written by save_check_setup before this resolve runs.
    setup_prose = check.get("setup_prose", "")
    outcome_context = (
        f"[Skill Check] {check['skill'].title()} DC {check['dc']}: "
        f"rolled {raw_roll} + {check['modifier']} = {total} — "
        f"{'SUCCESS' if success else 'FAILURE'}\n"
        f"Setup: {setup_prose}"
    )
    outcome_chunks: list[str] = []
    async for chunk in scene_narrator.run(turn.player_input, context=outcome_context):
        outcome_chunks.append(chunk)
        yield _event("token", {"text": chunk})

    outcome_prose = "".join(outcome_chunks)
    dm_response = setup_prose + "\n\n" + outcome_prose
    await save_resolved_check(
        db,
        turn_id=turn.id,
        check=check,
        roll=raw_roll,
        total=total,
        success=success,
        dm_response=dm_response,
    )
    yield _event("turn_end", {"turn_id": str(turn.id)})
    _schedule_post_turn(
        dm_response, session_id=session_id, campaign_id=campaign_id, namespace=namespace, turn_id=turn.id
    )


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
    asyncio.create_task(run_lore_keeper(dm_response, campaign_id, namespace, source_turn_id), name="cairn-bg")


async def run_scene_director_post(session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
    """Observe the completed turn and apply the Scene Director's post-pass decisions.

    Fire-and-forget, mirroring the LoreKeeper. A scene-transition push is recorded as
    Session.pending_transition (applied on the next turn's pre-pass); act progress advances
    the campaign's act index. A DM-narrated time skip (only set alongside a push) advances the
    clock here — unless this turn was a rest that already advanced time, to avoid double-counting.
    """
    try:
        async with db_client.get_sessionmaker()() as db:
            context = await scene_director_context.build_post_response_context(db, session_id, turn_id)

        post = await scene_director.run_post(context)
        if post["scene_transition_push"] is None and not post["act_progress"]:
            return

        async with db_client.get_sessionmaker()() as db, db.begin():
            session = await session_queries.get_session(db, session_id)
            if post["scene_transition_push"] is not None:
                session.pending_transition = post["scene_transition_push"]
            if post["act_progress"]:
                campaign = await campaign_queries.get_campaign(db, session.campaign_id)
                campaign.current_act_index += 1
            if post["time_advance_hours"] > 0:
                await _apply_director_time(db, session, turn_id, post["time_advance_hours"])
        log.info("scene_director_post_done", session_id=str(session_id))
    except Exception as exc:
        log.error("scene_director_post_failed", error=str(exc), session_id=str(session_id))


async def _apply_director_time(db: AsyncSession, session: Session, turn_id: uuid.UUID, hours: int) -> None:
    """Advance the clock for a DM-narrated time skip, guarding against double-counting a rest.

    If this turn already advanced time (e.g. a rest emitted `time_advanced`), the Scene Director's
    skip is a redundant restatement of the same passage of time, so we skip it.
    """
    turn = await turn_queries.get_turn(db, turn_id)
    if any(e.get("type") == "time_advanced" for e in (turn.events or [])):
        log.info("scene_director_time_skip_double_count", turn_id=str(turn_id), hours=hours)
        return
    # No recording scope in this background task; bind one so advance_time's event lands on the turn.
    with recording_turn(turn_id):
        await time_service.advance_time(db, session, hours=hours, source="scene_director")


def schedule_scene_director_post(session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
    asyncio.create_task(run_scene_director_post(session_id, turn_id), name="cairn-bg")


async def consume_death_recovery(db: AsyncSession, *, session_id: uuid.UUID) -> bool:
    """Whether this turn should narrate a narrative-mode death wake-up. Clears the handoff."""
    return await session_queries.consume_pending_recovery(db, session_id)


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
