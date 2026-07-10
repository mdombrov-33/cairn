from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from cairn.agents import dialogue as dialogue_agent
from cairn.agents import (
    intent_router,
    recruiter,
    rules_lawyer,
    scene_builder,
    scene_director,
    scene_summarizer,
)
from cairn.context import current_turn_id
from cairn.db import client as db_client
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import NotFoundError
from cairn.domain.services import campaign_view, companions, recruitment, scene_director_context
from cairn.domain.services import npcs as npc_service
from cairn.domain.services import scenes as scene_service
from cairn.domain.services.combat import state as combat_state_service
from cairn.pipelines.checkpointer import get_checkpointer
from cairn.types import CheckData, DialogueEntity, HelperRef, ScenePreOutput

log = structlog.get_logger()


class TurnState(TypedDict):
    session_id: str
    campaign_id: str
    player_input: str
    intent: str | None
    npc_name: str | None
    check: CheckData | None  # set by resolve_skill_check; consumed by route layer
    npc_context: str | None  # set by resolve_dialogue; consumed by route layer
    rest_context: str | None  # set by resolve_rest; consumed by route layer
    scene_pre_output: ScenePreOutput | None  # set by scene_director_pre; None when combat already active
    is_scene_entry: bool  # set by scene_create; consumed by route layer for narration
    combat_just_started: bool  # set by combat_entry when init_state ran


async def _route_intent(state: TurnState) -> dict[str, Any]:
    intent, npc_name = await intent_router.run(state["player_input"])
    log.info("intent_classified", intent=intent, npc_name=npc_name)
    return {"intent": intent, "npc_name": npc_name}


async def _resolve_skill_check(state: TurnState) -> dict[str, Any]:
    session_id = uuid.UUID(state["session_id"])
    campaign_id = uuid.UUID(state["campaign_id"])

    async with db_client.get_session() as db:
        party = await character_queries.get_party_for_session(db, session_id)

    # Active character: prefer the PC (non-companion); fall back to first available.
    active = next((c for c in party if not c.is_companion), party[0] if party else None)

    party_views = [rules_lawyer.CharacterView.from_character(c) for c in party]
    active_view = rules_lawyer.CharacterView.from_character(active) if active else None

    character_context = rules_lawyer.build_character_context(active_view) if active_view else ""
    party_manifest = rules_lawyer.build_party_manifest(party_views, active.id) if active else ""

    check = await rules_lawyer.run(
        state["player_input"],
        character_context=character_context,
        party_manifest=party_manifest,
    )

    check_dict: CheckData = {
        "skill": check.skill,
        "dc": check.dc,
        "modifier": check.modifier,
        "roll_type": check.roll_type,
        "status": "pending",
    }
    if check.helper:
        party_ids = {str(c.id) for c in party}
        if check.helper.character_id in party_ids:
            helper: HelperRef = {
                "character_id": check.helper.character_id,
                "name": check.helper.name,
            }
            check_dict["helper"] = helper
        else:
            log.warning(
                "rules_lawyer_invalid_helper",
                helper_id=check.helper.character_id,
                party_ids=list(party_ids),
            )

    if check.loot_intent:
        async with db_client.get_session() as db:
            npc = await npc_queries.find_by_name(db, campaign_id, check.loot_intent.npc_name)
        if npc is not None:
            check_dict["loot_intent"] = {"npc_id": str(npc.id), "item_name": check.loot_intent.item_name}
        else:
            log.warning("pickpocket_npc_not_found", npc_name=check.loot_intent.npc_name)

    return {"check": check_dict}


def _infer_rest_type(text: str) -> str:
    lowered = text.lower()
    long_words = ("long rest", "camp", "sleep", "night", "8 hour", "full rest", "dawn", "morning")
    return "long" if any(w in lowered for w in long_words) else "short"


async def _resolve_rest(state: TurnState) -> dict[str, Any]:
    from cairn.domain.exceptions import ConflictError
    from cairn.domain.services import rests as rest_service

    session_id = uuid.UUID(state["session_id"])
    rest_type = _infer_rest_type(state["player_input"])

    async with db_client.get_session() as db:
        try:
            if rest_type == "long":
                result = await rest_service.apply_long_rest(db, session_id=session_id)
            else:
                result = await rest_service.apply_short_rest(db, session_id=session_id)
            context = rest_service.build_rest_context(rest_type, result)
        except ConflictError as e:
            context = rest_service.build_blocked_context(e.code)

    log.info("rest_resolved", session_id=state["session_id"], rest_type=rest_type)
    return {"rest_context": context}


