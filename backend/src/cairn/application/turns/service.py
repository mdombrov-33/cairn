import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import (
    combat_resolver,
    companion_reflector,
    lore_keeper,
    scene_director,
    scene_narrator,
    scene_summarizer,
)
from cairn.application import companions as companions_service
from cairn.application import loot as loot_service
from cairn.application import narrative_context, scene_director_context
from cairn.application import time as time_service
from cairn.application.turns.types import CheckData, CompanionActionProposal, LootIntent
from cairn.context import recording_turn, using_campaign_settings
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.scene import Scene
from cairn.db.models.session import Session
from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import AgentError, ConflictError, NotFoundError, ValidationError
from cairn.domain.services import campaign_view
from cairn.domain.services import settings as settings_service
from cairn.pipelines import turn_graph
from cairn.pipelines.turn_graph import TurnState
from cairn.types import NpcPresence, ScenePostOutput

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
    # Mechanical pacing beat — one per turn in the scene, no LLM. Committed before the graph runs
    # so the Scene Director pre-pass (its own session) reads this turn's count.
    await scene_queries.increment_beat_count(db, scene.id)
    # Commit the turn before any graph/streaming work so the combat emitter (which opens
    # its own session) can append events to it. Record under the turn around the graph run so
    # prepare-phase nodes (e.g. rest, scene_create) record their work on this turn.
    await db.commit()

    # The graph runs for every turn now — the Scene Director's pre-pass decides whether the
    # turn enters/continues combat, transitions scenes, or routes to a normal resolver.
    resolved_settings = settings_service.resolve_settings(campaign.settings)
    with recording_turn(turn.id), using_campaign_settings(resolved_settings):
        state = await turn_graph.run(
            player_input=player_input,
            session_id=session_id,
            campaign_id=db_session.campaign_id,
        )
    state["settings"] = resolved_settings
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
    """Shared post-narration epilogue: fire the LoreKeeper, Scene Director post-pass, reflector,
    and (for a long scene) the mid-scene compression summarizer."""
    schedule_lore_keeper(dm_response, campaign_id, namespace, turn_id)
    schedule_scene_director_post(session_id, turn_id)
    schedule_companion_reflector(session_id, turn_id)
    schedule_scene_summarizer(session_id)


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

    with recording_turn(turn.id), using_campaign_settings(state["settings"]):
        yield _event("turn_start", {"turn_id": str(turn.id), "intent": intent})

        if intent == "combat_action":
            combat_context, proposal = await combat_resolver.resolve(state["player_input"], str(session_id))
            if proposal is not None:
                pending: CompanionActionProposal = {
                    "kind": "companion_action",
                    "status": "pending",
                    **proposal,
                    "prior_context": combat_context,
                    "settings": state["settings"],
                }
                await turn_queries.update_turn_check(db, turn.id, check_data=pending)
                yield _event(
                    "companion_action_proposed",
                    {
                        "combatant_id": proposal["combatant_id"],
                        "proposed": {
                            "tool": "combat_resolver",
                            "args": {"input": proposal["action"]},
                            "narration": proposal["narration"],
                        },
                    },
                )
                return
            narrator = scene_narrator.run(state["player_input"], context=combat_context)
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
        # Soft pacing guidance the pre-pass computed for this turn (None outside the graph, e.g. combat).
        pre = state["scene_pre_output"]
        pacing_nudge = pre["pacing_nudge"] if pre else None

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
                pacing_nudge=pacing_nudge,
            ):
                setup_chunks.append(chunk)
                yield _event("token", {"text": chunk})
            await save_check_setup(
                db,
                turn_id=turn.id,
                check=check,
                setup_prose="".join(setup_chunks),
                settings=state["settings"],
            )
            yield _event("check_required", _check_payload(check))
            return

        # Intents that resolve to an NPC/companion line fold it into the context; narrative_action
        # uses the DM context alone.
        context = (
            _join_context(dm_context, state["npc_context"] or "")
            if intent in ("npc_dialogue", "recruit_attempt", "dismiss_companion")
            else dm_context
        )

        narrator = scene_narrator.run(
            state["player_input"],
            context=context,
            is_scene_entry=is_scene_entry,
            intro_mode=intro_mode,
            death_recovery=death_recovery,
            pacing_nudge=pacing_nudge,
        )
        async for event in _narrate(
            narrator, db, turn=turn, session_id=session_id, campaign_id=campaign_id, namespace=namespace
        ):
            yield event


