"""Mid-scene compression — Layer 7 of the DM context is scene-scoped and beat-aware.

A short scene rides along verbatim. Once it runs past the compression threshold, the older turns
collapse into `scene_progress_summary` (an "Earlier this scene" section) and only the last
RECENT_TURNS stay verbatim, so the prompt stays bounded however long the scene runs.
"""

import uuid

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.services import narrative_context
from cairn.domain.services.narrative_context import COMPRESSION_BEAT_THRESHOLD, RECENT_TURNS
from tests._factories import make_campaign, make_session


async def _seed_scene_turns(campaign_id: uuid.UUID, session_id: uuid.UUID, *, count: int) -> uuid.UUID:
    """Attach `count` completed turns to the campaign's current scene. Returns the scene id."""
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, campaign_id)
        assert scene is not None
        for i in range(count):
            turn = await turn_queries.create_turn(
                db, session_id=session_id, scene_id=scene.id, idx=i, player_input=f"turn-{i}"
            )
            await turn_queries.update_turn_response(db, turn.id, dm_response=f"response-{i}")
        await db.commit()
        return scene.id


async def _set_pacing(scene_id: uuid.UUID, *, beat_count: int, progress_summary: str | None) -> None:
    async with db_client.get_session() as db:
        scene = await scene_queries.get_scene(db, scene_id)
        scene.beat_count = beat_count
        scene.scene_progress_summary = progress_summary
        await db.commit()


async def test_short_scene_rides_verbatim(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    campaign_id, session_id = uuid.UUID(camp["id"]), uuid.UUID(sess["id"])

    scene_id = await _seed_scene_turns(campaign_id, session_id, count=4)
    await _set_pacing(scene_id, beat_count=4, progress_summary="SHOULD-NOT-APPEAR")

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, session_id)

    # Under the threshold every turn is verbatim and the summary is not consulted.
    assert "turn-0" in context and "turn-3" in context
    assert "Earlier this scene" not in context
    assert "SHOULD-NOT-APPEAR" not in context


async def test_long_scene_compresses_older_turns(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    campaign_id, session_id = uuid.UUID(camp["id"]), uuid.UUID(sess["id"])

    count = COMPRESSION_BEAT_THRESHOLD + 3  # 11 turns, window keeps the last RECENT_TURNS
    scene_id = await _seed_scene_turns(campaign_id, session_id, count=count)
    await _set_pacing(scene_id, beat_count=count + 1, progress_summary="OLDER-BEATS-SUMMARY")

    async with db_client.get_session() as db:
        context = await narrative_context.build_dm_context(db, session_id)

    # The summary carries the older turns; only the last RECENT_TURNS ride along verbatim.
    assert "Earlier this scene" in context
    assert "OLDER-BEATS-SUMMARY" in context
    assert f"turn-{count - 1}" in context  # most recent — verbatim
    assert "turn-0" not in context  # oldest — fell out of the window, lives only in the summary
    oldest_verbatim = count - RECENT_TURNS
    assert f"turn-{oldest_verbatim - 1}" not in context
    assert f"turn-{oldest_verbatim}" in context
