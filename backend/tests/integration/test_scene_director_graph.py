"""Direct tests for the Scene Director graph nodes.

The integration-wide `_fake_turn_graph_run` patches the whole graph, so the real nodes
(`_combat_entry`, `_scene_create`, routing) are never exercised through the HTTP path.
These tests call the node functions directly against a real DB, the way
`test_skill_check_flow` exercises `_resolve_skill_check`.
"""

import uuid

from httpx import AsyncClient

from cairn.context import current_turn_id
from cairn.db import client as db_client
from cairn.db.queries import locations as location_queries
from cairn.db.queries import scenes as scene_queries
from cairn.db.queries import sessions as session_queries
from cairn.db.queries import turns as turn_queries
from cairn.domain.services.settings import ResolvedCampaignSettings
from cairn.pipelines.turn_graph import (
    TurnState,
    _after_combat_entry,
    _after_pre,
    _combat_entry,
    _scene_create,
    _scene_director_pre,
)
from cairn.types import ScenePreOutput
from tests._factories import make_campaign, make_character, make_session


def _state(session_id: str, campaign_id: str, pre: ScenePreOutput | None, player_input: str = "go") -> TurnState:
    return {
        "session_id": session_id,
        "campaign_id": campaign_id,
        "player_input": player_input,
        "intent": None,
        "npc_name": None,
        "check": None,
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": pre,
        "is_scene_entry": False,
        "combat_just_started": False,
        "settings": ResolvedCampaignSettings(),
    }


def _trigger(npc_ids: list[str]) -> ScenePreOutput:
    return {
        "combat_trigger": {"hostile_npc_ids": npc_ids},
        "scene_transition_pull": None,
        "pacing_nudge": None,
    }


def _pull(to_location_id: str) -> ScenePreOutput:
    return {
        "combat_trigger": None,
        "scene_transition_pull": {"to_location_id": to_location_id, "reason": "player heads out"},
        "pacing_nudge": None,
    }


# --- Pure routing -----------------------------------------------------------------


def test_after_pre_combat_active_goes_to_terminus() -> None:
    assert _after_pre(_state("s", "c", None)) == "combat_terminus"


def test_after_pre_combat_trigger_goes_to_entry() -> None:
    assert _after_pre(_state("s", "c", _trigger(["id"]))) == "combat_entry"


def test_after_pre_empty_trigger_falls_through() -> None:
    assert _after_pre(_state("s", "c", _trigger([]))) == "route_intent"


def test_after_pre_transition_pull_goes_to_scene_create() -> None:
    assert _after_pre(_state("s", "c", _pull("loc"))) == "scene_create"


def test_after_pre_default_goes_to_route_intent() -> None:
    pre: ScenePreOutput = {"combat_trigger": None, "scene_transition_pull": None, "pacing_nudge": None}
    assert _after_pre(_state("s", "c", pre)) == "route_intent"


def test_after_combat_entry_branches_on_flag() -> None:
    started = _state("s", "c", None)
    started["combat_just_started"] = True
    assert _after_combat_entry(started) == "combat_terminus"
    assert _after_combat_entry(_state("s", "c", None)) == "route_intent"


# --- combat_entry -----------------------------------------------------------------


async def _seed(client: AsyncClient) -> tuple[str, str]:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    return camp["id"], sess["id"]


async def _first_npc_id(client: AsyncClient, campaign_id: str) -> str:
    r = await client.get(f"/v1/campaigns/{campaign_id}/npcs", headers={"X-User-Id": "user_a"})
    return r.json()[0]["id"]


async def test_combat_entry_starts_combat_from_valid_npc(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    npc_id = await _first_npc_id(client, campaign_id)

    result = await _combat_entry(_state(session_id, campaign_id, _trigger([npc_id])))

    assert result["combat_just_started"] is True
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        assert session.combat_active is True


async def test_combat_entry_drops_invalid_npc_and_falls_through(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)

    result = await _combat_entry(_state(session_id, campaign_id, _trigger(["not-a-uuid", str(uuid.uuid4())])))

    assert result["combat_just_started"] is False
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        assert session.combat_active is False


async def test_scene_director_pre_short_circuits_during_combat(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)
    npc_id = await _first_npc_id(client, campaign_id)
    await _combat_entry(_state(session_id, campaign_id, _trigger([npc_id])))

    result = await _scene_director_pre(_state(session_id, campaign_id, None))

    assert result == {"scene_pre_output": None}


# --- scene_create -----------------------------------------------------------------


async def test_scene_create_closes_old_opens_new_and_stamps_turn(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)

    # A committed turn whose scene_id we expect to be re-stamped onto the new scene.
    async with db_client.get_session() as db:
        opening = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert opening is not None
        opening_id = opening.id
        turn = await turn_queries.create_turn(
            db, session_id=uuid.UUID(session_id), scene_id=opening_id, idx=0, player_input="I head out"
        )
        await db.commit()
        turn_id = turn.id
        locations = await location_queries.list_by_campaign(db, uuid.UUID(campaign_id))
    target = locations[0]

    token = current_turn_id.set(turn_id)
    try:
        result = await _scene_create(_state(session_id, campaign_id, _pull(str(target.id))))
    finally:
        current_turn_id.reset(token)

    assert result["is_scene_entry"] is True
    async with db_client.get_session() as db:
        old = await scene_queries.get_scene(db, opening_id)
        assert old.ended_at is not None
        assert old.summary  # summarizer wrote something
        new = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert new is not None and new.id != opening_id
        assert new.location_id == target.id
        stamped = await turn_queries.get_turn(db, turn_id)
        assert stamped.scene_id == new.id
        session = await session_queries.get_session(db, uuid.UUID(session_id))
        assert session.pending_transition is None


async def test_scene_create_drops_unknown_location(client: AsyncClient) -> None:
    campaign_id, session_id = await _seed(client)

    result = await _scene_create(_state(session_id, campaign_id, _pull(str(uuid.uuid4()))))

    assert result["is_scene_entry"] is False