async def _surface_check_discoveries(db: AsyncSession, *, turn: Turn, skill: str, total: int) -> list[str]:
    """Move any authored `hidden` detail this roll earned into the scene's discovered_facts.

    A hidden detail carries its own check + dc; the roll surfaces it when the skill matches and the
    total clears that authored dc (the discovery bar is authored, independent of the rules-lawyer's
    action dc). Runs before narration so the reveal is narratable the same turn. Returns the newly
    discovered reveal texts to feed the narrator.
    """
    scene = await scene_queries.get_scene(db, turn.scene_id)
    revealed: list[str] = []
    for detail in (scene.authored or {}).get("hidden") or []:
        if detail.get("check", "").lower() != skill.lower() or total < detail["dc"]:
            continue
        reveal = detail["reveals"]
        if reveal not in scene.discovered_facts:
            await scene_queries.mark_discovered(db, scene.id, reveal, turn_index=turn.idx)
            revealed.append(reveal)
    return revealed


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

    # Check-gated discoveries land before narration, so the reveal is narratable this same turn.
    revealed = await _surface_check_discoveries(db, turn=turn, skill=check["skill"], total=total)

    # setup_prose is written by save_check_setup before this resolve runs.
    setup_prose = check.get("setup_prose", "")
    outcome_context = (
        f"[Skill Check] {check['skill'].title()} DC {check['dc']}: "
        f"rolled {raw_roll} + {check['modifier']} = {total} — "
        f"{'SUCCESS' if success else 'FAILURE'}\n"
        f"Setup: {setup_prose}"
    )
    if revealed:
        outcome_context += "\n\nNewly discovered this check (narrate the party finding it):\n" + "\n".join(
            f"- {r}" for r in revealed
        )
    with using_campaign_settings(check.get("settings", settings_service.ResolvedCampaignSettings())):
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
        if not _post_has_effect(post):
            return

        async with db_client.get_sessionmaker()() as db, db.begin():
            session = await session_queries.get_session(db, session_id)
            scene = await scene_queries.get_current_scene(db, session.campaign_id)
            if scene is not None:
                turn = await turn_queries.get_turn(db, turn_id)
                await _apply_scene_deltas(db, scene, post, turn_idx=turn.idx)
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


def _post_has_effect(post: ScenePostOutput) -> bool:
    """Whether the post-pass changed anything worth opening a write transaction for."""
    return bool(
        post["scene_transition_push"]
        or post["act_progress"]
        or post["tension_delta"]
        or post["mood"]
        or post["discovered"]
        or post["threads_added"]
        or post["threads_resolved"]
        or post["npc_updates"]
        or post["npc_departures"]
    )


async def _apply_scene_deltas(db: AsyncSession, scene: Scene, post: ScenePostOutput, *, turn_idx: int) -> None:
    """Apply the Scene Director's post-pass scene-depth deltas via the service-only writers.

    Free-form discoveries stamp the revelation clock like check-gated ones; presence changes merge
    onto existing NPCs by id (arrivals of brand-new NPCs are not the director's job — they enter via
    dialogue or the scene builder)."""
    if post["tension_delta"]:
        await scene_queries.apply_tension(db, scene.id, post["tension_delta"])
    if post["mood"] is not None:
        await scene_queries.set_mood(db, scene.id, post["mood"])
    for fact in post["discovered"]:
        await scene_queries.mark_discovered(db, scene.id, fact, turn_index=turn_idx)
    for thread in post["threads_added"]:
        await scene_queries.add_thread(db, scene.id, thread)
    for thread in post["threads_resolved"]:
        await scene_queries.resolve_thread(db, scene.id, thread)
    if post["npc_updates"] or post["npc_departures"]:
        merged = _merge_presence(scene.npcs_present, post["npc_updates"], post["npc_departures"])
        await scene_queries.set_npcs_present(db, scene.id, merged)


