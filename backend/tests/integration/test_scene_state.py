"""Scene depth + pacing — the state-writer query helpers.

These lock the storage layer the resolver and Scene Director passes write through:
authored content + scene-level presence at birth, and the discovery / thread /
tension / mood / pacing mutators. All writes are service-applied (no LLM tools).
"""

import uuid

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import scenes as scene_queries
from cairn.domain.scenes import AuthoredScene, NpcPresence
from tests._factories import make_campaign


async def _scene(campaign_id: str, **kwargs) -> uuid.UUID:
    async with db_client.get_session() as db:
        scene = await scene_queries.create_scene(db, campaign_id=uuid.UUID(campaign_id), location_id=None, **kwargs)
        await db.commit()
        return scene.id


async def test_create_scene_stores_authored_and_presence(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    authored: AuthoredScene = {
        "atmosphere": "Lamplight and old smoke.",
        "surface_details": ["A locked iron chest under the desk"],
        "hidden": [{"check": "investigation", "dc": 14, "reveals": "A false drawer along the left rail"}],
        "secrets": [{"unlocked_by": "false_drawer_found", "content": "A sealed letter to Maren"}],
        "threads_in_air": ["The hooded man hasn't spoken in an hour"],
        "hooks_out": [{"hook": "letter_read", "to": "act_2_temple_lead"}],
    }
    presence: list[NpcPresence] = [
        {
            "npc_id": "old_grim",
            "doing": "polishing a glass",
            "attentive_to": ["the door"],
            "agenda": "Get them out by midnight",
        }
    ]
    scene_id = await _scene(camp["id"], authored=authored, npcs_present=presence)

    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.authored["hidden"][0]["reveals"] == "A false drawer along the left rail"
    assert scene.npcs_present[0]["agenda"] == "Get them out by midnight"
    assert scene.beat_count == 0 and scene.tension_level == 0 and scene.mood == "quiet"
    assert scene.discovered_facts == [] and scene.unresolved_threads == []


async def test_mark_discovered_stamps_revelation_turn_and_dedupes(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    scene_id = await _scene(camp["id"])
    async with db_client.get_session() as db:
        await scene_queries.mark_discovered(db, scene_id, "false_drawer_found", turn_index=7)
        await scene_queries.mark_discovered(db, scene_id, "false_drawer_found", turn_index=9)  # dupe — ignored
        await db.commit()
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.discovered_facts == ["false_drawer_found"]
    assert scene.last_revelation_at_turn == 7  # first discovery wins; dupe didn't re-stamp


async def test_threads_add_and_resolve(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    scene_id = await _scene(camp["id"])
    async with db_client.get_session() as db:
        await scene_queries.add_thread(db, scene_id, "who is the hooded man")
        await scene_queries.add_thread(db, scene_id, "why is Tomas late")
        await scene_queries.resolve_thread(db, scene_id, "who is the hooded man")
        await db.commit()
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.unresolved_threads == ["why is Tomas late"]


async def test_tension_clamps_and_mood_sets(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    scene_id = await _scene(camp["id"])
    async with db_client.get_session() as db:
        await scene_queries.apply_tension(db, scene_id, 12)  # clamps to 10
        await scene_queries.set_mood(db, scene_id, "charged")
        await db.commit()
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.tension_level == 10 and scene.mood == "charged"

    async with db_client.get_session() as db:
        await scene_queries.apply_tension(db, scene_id, -100)  # clamps to 0
        await db.commit()
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.tension_level == 0


async def test_beat_count_and_progress_summary(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    scene_id = await _scene(camp["id"])
    async with db_client.get_session() as db:
        await scene_queries.increment_beat_count(db, scene_id)
        await scene_queries.increment_beat_count(db, scene_id)
        await scene_queries.set_progress_summary(db, scene_id, "The party has searched the desk and pressed Grim once.")
        await db.commit()
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
    assert scene.beat_count == 2
    assert scene.scene_progress_summary is not None and "Grim" in scene.scene_progress_summary
