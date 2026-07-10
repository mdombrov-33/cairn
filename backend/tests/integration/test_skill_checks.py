import uuid
from unittest.mock import patch

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import locations as location_queries
from cairn.db.queries import scenes as scene_queries
from cairn.domain.services import scenes as scene_service
from tests._factories import make_campaign, make_session, parse_sse


async def _skill_check_run(player_input, session_id, campaign_id):
    return {
        "session_id": str(session_id),
        "campaign_id": str(campaign_id),
        "player_input": player_input,
        "intent": "skill_check",
        "npc_name": None,
        "check": {
            "skill": "persuasion",
            "dc": 14,
            "modifier": 4,
            "roll_type": "d20",
            "status": "pending",
        },
        "npc_context": None,
        "rest_context": None,
        "scene_pre_output": None,
        "is_scene_entry": False,
        "combat_just_started": False,
    }


async def _submit_skill_check(client: AsyncClient, session_id: str) -> list[dict]:
    with patch("cairn.pipelines.turn_graph.run", side_effect=_skill_check_run):
        r = await client.post(
            f"/v1/sessions/{session_id}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I try to convince the guard the merchant is lying"},
        )
    assert r.status_code == 201
    return parse_sse(r.text)


async def test_skill_check_phase1_emits_check_required(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    events = await _submit_skill_check(client, sess["id"])

    types = [e["type"] for e in events]
    assert "turn_start" in types
    assert "token" in types
    assert "check_required" in types
    assert "turn_end" not in types


async def test_skill_check_phase1_check_required_has_fields(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    events = await _submit_skill_check(client, sess["id"])
    check_event = next(e for e in events if e["type"] == "check_required")

    assert check_event["data"]["skill"] == "persuasion"
    assert check_event["data"]["dc"] == 14
    assert check_event["data"]["modifier"] == 4
    assert check_event["data"]["roll_type"] == "d20"


async def test_skill_check_phase1_persists_pending_check(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    turns = (
        await client.get(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
        )
    ).json()

    turn = turns[0]
    assert turn["id"] == turn_id
    assert turn["dm_response"] is None
    assert turn["check_data"]["status"] == "pending"
    assert turn["check_data"]["skill"] == "persuasion"
    assert "setup_prose" in turn["check_data"]


async def test_resolve_requires_auth(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        json={"roll": 17},
    )
    assert r.status_code == 401


async def test_resolve_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_b"},
        json={"roll": 17},
    )
    assert r.status_code == 404


async def test_resolve_on_narrative_turn_returns_409(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": "I look around"},
    )
    turn_id = parse_sse(r.text)[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "no_pending_check"


async def test_resolve_emits_roll_result_and_turn_end(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    assert r.status_code == 200
    resolve_events = parse_sse(r.text)
    types = [e["type"] for e in resolve_events]

    assert "roll_result" in types
    assert "token" in types
    assert "turn_end" in types


async def test_resolve_computes_success_correctly(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    # roll=17, modifier=4 (from fake), dc=14 → total=21 → success
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    roll_result = next(e for e in parse_sse(r.text) if e["type"] == "roll_result")
    assert roll_result["data"]["roll"] == 17
    assert roll_result["data"]["total"] == 21
    assert roll_result["data"]["success"] is True


async def test_resolve_failure(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    # roll=5, modifier=4, dc=14 → total=9 → failure
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 5},
    )
    roll_result = next(e for e in parse_sse(r.text) if e["type"] == "roll_result")
    assert roll_result["data"]["total"] == 9
    assert roll_result["data"]["success"] is False


async def test_resolve_persists_dm_response_and_check(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )

    turns = (
        await client.get(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
        )
    ).json()

    turn = turns[0]
    assert turn["dm_response"] is not None
    assert turn["check_data"]["status"] == "resolved"
    assert turn["check_data"]["roll"] == 17
    assert turn["check_data"]["total"] == 21
    assert turn["check_data"]["success"] is True


async def test_resolve_roll_must_be_1_to_20(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 21},
    )
    assert r.status_code == 422


# --- Check-gated discoveries: a passed check surfaces an authored hidden detail ---


async def _open_back_room(campaign_id: str) -> None:
    """Make the authored back room (investigation dc 14 → false drawer) the campaign's current scene."""
    cid = uuid.UUID(campaign_id)
    async with db_client.get_session() as db:
        back_room = next(loc for loc in await location_queries.list_by_campaign(db, cid) if "Back Room" in loc.name)
        await scene_service.open_scene(db, campaign_id=cid, location=back_room, act_index=0)
        await db.commit()


async def _submit_check(client: AsyncClient, session_id: str, campaign_id: str, *, skill: str) -> str:
    """Submit a turn that resolves to a pending check of `skill` (dc 14, mod 0). Returns the turn id."""

    async def _run(player_input, session_id, campaign_id):
        return {
            "session_id": str(session_id),
            "campaign_id": str(campaign_id),
            "player_input": player_input,
            "intent": "skill_check",
            "npc_name": None,
            "check": {"skill": skill, "dc": 14, "modifier": 0, "roll_type": "d20", "status": "pending"},
            "npc_context": None,
            "rest_context": None,
            "scene_pre_output": None,
            "is_scene_entry": False,
            "combat_just_started": False,
        }

    with patch("cairn.pipelines.turn_graph.run", side_effect=_run):
        r = await client.post(
            f"/v1/sessions/{session_id}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": f"I make a {skill} check on the desk"},
        )
    assert r.status_code == 201
    return parse_sse(r.text)[0]["data"]["turn_id"]


async def _discovered_facts(campaign_id: str) -> tuple[list[str], int | None]:
    async with db_client.get_session() as db:
        scene = await scene_queries.get_current_scene(db, uuid.UUID(campaign_id))
        assert scene is not None
        return list(scene.discovered_facts), scene.last_revelation_at_turn


async def test_passed_check_surfaces_matching_hidden_detail(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    await _open_back_room(camp["id"])
    turn_id = await _submit_check(client, sess["id"], camp["id"], skill="investigation")

    # roll 14 + mod 0 = 14 → clears the authored investigation dc 14.
    await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 14},
    )

    facts, last_at = await _discovered_facts(camp["id"])
    assert any("false drawer" in f for f in facts)
    assert last_at is not None  # stalling clock stamped


async def test_failed_check_surfaces_nothing(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    await _open_back_room(camp["id"])
    turn_id = await _submit_check(client, sess["id"], camp["id"], skill="investigation")

    # roll 10 + mod 0 = 10 → under the authored dc 14.
    await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 10},
    )

    facts, last_at = await _discovered_facts(camp["id"])
    assert facts == []
    assert last_at is None


async def test_wrong_skill_leaves_hidden_detail_sealed(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    await _open_back_room(camp["id"])
    # Perception dc 16 gates the footprints; an investigation total of 14 must not surface them.
    turn_id = await _submit_check(client, sess["id"], camp["id"], skill="investigation")

    await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 14},
    )

    facts, _ = await _discovered_facts(camp["id"])
    assert not any("footprints" in f for f in facts)
