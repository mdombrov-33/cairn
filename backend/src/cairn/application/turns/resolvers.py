"""Persistence-and-agent turn workflows.

The turn graph delegates here while retaining its checkpoint state and node
names. Query modules stay the concrete persistence adapters.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import structlog

from cairn.agents import dialogue as dialogue_agent
from cairn.agents import recruiter, rules_lawyer
from cairn.application import campaign_context, recruitment
from cairn.application import npcs as npc_service
from cairn.application import rests as rest_service
from cairn.context import current_campaign_settings, current_turn_id
from cairn.db import client as db_client
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.exceptions import ConflictError
from cairn.domain.services import companions
from cairn.types import CheckData, DialogueEntity, HelperRef

if TYPE_CHECKING:
    from cairn.pipelines.turn_graph import TurnState

log = structlog.get_logger()


async def resolve_skill_check(state: TurnState) -> dict[str, Any]:
    session_id = uuid.UUID(state["session_id"])
    campaign_id = uuid.UUID(state["campaign_id"])

    async with db_client.get_session() as db:
        party = await character_queries.get_party_for_session(db, session_id)

    active = next((character for character in party if not character.is_companion), party[0] if party else None)
    party_views = [rules_lawyer.CharacterView.from_character(character) for character in party]
    active_view = rules_lawyer.CharacterView.from_character(active) if active else None
    character_context = rules_lawyer.build_character_context(active_view) if active_view else ""
    party_manifest = rules_lawyer.build_party_manifest(party_views, active.id) if active else ""
    check = await rules_lawyer.run(
        state["player_input"], character_context=character_context, party_manifest=party_manifest
    )

    check_dict: CheckData = {
        "skill": check.skill,
        "dc": check.dc,
        "modifier": check.modifier,
        "roll_type": check.roll_type,
        "status": "pending",
    }
    if check.helper:
        party_ids = {str(character.id) for character in party}
        if check.helper.character_id in party_ids:
            helper: HelperRef = {"character_id": check.helper.character_id, "name": check.helper.name}
            check_dict["helper"] = helper
        else:
            log.warning("rules_lawyer_invalid_helper", helper_id=check.helper.character_id, party_ids=list(party_ids))

    if check.loot_intent:
        async with db_client.get_session() as db:
            npc = await npc_queries.find_by_name(db, campaign_id, check.loot_intent.npc_name)
        if npc is not None:
            check_dict["loot_intent"] = {"npc_id": str(npc.id), "item_name": check.loot_intent.item_name}
        else:
            log.warning("pickpocket_npc_not_found", npc_name=check.loot_intent.npc_name)

    return {"check": check_dict}


def infer_rest_type(text: str) -> str:
    lowered = text.lower()
    long_words = ("long rest", "camp", "sleep", "night", "8 hour", "full rest", "dawn", "morning")
    return "long" if any(word in lowered for word in long_words) else "short"


async def resolve_rest(state: TurnState) -> dict[str, Any]:
    session_id = uuid.UUID(state["session_id"])
    rest_type = infer_rest_type(state["player_input"])

    async with db_client.get_session() as db:
        try:
            result = (
                await rest_service.apply_long_rest(db, session_id=session_id)
                if rest_type == "long"
                else await rest_service.apply_short_rest(db, session_id=session_id)
            )
            context = rest_service.build_rest_context(rest_type, result)
        except ConflictError as error:
            context = rest_service.build_blocked_context(error.code)

    log.info("rest_resolved", session_id=state["session_id"], rest_type=rest_type)
    return {"rest_context": context}


async def resolve_dialogue(state: TurnState) -> dict[str, Any]:
    campaign_id = uuid.UUID(state["campaign_id"])
    name = state["npc_name"] or ""

    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, campaign_id)
        location_id = scene.location_id if scene is not None else None
        npc = await npc_queries.find_by_name(db, campaign_id, name, location_id=location_id)

        if npc is None:
            companion = await character_queries.find_companion_by_name(db, campaign_id, name)
            if companion is not None:
                active_settings = current_campaign_settings.get()
                settings = active_settings if active_settings is not None else state["settings"]
                if settings.companion.dialogue != "ai":
                    return {"npc_context": f"[{companion.name}'s dialogue is player-controlled.]"}
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

            _, _, world = await campaign_context.world_chain(db, campaign_id)
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


async def resolve_recruitment(state: TurnState) -> dict[str, Any]:
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

        return {"npc_context": line}


async def resolve_dismissal(state: TurnState) -> dict[str, Any]:
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
