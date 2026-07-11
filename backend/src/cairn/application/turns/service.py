import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import (
    combat_resolver,
    scene_narrator,
)
from cairn.application import loot as loot_service
from cairn.application import narrative_context
from cairn.application.turns.epilogue import post_turn_epilogue
from cairn.application.turns.types import CheckData, CompanionActionProposal, LootIntent
from cairn.context import recording_turn, using_campaign_settings
from cairn.db.models.character import Character
from cairn.db.models.turn import Turn
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.exceptions import AgentError, ConflictError, NotFoundError, ValidationError
from cairn.domain.services import settings as settings_service
from cairn.pipelines import turn_graph
from cairn.pipelines.turn_graph import TurnState

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
    post_turn_epilogue.schedule(
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
        post_turn_epilogue.schedule(
            dm_response, session_id=session_id, campaign_id=campaign_id, namespace=namespace, turn_id=turn.id
        )


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
