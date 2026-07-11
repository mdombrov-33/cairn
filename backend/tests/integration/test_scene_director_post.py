"""Scene Director post-pass — mechanical beat count + applied scene-depth deltas.

The pre/post LLM passes aren't exercised here (the integration fake short-circuits the graph);
these lock the wiring around them: every turn bumps `beat_count`, and a post-pass decision is
translated into the service-only scene writers (tension, mood, discoveries, threads, presence).
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.application.turns.epilogue import PostTurnEpilogue
from cairn.db import client as db_client
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import turns as turn_queries
from cairn.types import NpcPresence, ScenePostOutput
from tests._factories import make_campaign, make_session


def _post(**overrides) -> ScenePostOutput:
    base: ScenePostOutput = {
        "combat_ended": False,
        "scene_transition_push": None,
        "time_advance_hours": 0,
        "act_progress": False,
        "tension_delta": 0,
        "mood": None,
        "discovered": [],
        "threads_added": [],
        "threads_resolved": [],
        "npc_updates": [],
        "npc_departures": [],
    }
    return {**base, **overrides}  # type: ignore[typeddict-item]


async def _submit_turn(client: AsyncClient, session_id: str, text: str = "I look around") -> None:
    r = await client.post(
        f"/v1/sessions/{session_id}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": text},
    )
    assert r.status_code == 201


async def _current_scene(campaign_id: str):
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert scene is not None
        return scene


async def _seed_turn(campaign_id: str, session_id: str) -> uuid.UUID:
    """A completed turn on the current scene the post-pass can observe."""
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert scene is not None
        turn = await turn_queries.create_turn(
            db, session_id=uuid.UUID(session_id), scene_id=scene.id, idx=0, player_input="I probe the room"
        )
        turn.dm_response = "The room answers with dust and silence."
        await db.commit()
        return turn.id


async def _run_post(session_id: str, turn_id: uuid.UUID, post: ScenePostOutput) -> None:
    with patch("cairn.application.turns.epilogue.scene_director.run_post", new=AsyncMock(return_value=post)):
        await PostTurnEpilogue()._run_scene_director_post(uuid.UUID(session_id), turn_id)


# --- beat_count -------------------------------------------------------------------


async def test_each_turn_bumps_beat_count(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    assert (await _current_scene(camp["id"])).beat_count == 0
    await _submit_turn(client, sess["id"])
    await _submit_turn(client, sess["id"])

    assert (await _current_scene(camp["id"])).beat_count == 2


# --- post-pass applied deltas -----------------------------------------------------


async def test_post_pass_writes_tension_mood_discovery_thread(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    turn_id = await _seed_turn(camp["id"], sess["id"])

    await _run_post(
        sess["id"],
        turn_id,
        _post(
            tension_delta=3,
            mood="charged",
            discovered=["A cold draft leaks from behind the north wall"],
            threads_added=["Who left the cellar door open?"],
        ),
    )

    scene = await _current_scene(camp["id"])
    assert scene.tension_level == 3
    assert scene.mood == "charged"
    assert any("cold draft" in f for f in scene.discovered_facts)
    assert scene.last_revelation_at_turn == 0  # free-form discovery stamps the stall clock too
    assert "Who left the cellar door open?" in scene.unresolved_threads


async def test_post_pass_resolves_open_thread(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    turn_id = await _seed_turn(camp["id"], sess["id"])

    scene = await _current_scene(camp["id"])
    async with db_client.get_session() as db:
        await scene_queries.add_thread(db, scene.id, "The stranger won't give his name")
        await db.commit()

    await _run_post(sess["id"], turn_id, _post(threads_resolved=["The stranger won't give his name"]))

    scene = await _current_scene(camp["id"])
    assert scene.unresolved_threads == []


async def test_post_pass_merges_presence_and_removes_departed(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    turn_id = await _seed_turn(camp["id"], sess["id"])

    scene = await _current_scene(camp["id"])
    seeded: list[NpcPresence] = [
        {"npc_id": "grim", "doing": "polishing a glass", "agenda": "get them out by midnight"},
        {"npc_id": "harl", "doing": "counting coppers"},
    ]
    async with db_client.get_session() as db:
        await scene_queries.set_npcs_present(db, scene.id, seeded)
        await db.commit()

    await _run_post(
        sess["id"],
        turn_id,
        _post(
            npc_updates=[{"npc_id": "grim", "agenda": "draw steel if pressed"}],
            npc_departures=["harl"],
        ),
    )

    scene = await _current_scene(camp["id"])
    by_id = {p["npc_id"]: p for p in scene.npcs_present}
    assert "harl" not in by_id  # departed
    assert by_id["grim"]["agenda"] == "draw steel if pressed"  # merged
    assert by_id["grim"]["doing"] == "polishing a glass"  # untouched field preserved


async def test_post_pass_noop_leaves_scene_untouched(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    turn_id = await _seed_turn(camp["id"], sess["id"])

    await _run_post(sess["id"], turn_id, _post())

    scene = await _current_scene(camp["id"])
    assert scene.tension_level == 0
    assert scene.mood == "quiet"
    assert scene.discovered_facts == []
    assert scene.last_revelation_at_turn is None
