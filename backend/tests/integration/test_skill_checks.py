import json
from unittest.mock import patch

from httpx import AsyncClient


def _parse_sse(text: str) -> list[dict]:
    events = []
    current: dict = {}
    for line in text.splitlines():
        if line.startswith("event: "):
            current["type"] = line[7:]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[6:])
        elif not line and current:
            events.append(current)
            current = {}
    return events


async def _campaign(client: AsyncClient) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201
    return r.json()


async def _session(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 201
    return r.json()


async def _submit_skill_check(client: AsyncClient, session_id: str) -> list[dict]:
    with patch("cairn.pipelines.turn_graph.run", return_value=("skill_check", None)):
        r = await client.post(
            f"/v1/sessions/{session_id}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I try to convince the guard the merchant is lying"},
        )
    assert r.status_code == 201
    return _parse_sse(r.text)


async def test_skill_check_phase1_emits_check_required(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit_skill_check(client, sess["id"])

    types = [e["type"] for e in events]
    assert "turn_start" in types
    assert "token" in types
    assert "check_required" in types
    assert "turn_end" not in types


async def test_skill_check_phase1_check_required_has_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit_skill_check(client, sess["id"])
    check_event = next(e for e in events if e["type"] == "check_required")

    assert check_event["data"]["skill"] == "persuasion"
    assert check_event["data"]["dc"] == 14
    assert check_event["data"]["modifier"] == 4
    assert check_event["data"]["roll_type"] == "d20"


async def test_skill_check_phase1_persists_pending_check(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

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
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        json={"roll": 17},
    )
    assert r.status_code == 401


async def test_resolve_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_b"},
        json={"roll": 17},
    )
    assert r.status_code == 404


async def test_resolve_on_narrative_turn_returns_409(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": "I look around"},
    )
    turn_id = _parse_sse(r.text)[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "no_pending_check"


async def test_resolve_emits_roll_result_and_turn_end(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    assert r.status_code == 200
    resolve_events = _parse_sse(r.text)
    types = [e["type"] for e in resolve_events]

    assert "roll_result" in types
    assert "token" in types
    assert "turn_end" in types


async def test_resolve_computes_success_correctly(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    # roll=17, modifier=4 (from fake), dc=14 → total=21 → success
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 17},
    )
    roll_result = next(e for e in _parse_sse(r.text) if e["type"] == "roll_result")
    assert roll_result["data"]["roll"] == 17
    assert roll_result["data"]["total"] == 21
    assert roll_result["data"]["success"] is True


async def test_resolve_failure(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    # roll=5, modifier=4, dc=14 → total=9 → failure
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 5},
    )
    roll_result = next(e for e in _parse_sse(r.text) if e["type"] == "roll_result")
    assert roll_result["data"]["total"] == 9
    assert roll_result["data"]["success"] is False


async def test_resolve_persists_dm_response_and_check(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
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
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    events = await _submit_skill_check(client, sess["id"])
    turn_id = events[0]["data"]["turn_id"]

    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns/{turn_id}/resolve",
        headers={"X-User-Id": "user_a"},
        json={"roll": 21},
    )
    assert r.status_code == 422