async def _resolve_dialogue(state: TurnState) -> dict[str, Any]:
    campaign_id = uuid.UUID(state["campaign_id"])
    name = state["npc_name"] or ""

    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, campaign_id)
        location_id = scene.location_id if scene is not None else None
        npc = await npc_queries.find_by_name(db, campaign_id, name, location_id=location_id)

        if npc is None:
            # The player may be addressing a party companion (a Character, not an NPC).
            companion = await character_queries.find_companion_by_name(db, campaign_id, name)
            if companion is not None:
                meta = companion.companion_meta or {}
                comp_entity: DialogueEntity = {
                    "name": companion.name,
                    "profile": companion.narrative_profile,
                    "disposition": "friendly",
                    "approval_band": companions.approval_band(meta.get("approval", 0)),
                    "mood": meta.get("mood", "content"),
                }
                result = await dialogue_agent.run(state["player_input"], comp_entity)
                return {"npc_context": f'[{companion.name}]: "{result.dialogue}"'}

            # No one by that name exists yet: instantiate an authored world figure the party has
            # now reached, else the builder generates a background walk-on on the spot.
            _, _, world = await campaign_view.world_chain(db, campaign_id)
            npc = await npc_service.instantiate_world_cast(db, campaign_id=campaign_id, world_key=world.key, name=name)
            if npc is None:
                npc = await npc_service.generate_background_npc(db, campaign_id=campaign_id, name=name, scene=scene)

        entity: DialogueEntity = {
            "name": npc.name,
            "profile": npc.narrative_profile,
            "disposition": npc.disposition,
        }
        result = await dialogue_agent.run(state["player_input"], entity)
        if result.disposition_change and result.disposition_change != npc.disposition:
            await _record_disposition_change(db, campaign_id, npc, old=npc.disposition, new=result.disposition_change)
            npc.disposition = result.disposition_change
        await npc_service.record_dialogue_exchange(db, npc=npc, scene=scene)
        await db.commit()
        return {"npc_context": f'[{npc.name}]: "{result.dialogue}"'}


async def _record_disposition_change(db: Any, campaign_id: uuid.UUID, npc: Any, *, old: str, new: str) -> None:
    """Log an NPC's disposition shift to the world bible so it becomes canon the DM remembers
    (e.g. "old_grim disposition: neutral → hostile"). Deterministic — the mechanical flip is
    recorded here, not left for the LLM LoreKeeper to infer from prose."""
    campaign = await campaign_queries.get_campaign(db, campaign_id)
    await world_bible_queries.upsert_entry(
        db,
        campaign_id=campaign_id,
        namespace=campaign.world_bible_namespace,
        type_="RELATIONSHIP",
        key=f"{npc.name} — disposition toward the party",
        content=f"{npc.name}'s disposition toward the party is now {new} (was {old}).",
        source_turn_id=current_turn_id.get(),
    )


async def _resolve_recruitment(state: TurnState) -> dict[str, Any]:
    """Adjudicate a bid to recruit an NPC. The `recruiter` decides in-character; on accept the NPC
    converts to a party companion (soft-capped), on conditional the ask is recorded for later."""
    campaign_id = uuid.UUID(state["campaign_id"])
    name = state["npc_name"] or ""

    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, campaign_id)
        location_id = scene.location_id if scene is not None else None
        npc = await npc_queries.find_by_name(db, campaign_id, name, location_id=location_id)
        if npc is None:
            return {"npc_context": f'[No one here answers to "{name}".]'}
        if not recruitment.is_recruitable(npc):
            return {"npc_context": f"[{npc.name} is not someone who would throw in with the party.]"}

        decision = await recruiter.run(
            state["player_input"],
            profile=npc.narrative_profile,
            disposition=npc.disposition,
            context=(scene.summary if scene is not None else "") or "",
            recruitment_condition=npc.recruitment_condition,
        )
        line = f'[{npc.name}]: "{decision.line}"'

        if decision.decision == "accept":
            if await recruitment.is_party_full(db, campaign_id):
                return {
                    "npc_context": f"{line}\n[The party is already "
                    f"{recruitment.MAX_ACTIVE_COMPANIONS} strong — someone must step aside first.]"
                }
            campaign = await campaign_queries.get_campaign(db, campaign_id)
            await recruitment.recruit(db, npc=npc, owner_id=campaign.owner_id)
            await db.commit()
            log.info("companion_recruited", campaign_id=state["campaign_id"], name=npc.name)
            return {"npc_context": f"{line}\n[{npc.name} joins the party.]"}

        if decision.decision == "conditional":
            npc.recruitment_condition = decision.condition or None
            await db.commit()
            return {"npc_context": line}

        return {"npc_context": line}  # refuse — stays an NPC, re-attemptable


