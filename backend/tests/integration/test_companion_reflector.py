"""Integration tests for run_companion_reflector — the post-turn approval wiring.

The reflector *agent* (the LLM judgment) is stubbed; these lock the service around it:
the no-companion guard, that returned deltas are applied via the approval service, and that
unknown-id / zero deltas are dropped before they reach it.
"""

import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.application.turns import service as turns_service
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import turns as turn_queries
from tests._factories import DEFAULT_CHARACTER, make_campaign, make_character, make_session

_PROFILE = {"name": "Bram", "personality": "Loyal and blunt.", "voice": {"accent": "rough"}}


async def _seed_turn(client: AsyncClient) -> tuple[str, uuid.UUID]:
    """A campaign + session with one committed turn. Returns (campaign_id, turn_id)."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])  # the PC
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(camp["id"]))
        assert scene is not None
        turn = await turn_queries.create_turn(
            db, session_id=uuid.UUID(sess["id"]), scene_id=scene.id, idx=0, player_input="I spare the deserter"
        )
        await turn_queries.update_turn_response(db, turn.id, dm_response="You lower your blade.")
        await db.commit()
        turn_id = turn.id
    return sess["id"], turn_id


async def _add_companion(client: AsyncClient, campaign_id: str) -> uuid.UUID:
    comp = await make_character(
        client,
        campaign_id,
        **{**DEFAULT_CHARACTER, "name": "Bram", "is_companion": True, "narrative_profile": _PROFILE},
    )
    return uuid.UUID(comp["id"])


async def test_no_companion_present_is_a_noop(client: AsyncClient) -> None:
    session_id, turn_id = await _seed_turn(client)

    with patch("cairn.agents.companion_reflector.run", new=AsyncMock()) as mock_run:
        await turns_service.run_companion_reflector(uuid.UUID(session_id), turn_id)

    mock_run.assert_not_awaited()  # guarded out before the LLM is ever called


async def test_returned_delta_is_applied_to_approval(client: AsyncClient) -> None:
    # Session must belong to the same campaign as the companion, so seed the campaign first.
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    cid = await _add_companion(client, camp["id"])
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(camp["id"]))
        assert scene is not None
        turn = await turn_queries.create_turn(
            db, session_id=uuid.UUID(sess["id"]), scene_id=scene.id, idx=0, player_input="I spare the deserter"
        )
        await turn_queries.update_turn_response(db, turn.id, dm_response="You lower your blade.")
        await db.commit()
        turn_id = turn.id

    deltas = [{"companion_id": str(cid), "delta": 18, "reason": "Spared the deserter"}]
    with patch("cairn.agents.companion_reflector.run", new=AsyncMock(return_value=deltas)):
        await turns_service.run_companion_reflector(uuid.UUID(sess["id"]), turn_id)

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
    assert char.companion_meta is not None
    assert char.companion_meta["approval"] == 18
    assert char.companion_meta["approval_log"][-1]["reason"] == "Spared the deserter"


async def test_unknown_id_and_zero_delta_are_dropped(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    cid = await _add_companion(client, camp["id"])
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(camp["id"]))
        assert scene is not None
        turn = await turn_queries.create_turn(
            db, session_id=uuid.UUID(sess["id"]), scene_id=scene.id, idx=0, player_input="nothing much"
        )
        await turn_queries.update_turn_response(db, turn.id, dm_response="Quiet.")
        await db.commit()
        turn_id = turn.id

    deltas = [
        {"companion_id": str(uuid.uuid4()), "delta": 30, "reason": "ghost"},  # unknown companion
        {"companion_id": str(cid), "delta": 0, "reason": "no move"},  # zero delta
    ]
    with patch("cairn.agents.companion_reflector.run", new=AsyncMock(return_value=deltas)):
        await turns_service.run_companion_reflector(uuid.UUID(sess["id"]), turn_id)

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
    # companion_meta was initialized at creation; nothing should have moved it.
    assert char.companion_meta is not None
    assert char.companion_meta["approval"] == 0
    assert char.companion_meta["approval_log"] == []