def _merge_presence(current: list[NpcPresence], updates: list[NpcPresence], departures: list[str]) -> list[NpcPresence]:
    """Drop departed NPCs, then merge in-scene state shifts (doing/attentive_to/agenda) by id."""
    departed = set(departures)
    by_id: dict[str, dict[str, Any]] = {p["npc_id"]: dict(p) for p in current if p["npc_id"] not in departed}
    for upd in updates:
        present = by_id.get(upd["npc_id"])
        if present is not None:  # only shift NPCs already in the scene
            present.update({k: v for k, v in upd.items() if k != "npc_id"})
    return cast(list[NpcPresence], list(by_id.values()))


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


async def run_scene_summarizer(session_id: uuid.UUID) -> None:
    """Regenerate a long scene's `scene_progress_summary` from the turns that have fallen out of the
    verbatim window. Fire-and-forget, mirroring the LoreKeeper. No-op until the scene passes the
    compression threshold, and then only every SUMMARY_REGEN_EVERY beats — so most turns do nothing.
    """
    try:
        async with db_client.get_sessionmaker()() as db:
            session = await session_queries.get_session(db, session_id)
            scene = await scene_queries.get_current_scene(db, session.campaign_id)
            if scene is None or scene.beat_count < narrative_context.COMPRESSION_BEAT_THRESHOLD:
                return
            if scene.beat_count % narrative_context.SUMMARY_REGEN_EVERY != 0:
                return
            all_turns = await turn_queries.list_turns(db, session_id)
            older = campaign_view.scene_turn_views(all_turns, scene.id)[: -narrative_context.RECENT_TURNS]
            if not older:
                return
            scene_id = scene.id
            beat = scene.beat_count
            authored_summary = scene.summary or ""
            location_name = ""
            if scene.location_id is not None:
                location = await location_queries.get_location(db, scene.location_id)
                location_name = location.name if location else ""

        summary = await scene_summarizer.run(location_name, authored_summary, older)

        async with db_client.get_sessionmaker()() as db, db.begin():
            await scene_queries.set_progress_summary(db, scene_id, summary)
        log.info("scene_progress_summary_written", session_id=str(session_id), beat=beat)
    except Exception as exc:
        log.error("scene_summarizer_failed", error=str(exc), session_id=str(session_id))


def schedule_scene_summarizer(session_id: uuid.UUID) -> None:
    asyncio.create_task(run_scene_summarizer(session_id), name="cairn-bg")


def _companion_view(character: Character) -> dict[str, Any]:
    """The reflector's view of a companion: who they are + their current standing."""
    profile = character.narrative_profile or {}
    meta = character.companion_meta or {}
    return {
        "id": str(character.id),
        "name": character.name,
        "personality": profile.get("personality", ""),
        "prejudices": profile.get("prejudices", []),
        "personal_goal": meta.get("personal_goal", ""),
        "approval": meta.get("approval", 0),
        "mood": meta.get("mood", "content"),
    }