async def _resolve_dismissal(state: TurnState) -> dict[str, Any]:
    """Part ways with a party companion: it converts back into an NPC at the current location."""
    campaign_id = uuid.UUID(state["campaign_id"])
    name = state["npc_name"] or ""

    async with db_client.get_session() as db:
        companion = await character_queries.find_companion_by_name(db, campaign_id, name)
        if companion is None:
            return {"npc_context": f'[No companion named "{name}" travels with the party.]'}
        scene = await scene_queries.get_current_scene(db, campaign_id)
        location_id = scene.location_id if scene is not None else None
        npc = await recruitment.dismiss(db, character=companion, location_id=location_id)
        await db.commit()
        log.info("companion_dismissed", campaign_id=state["campaign_id"], name=npc.name)
        return {"npc_context": f"[{npc.name} parts ways with the party.]"}


async def _scene_director_pre(state: TurnState) -> dict[str, Any]:
    """Meta-routing pass that runs before every turn.

    Skips the LLM call entirely when combat is already active (the director's pulls are
    meaningless mid-combat). A pending scene transition from a prior post-pass push is
    folded into this turn's pull so the routing conditional stays purely state-driven.
    """
    session_id = uuid.UUID(state["session_id"])
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, session_id)
        if session.combat_active:
            return {"scene_pre_output": None}
        pending = session.pending_transition
        context = await scene_director_context.build_pre_input_context(db, session_id, state["player_input"])

    pre = await scene_director.run_pre(context)
    if pre["scene_transition_pull"] is None and pending is not None:
        pre = {
            "combat_trigger": pre["combat_trigger"],
            "scene_transition_pull": pending,
            "pacing_nudge": pre["pacing_nudge"],
        }
    return {"scene_pre_output": pre}


def _after_pre(state: TurnState) -> str:
    pre = state["scene_pre_output"]
    if pre is None:
        return "combat_terminus"  # combat already active — straight to resolution
    trigger = pre["combat_trigger"]
    if trigger and trigger["hostile_npc_ids"]:
        return "combat_entry"
    if pre["scene_transition_pull"] is not None:
        return "scene_create"
    return "route_intent"


async def _combat_entry(state: TurnState) -> dict[str, Any]:
    """Initialize combat from the Scene Director's detected hostile NPCs.

    Invalid or out-of-campaign ids are dropped; if nothing valid remains, the turn falls
    through to normal intent routing instead of starting an empty combat.
    """
    pre = state["scene_pre_output"]
    trigger = pre["combat_trigger"] if pre else None
    session_id = uuid.UUID(state["session_id"])
    campaign_id = uuid.UUID(state["campaign_id"])

    enemies: list[dict] = []
    async with db_client.get_session() as db:
        for raw_id in trigger["hostile_npc_ids"] if trigger else []:
            try:
                npc = await npc_queries.get_npc(db, uuid.UUID(raw_id))
            except NotFoundError, ValueError:
                log.warning("combat_trigger_invalid_npc", npc_id=raw_id)
                continue
            if npc.campaign_id != campaign_id:
                log.warning("combat_trigger_foreign_npc", npc_id=raw_id)
                continue
            enemies.append({"type": "npc", "id": str(npc.id)})

        if not enemies:
            return {"combat_just_started": False}
        await combat_state_service.init_state(db, session_id, enemies)

    log.info("combat_entered", session_id=state["session_id"], enemy_count=len(enemies))
    return {"combat_just_started": True}


def _after_combat_entry(state: TurnState) -> str:
    return "combat_terminus" if state["combat_just_started"] else "route_intent"


async def _combat_terminus(state: TurnState) -> dict[str, Any]:
    """Terminal for combat turns — the route layer streams combat_resolver on this intent."""
    return {"intent": "combat_action"}


async def _build_unauthored_scene(db: Any, campaign: Any, template: Any, location: Any) -> None:
    """First entry to a location the world never authored: generate a layered scene once and
    persist it to `Location.authored_scene`, so every later entry re-enters the authored path with
    no regeneration. Parse-fail safe — on failure the location stays thin and open_scene falls back
    to a roster-only scene."""
    act = campaign_view.act_at(template, campaign.current_act_index) or {"title": "", "premise": ""}
    npcs = await npc_queries.list_by_location(db, campaign.id, location.id)
    roster = [{"name": n.name, "role": n.class_ or "", "disposition": n.disposition} for n in npcs]
    raw = await scene_builder.build(
        location_name=location.name,
        location_description=location.description,
        act_title=act["title"],
        act_premise=act["premise"],
        time_label="",
        roster=roster,
    )
    if raw:
        location.authored_scene = raw
        await db.flush()
        log.info("scene_built", location=location.name)


