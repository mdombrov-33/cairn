"""Direct tests for Stage 3d DM-polish helpers that the integration LLM fake can't exercise:
intro-mode onboarding and the Scene Director time-advance double-count guard.
"""

import uuid

from httpx import AsyncClient

from cairn.application import narrative_context
from cairn.application.turns import service as turns_service
from cairn.application.turns.epilogue import _apply_director_time
from cairn.db import client as db_client
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from tests._factories import make_campaign, make_character, make_session


async def _seed(client: AsyncClient) -> tuple[str, str]:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    return camp["id"], sess["id"]


async def _add_turns(campaign_id: str, session_id: str, n: int) -> uuid.UUID:
    """Append n turns to the session; returns the last turn's id."""
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert scene is not None
        last_id = None
        for i in range(n):
            turn = await turn_queries.create_turn(
                db, session_id=uuid.UUID(session_id), scene_id=scene.id, idx=i, player_input="go"
            )
            last_id = turn.id
        await db.commit()
    assert last_id is not None
    return last_id


# --- intro_mode (Verify #15) -----------------------------------------------------


async def test_intro_mode_true_for_fresh_custom_pc(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    async with db_client.get_session() as db:
        assert await narrative_context.is_intro_mode(db, uuid.UUID(session_id)) is True


async def test_intro_mode_holds_through_third_turn(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    await _add_turns(campaign_id, session_id, 3)
    async with db_client.get_session() as db:
        assert await narrative_context.is_intro_mode(db, uuid.UUID(session_id)) is True


async def test_intro_mode_off_from_fourth_turn(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    await _add_turns(campaign_id, session_id, 4)
    async with db_client.get_session() as db:
        assert await narrative_context.is_intro_mode(db, uuid.UUID(session_id)) is False


# --- time advance double-count guard (Verify #18/#19) ----------------------------


async def test_director_time_advances_clock_and_records_event(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    turn_id = await _add_turns(campaign_id, session_id, 1)

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        before = session.in_game_hours_elapsed
        await _apply_director_time(db, session, turn_id, 6)
        await db.commit()

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        assert session.in_game_hours_elapsed == before + 6
        turn = await turn_queries.get_turn(db, turn_id)
        assert any(e["type"] == "time_advanced" for e in (turn.events or []))


async def test_director_time_skips_when_rest_already_advanced(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    turn_id = await _add_turns(campaign_id, session_id, 1)

    # Simulate a rest having advanced time on this same turn.
    async with db_client.get_session() as db:
        await turn_queries.append_event(db, turn_id, {"type": "time_advanced", "source": "long_rest", "hours": 8})
        await db.commit()

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        before = session.in_game_hours_elapsed
        await _apply_director_time(db, session, turn_id, 6)
        await db.commit()

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        assert session.in_game_hours_elapsed == before


# --- death recovery handoff (Verify #10) -----------------------------------------


async def test_consume_death_recovery_fires_once(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    sid = uuid.UUID(session_id)

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, sid)
        session.pending_recovery = {"reason": "slain by goblins", "prior_events_summary": "the ambush"}
        await db.commit()

    async with db_client.get_session() as db:
        assert await turns_service.consume_death_recovery(db, session_id=sid) is True
        await db.commit()

    # Cleared — a second turn does not re-narrate the wake-up.
    async with db_client.get_session() as db:
        assert await turns_service.consume_death_recovery(db, session_id=sid) is False
