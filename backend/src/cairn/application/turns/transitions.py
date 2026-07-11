"""Scene and combat-entry workflows delegated from the turn graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from cairn.agents import scene_builder, scene_director, scene_summarizer
from cairn.application import campaign_context, scene_director_context
from cairn.application import scenes as scene_service
from cairn.context import current_turn_id
from cairn.db import client as db_client
from cairn.db.queries import locations as location_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.exceptions import NotFoundError
from cairn.domain.services import campaign_view
from cairn.domain.services.combat import state as combat_state_service

if TYPE_CHECKING:
    from cairn.pipelines.turn_graph import TurnState

log = structlog.get_logger()


async def scene_director_pre(state: TurnState) -> dict[str, Any]:
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


async def combat_entry(state: TurnState) -> dict[str, Any]:
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


async def _build_unauthored_scene(db: Any, campaign: Any, template: Any, location: Any) -> None:
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


async def scene_create(state: TurnState) -> dict[str, Any]:
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

        campaign, template, _ = await campaign_context.world_chain(db, campaign_id)
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
