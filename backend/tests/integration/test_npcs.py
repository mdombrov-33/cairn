from unittest.mock import patch

from httpx import AsyncClient

from tests._factories import make_campaign, make_session, parse_sse


async def test_campaign_creation_seeds_npcs(client: AsyncClient) -> None:
    camp = await make_campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    npcs = r.json()
    assert len(npcs) == 3


async def test_npcs_have_stat_block_fields(client: AsyncClient) -> None:
    camp = await make_campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npcs = r.json()
    for npc in npcs:
        assert "ac" in npc
        assert "max_hp" in npc
        assert "hp" in npc
        assert "cr" in npc
        assert "ability_scores" in npc
        assert "conditions" in npc
        assert npc["hp"] == npc["max_hp"]


async def test_get_npc_by_id(client: AsyncClient) -> None:
    camp = await make_campaign(client)

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
    camp = await make_campaign(client)

    r = await client.get(f"/v1/campaigns/{camp['id']}/npcs")
    assert r.status_code == 401


async def test_npcs_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_npc_dialogue_turn_emits_tokens(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    npcs_r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npc_name = npcs_r.json()[0]["name"]

    async def _npc_run(player_input, session_id, campaign_id):
        return {
            "session_id": str(session_id),
            "campaign_id": str(campaign_id),
            "player_input": player_input,
            "intent": "npc_dialogue",
            "npc_name": npc_name,
            "check": None,
            "npc_context": f'[{npc_name}]: "Aye, what\'ll it be?"',
            "rest_context": None,
            "scene_pre_output": None,
            "is_scene_entry": False,
            "combat_just_started": False,
        }

    with patch("cairn.pipelines.turn_graph.run", side_effect=_npc_run):
        r = await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": f"I talk to {npc_name}"},
        )
    assert r.status_code == 201
    events = parse_sse(r.text)
    types = [e["type"] for e in events]

    assert "turn_start" in types
    assert "token" in types
    assert "turn_end" in types


async def test_npc_dialogue_persists_dm_response(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    npcs_r = await client.get(
        f"/v1/campaigns/{camp['id']}/npcs",
        headers={"X-User-Id": "user_a"},
    )
    npc_name = npcs_r.json()[0]["name"]

    async def _npc_run(player_input, session_id, campaign_id):
        return {
            "session_id": str(session_id),
            "campaign_id": str(campaign_id),
            "player_input": player_input,
            "intent": "npc_dialogue",
            "npc_name": npc_name,
            "check": None,
            "npc_context": f'[{npc_name}]: "Hello there."',
            "rest_context": None,
            "scene_pre_output": None,
            "is_scene_entry": False,
            "combat_just_started": False,
        }

    with patch("cairn.pipelines.turn_graph.run", side_effect=_npc_run):
        r = await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": f"I greet {npc_name}"},
        )
    events = parse_sse(r.text)
    turn_id = events[0]["data"]["turn_id"]

    turns = (
        await client.get(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
        )
    ).json()

    turn = next(t for t in turns if t["id"] == turn_id)
    assert turn["dm_response"] is not None
    assert len(turn["dm_response"]) > 0