async def run_companion_reflector(session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
    """Judge a completed turn per-companion and apply approval deltas. Fire-and-forget.

    Reads the committed turn (player input, narration, events) and the party's companions;
    if none are present it does nothing. Deltas that name an unknown companion or move by 0
    are dropped before they reach the approval service.
    """
    try:
        async with db_client.get_sessionmaker()() as db:
            party = await character_queries.get_party_for_session(db, session_id)
            companions = [c for c in party if c.is_companion]
            if not companions:
                return
            turn = await turn_queries.get_turn(db, turn_id)
            player_input = turn.player_input
            dm_response = turn.dm_response or ""
            events = list(turn.events or [])
            views = [_companion_view(c) for c in companions]

        deltas = await companion_reflector.run(
            player_input=player_input, dm_response=dm_response, events=events, companions=views
        )
        valid_ids = {str(c.id) for c in companions}
        applied = [d for d in deltas if d["companion_id"] in valid_ids and d["delta"] != 0]
        if not applied:
            return

        async with db_client.get_sessionmaker()() as db, db.begin():
            for delta in applied:
                await companions_service.adjust_approval(
                    db,
                    character_id=uuid.UUID(delta["companion_id"]),
                    delta=delta["delta"],
                    reason=delta["reason"],
                    turn_id=turn_id,
                )
        log.info("companion_reflector_done", count=len(applied), session_id=str(session_id))
    except Exception as exc:
        log.error("companion_reflector_failed", error=str(exc), session_id=str(session_id))


def schedule_companion_reflector(session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
    asyncio.create_task(run_companion_reflector(session_id, turn_id), name="cairn-bg")


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
    settings: settings_service.ResolvedCampaignSettings,
) -> None:
    updated: CheckData = {**check, "setup_prose": setup_prose, "settings": settings}
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

    return turn, cast(CheckData, _hydrate_pause_settings(cast(CheckData, check)))


async def prepare_companion_action(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    owner_id: str,
) -> tuple[Turn, CompanionActionProposal, str]:
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign_owned_by(db, db_session.campaign_id, owner_id)
    turn = await turn_queries.get_turn(db, turn_id)
    if turn.session_id != session_id:
        raise NotFoundError(f"turn {turn_id} not found", code="turn_not_found")
    proposal = turn.check_data
    if not proposal or proposal.get("kind") != "companion_action" or proposal.get("status") != "pending":
        raise ConflictError("no pending companion action on this turn", code="no_pending_companion_action")
    return (
        turn,
        cast(CompanionActionProposal, _hydrate_pause_settings(cast(CompanionActionProposal, proposal))),
        campaign.world_bible_namespace,
    )


async def stream_companion_action(
    db: AsyncSession,
    *,
    turn: Turn,
    proposal: CompanionActionProposal,
    session_id: uuid.UUID,
    namespace: str,
    decision: str,
    override: str | None,
) -> AsyncGenerator[dict[str, Any]]:
    if decision not in {"confirm", "override"}:
        raise ValidationError("decision must be confirm or override")
    if decision == "override" and not override:
        raise ValidationError("override text is required")
    instruction = proposal["action"] if decision == "confirm" else cast(str, override)
    db_session = await session_queries.get_session(db, session_id)
    campaign = await campaign_queries.get_campaign(db, db_session.campaign_id)
    with using_campaign_settings(proposal["settings"]), recording_turn(turn.id):
        narrative_context, next_proposal = await combat_resolver.resolve(
            instruction,
            str(session_id),
            prior_context=proposal["prior_context"],
        )
        if next_proposal is not None:
            pending: CompanionActionProposal = {
                "kind": "companion_action",
                "status": "pending",
                **next_proposal,
                "prior_context": narrative_context,
                "settings": proposal["settings"],
            }
            await turn_queries.update_turn_check(db, turn.id, check_data=pending)
            yield _event(
                "companion_action_proposed",
                {
                    "combatant_id": next_proposal["combatant_id"],
                    "proposed": {
                        "tool": "combat_resolver",
                        "args": {"input": next_proposal["action"]},
                        "narration": next_proposal["narration"],
                    },
                },
            )
            return
        resolved: CompanionActionProposal = {**proposal, "status": "resolved"}
        await turn_queries.update_turn_check(db, turn.id, check_data=resolved)
        narrator = scene_narrator.run(instruction, context=narrative_context)
        async for event in _narrate(
            narrator, db, turn=turn, session_id=session_id, campaign_id=campaign.id, namespace=namespace
        ):
            yield event


def _hydrate_pause_settings(data: CheckData | CompanionActionProposal) -> CheckData | CompanionActionProposal:
    """Restore the immutable snapshot after JSONB deserialization."""
    settings = data.get("settings")
    if isinstance(settings, dict):
        return cast(
            CheckData | CompanionActionProposal,
            {**data, "settings": settings_service.ResolvedCampaignSettings.model_validate(settings)},
        )
    return data
