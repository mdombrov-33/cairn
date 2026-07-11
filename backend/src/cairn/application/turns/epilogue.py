"""Post-narration work that must not delay the foreground turn stream."""

import asyncio
import uuid
from collections.abc import Coroutine
from typing import Any, cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from cairn.agents import companion_reflector, lore_keeper, scene_director, scene_summarizer
from cairn.application import companions as companions_service
from cairn.application import narrative_context, scene_director_context
from cairn.application import time as time_service
from cairn.context import recording_turn
from cairn.db import client as db_client
from cairn.db.models.character import Character
from cairn.db.models.scene import Scene
from cairn.db.models.session import Session
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import locations as location_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.db.queries import world_bible as world_bible_queries
from cairn.domain.services import campaign_view
from cairn.types import NpcPresence, ScenePostOutput

log = structlog.get_logger()


class PostTurnEpilogue:
    """Run and supervise all in-process work triggered after a narrated turn.

    ``schedule`` is deliberately non-blocking: task lifecycle, failure isolation, and shutdown
    stay here so foreground turn handling only knows that its epilogue was scheduled.
    """

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def schedule(
        self,
        dm_response: str,
        *,
        session_id: uuid.UUID,
        campaign_id: uuid.UUID,
        namespace: str,
        turn_id: uuid.UUID,
    ) -> None:
        self._spawn("lore_keeper", self._run_lore_keeper(dm_response, campaign_id, namespace, turn_id))
        self._spawn("scene_director_post", self._run_scene_director_post(session_id, turn_id))
        self._spawn("companion_reflector", self._run_companion_reflector(session_id, turn_id))
        self._spawn("scene_summarizer", self._run_scene_summarizer(session_id))

    async def shutdown(self) -> None:
        """Cancel and await any epilogue work still running at application shutdown."""
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _spawn(self, name: str, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(self._isolate_failure(name, work), name="cairn-bg")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _isolate_failure(self, name: str, work: Coroutine[Any, Any, None]) -> None:
        try:
            await work
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("post_turn_task_failed", task=name)

    async def _run_lore_keeper(
        self, dm_response: str, campaign_id: uuid.UUID, namespace: str, source_turn_id: uuid.UUID
    ) -> None:
        async with db_client.get_sessionmaker()() as session:
            existing = await world_bible_queries.list_by_campaign(session, campaign_id)
        entries = await lore_keeper.run(dm_response, existing_keys=[entry.key for entry in existing])
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

    async def _run_scene_director_post(self, session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
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

    async def _run_scene_summarizer(self, session_id: uuid.UUID) -> None:
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

    async def _run_companion_reflector(self, session_id: uuid.UUID, turn_id: uuid.UUID) -> None:
        async with db_client.get_sessionmaker()() as db:
            party = await character_queries.get_party_for_session(db, session_id)
            companions = [character for character in party if character.is_companion]
            if not companions:
                return
            turn = await turn_queries.get_turn(db, turn_id)
            views = [_companion_view(character) for character in companions]
            player_input = turn.player_input
            dm_response = turn.dm_response or ""
            events = list(turn.events or [])
        deltas = await companion_reflector.run(
            player_input=player_input, dm_response=dm_response, events=events, companions=views
        )
        valid_ids = {str(character.id) for character in companions}
        applied = [delta for delta in deltas if delta["companion_id"] in valid_ids and delta["delta"] != 0]
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


def _post_has_effect(post: ScenePostOutput) -> bool:
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
    departed = set(departures)
    by_id: dict[str, dict[str, Any]] = {
        entry["npc_id"]: dict(entry) for entry in current if entry["npc_id"] not in departed
    }
    for update in updates:
        present = by_id.get(update["npc_id"])
        if present is not None:
            present.update({key: value for key, value in update.items() if key != "npc_id"})
    return cast(list[NpcPresence], list(by_id.values()))


async def _apply_director_time(db: AsyncSession, session: Session, turn_id: uuid.UUID, hours: int) -> None:
    turn = await turn_queries.get_turn(db, turn_id)
    if any(event.get("type") == "time_advanced" for event in (turn.events or [])):
        log.info("scene_director_time_skip_double_count", turn_id=str(turn_id), hours=hours)
        return
    with recording_turn(turn_id):
        await time_service.advance_time(db, session, hours=hours, source="scene_director")


def _companion_view(character: Character) -> dict[str, Any]:
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


post_turn_epilogue = PostTurnEpilogue()
