import json

from httpx import AsyncClient


def _parse_sse(text: str) -> list[dict]:
    """Parse SSE response body into a list of {type, data} dicts."""
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


async def _campaign(client: AsyncClient, user_id: str = "user_a") -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": user_id},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _session(client: AsyncClient, campaign_id: str, user_id: str = "user_a") -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": user_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _submit(
    client: AsyncClient, session_id: str, player_input: str, user_id: str = "user_a"
) -> list[dict]:
    r = await client.post(
        f"/v1/sessions/{session_id}/turns",
        headers={"X-User-Id": user_id},
        json={"player_input": player_input},
    )
    assert r.status_code == 201, r.text
    return _parse_sse(r.text)


async def test_submit_requires_auth(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        json={"player_input": "I look around"},
    )
    assert r.status_code == 401


async def test_submit_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    r = await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_b"},
        json={"player_input": "I sneak in"},
    )
    assert r.status_code == 404


async def test_submit_streams_sse_events(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit(client, sess["id"], "I look around the tavern")

    types = [e["type"] for e in events]
    assert types[0] == "turn_start"
    assert "token" in types
    assert types[-1] == "turn_end"


async def test_submit_turn_start_has_intent(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit(client, sess["id"], "I look around the tavern")

    turn_start = events[0]
    assert turn_start["type"] == "turn_start"
    assert turn_start["data"]["intent"] == "narrative_action"
    assert "turn_id" in turn_start["data"]


async def test_submit_tokens_assemble_dm_response(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit(client, sess["id"], "I look around")
    tokens = [e["data"]["text"] for e in events if e["type"] == "token"]
    assert "".join(tokens) == "The tavern is quiet tonight."


async def test_submit_dm_response_persisted(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    events = await _submit(client, sess["id"], "I look around")
    turn_id = events[0]["data"]["turn_id"]

    r = await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    turns = r.json()
    assert len(turns) == 1
    assert turns[0]["id"] == turn_id
    assert turns[0]["dm_response"] == "The tavern is quiet tonight."
    assert turns[0]["player_input"] == "I look around"


async def test_submit_idx_increments(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    await _submit(client, sess["id"], "First")
    await _submit(client, sess["id"], "Second")
    await _submit(client, sess["id"], "Third")

    r = await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
    )
    turns = r.json()
    assert [t["idx"] for t in turns] == [0, 1, 2]
    assert [t["player_input"] for t in turns] == ["First", "Second", "Third"]


async def test_get_turns_requires_auth(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    r = await client.get(f"/v1/sessions/{sess['id']}/turns")
    assert r.status_code == 401


async def test_get_turns_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])
    await _submit(client, sess["id"], "Hello")

    r = await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_get_turns_empty_before_any_turns(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    r = await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_list_turns_returns_turns_in_order(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    await _submit(client, sess["id"], "First")
    await _submit(client, sess["id"], "Second")

    r = await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    turns = r.json()
    assert [t["player_input"] for t in turns] == ["First", "Second"]
