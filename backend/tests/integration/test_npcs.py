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


async def test_campaign_creation_seeds_npcs(client: AsyncClient) -> None:
    camp = await _campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    npcs = r.json()
    assert len(npcs) == 3


async def test_npcs_have_stat_block_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npcs = r.json()
    for npc in npcs:
        assert "ac" in npc
        assert "max_hp" in npc
        assert "current_hp" in npc
        assert "cr" in npc
        assert "stats" in npc
        assert "conditions" in npc
        assert npc["current_hp"] == npc["max_hp"]


async def test_get_npc_by_id(client: AsyncClient) -> None:
    camp = await _campaign(client)

    npcs_r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npc_id = npcs_r.json()[0]["id"]

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs/{npc_id}",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == npc_id


async def test_npcs_requires_auth(client: AsyncClient) -> None:
    camp = await _campaign(client)

    r = await client.get(f"/v1/campaigns/{camp['id']}/npcs")
    assert r.status_code == 401


async def test_npcs_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_npc_dialogue_turn_emits_tokens(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    npcs_r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npc_name = npcs_r.json()[0]["name"]

    with patch("cairn.pipelines.turn_graph.run", return_value=("npc_dialogue", npc_name)):
        r = await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": f"I talk to {npc_name}"},
        )
    assert r.status_code == 201
    events = _parse_sse(r.text)
    types = [e["type"] for e in events]

    assert "turn_start" in types
    assert "token" in types
    assert "turn_end" in types


async def test_npc_dialogue_persists_dm_response(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    npcs_r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npc_name = npcs_r.json()[0]["name"]

    with patch("cairn.pipelines.turn_graph.run", return_value=("npc_dialogue", npc_name)):
        r = await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": f"I greet {npc_name}"},
        )
    events = _parse_sse(r.text)
    turn_id = events[0]["data"]["turn_id"]

    turns = (await client.get(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
    )).json()

    turn = next(t for t in turns if t["id"] == turn_id)
    assert turn["dm_response"] is not None
    assert len(turn["dm_response"]) > 0