async def _scene_create(state: TurnState) -> dict[str, Any]:
    """Apply a scene transition: summarize and close the old scene, open the new one.

    The current turn is re-stamped onto the new scene so its narration is recorded there.
    A transition to an unknown location is dropped (pending_transition cleared) rather than
    stranding the session.
    """
    session_id = uuid.UUID(state["session_id"])
    campaign_id = uuid.UUID(state["campaign_id"])
    pre = state["scene_pre_output"]
    transition = pre["scene_transition_pull"] if pre else None
    if transition is None:
        return {"is_scene_entry": False}

    try:
        target_location_id: uuid.UUID | None = uuid.UUID(transition["to_location_id"])
    except ValueError, TypeError:
        target_location_id = None

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, session_id)
        location = await location_queries.get_location(db, target_location_id) if target_location_id else None
        if location is None:
            log.warning("scene_transition_invalid_location", to_location_id=transition["to_location_id"])
            session.pending_transition = None
            await db.commit()
            return {"is_scene_entry": False}

        old_scene = await scene_queries.get_current_scene(db, campaign_id)
        if old_scene is not None:
            old_loc_name = ""
            if old_scene.location_id is not None:
                old_loc = await location_queries.get_location(db, old_scene.location_id)
                old_loc_name = old_loc.name if old_loc else ""
            all_turns = await turn_queries.list_turns(db, session_id)
            scene_turns = campaign_view.scene_turn_views(all_turns, old_scene.id)
            summary = await scene_summarizer.run(old_loc_name, old_scene.summary or "", scene_turns)
            await scene_queries.close_scene(db, old_scene.id, summary=summary, ended_at=datetime.now(UTC))

        campaign, template, _ = await campaign_view.world_chain(db, campaign_id)
        if not location.authored_scene:
            await _build_unauthored_scene(db, campaign, template, location)
        new_scene = await scene_service.open_scene(
            db,
            campaign_id=campaign_id,
            location=location,
            act_index=campaign.current_act_index,
        )
        turn_id = current_turn_id.get()
        if turn_id is not None:
            await turn_queries.set_turn_scene(db, turn_id, new_scene.id)
        session.pending_transition = None
        await db.commit()

    log.info("scene_created", session_id=state["session_id"], location=location.name)
    return {"is_scene_entry": True}


def _pick_node(state: TurnState) -> str:
    intent = state["intent"]
    if intent == "skill_check":
        return "resolve_skill_check"
    if intent == "npc_dialogue":
        return "resolve_dialogue"
    if intent == "rest_action":
        return "resolve_rest"
    if intent == "recruit_attempt":
        return "resolve_recruitment"
    if intent == "dismiss_companion":
        return "resolve_dismissal"
    return END


@lru_cache(maxsize=1)
def _get_graph() -> Any:
    builder: StateGraph = StateGraph(TurnState)
    builder.add_node("scene_director_pre", _scene_director_pre)
    builder.add_node("combat_entry", _combat_entry)
    builder.add_node("combat_terminus", _combat_terminus)
    builder.add_node("scene_create", _scene_create)
    builder.add_node("route_intent", _route_intent)
    builder.add_node("resolve_skill_check", _resolve_skill_check)
    builder.add_node("resolve_dialogue", _resolve_dialogue)
    builder.add_node("resolve_rest", _resolve_rest)
    builder.add_node("resolve_recruitment", _resolve_recruitment)
    builder.add_node("resolve_dismissal", _resolve_dismissal)

    builder.add_edge(START, "scene_director_pre")
    builder.add_conditional_edges(
        "scene_director_pre",
        _after_pre,
        ["combat_terminus", "combat_entry", "scene_create", "route_intent"],
    )
    builder.add_conditional_edges("combat_entry", _after_combat_entry, ["combat_terminus", "route_intent"])
    builder.add_edge("combat_terminus", END)
    builder.add_edge("scene_create", "route_intent")
    builder.add_conditional_edges("route_intent", _pick_node)
    builder.add_edge("resolve_skill_check", END)
    builder.add_edge("resolve_dialogue", END)
    builder.add_edge("resolve_rest", END)
    builder.add_edge("resolve_recruitment", END)
    builder.add_edge("resolve_dismissal", END)

    return builder.compile(checkpointer=get_checkpointer())


async def run(
    player_input: str,
    session_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> TurnState:
    graph = _get_graph()
    config = {"configurable": {"thread_id": str(session_id)}}
    result = await graph.ainvoke(
        TurnState(
            session_id=str(session_id),
            campaign_id=str(campaign_id),
            player_input=player_input,
            intent=None,
            npc_name=None,
            check=None,
            npc_context=None,
            rest_context=None,
            scene_pre_output=None,
            is_scene_entry=False,
            combat_just_started=False,
        ),
        config=config,
    )
    return result
