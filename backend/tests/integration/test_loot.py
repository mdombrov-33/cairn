"""Integration tests for loot_item tool."""

import uuid

import pytest
from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import npcs as npc_queries
from cairn.tools.game_state import loot_item

FIGHTER: dict = {
    "name": "Ser Aldric",
    "race": "human",
    "character_class": "fighter",
    "background": "soldier",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "skill_choices": ["Perception", "History"],
    "alignment": "Lawful Good",
    "bio": "A seasoned warrior.",
    "personality": "Stoic and direct.",
}


async def _campaign(client: AsyncClient) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "Test", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _character(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/characters",
        headers={"X-User-Id": "user_a"},
        json=FIGHTER,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _session(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _get_npc_by_name(campaign_id: str, name: str):
    cid = uuid.UUID(campaign_id)
    async with db_client.get_session() as db:
        npc = await npc_queries.find_by_name(db, cid, name)
    assert npc is not None, f"NPC {name!r} not found"
    return npc


async def test_loot_item_transfers_item_from_npc_to_character(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    result = await loot_item.ainvoke(
        {
            "session_id": sess["id"],
            "npc_id": str(npc.id),
            "item_name": "Chain Mail",
            "character_id": char["id"],
        }
    )

    assert result["name"] == "Chain Mail"

    async with db_client.get_session() as db:
        updated_npc = await npc_queries.get_npc(db, npc.id)
    assert "Chain Mail" not in [i["name"] for i in (updated_npc.inventory or [])]

    async with db_client.get_session() as db:
        updated_char = await character_queries.get_character(db, uuid.UUID(char["id"]))
    assert "Chain Mail" in [i["name"] for i in (updated_char.inventory or [])]


async def test_loot_nonexistent_item_raises(client: AsyncClient) -> None:
    from cairn.domain.exceptions import NotFoundError

    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    with pytest.raises(NotFoundError):
        await loot_item.ainvoke(
            {
                "session_id": sess["id"],
                "npc_id": str(npc.id),
                "item_name": "Nonexistent Sword of Power",
                "character_id": char["id"],
            }
        )


async def test_loot_cross_campaign_npc_raises(client: AsyncClient) -> None:
    from cairn.domain.exceptions import ValidationError

    camp_a = await _campaign(client)
    char_a = await _character(client, camp_a["id"])
    sess_a = await _session(client, camp_a["id"])

    # Second campaign with its own NPC
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "Other", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201
    camp_b = r.json()
    npc_b = await _get_npc_by_name(camp_b["id"], "Town Guard")

    with pytest.raises(ValidationError):
        await loot_item.ainvoke(
            {
                "session_id": sess_a["id"],
                "npc_id": str(npc_b.id),
                "item_name": "Chain Mail",
                "character_id": char_a["id"],
            }
        )


# Route tests


async def test_loot_route_transfers_item(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    r = await client.post(
        f"/v1/sessions/{sess['id']}/loot",
        headers={"X-User-Id": "user_a"},
        json={
            "npc_id": str(npc.id),
            "character_id": char["id"],
            "item_name": "Chain Mail",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item"]["name"] == "Chain Mail"

    async with db_client.get_session() as db:
        updated_npc = await npc_queries.get_npc(db, npc.id)
        updated_char = await character_queries.get_character(db, uuid.UUID(char["id"]))
    assert "Chain Mail" not in [i["name"] for i in (updated_npc.inventory or [])]
    assert "Chain Mail" in [i["name"] for i in (updated_char.inventory or [])]


async def test_loot_route_requires_auth(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    r = await client.post(
        f"/v1/sessions/{sess['id']}/loot",
        json={"npc_id": str(npc.id), "character_id": char["id"], "item_name": "Chain Mail"},
    )
    assert r.status_code == 401


async def test_loot_route_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    r = await client.post(
        f"/v1/sessions/{sess['id']}/loot",
        headers={"X-User-Id": "user_b"},
        json={"npc_id": str(npc.id), "character_id": char["id"], "item_name": "Chain Mail"},
    )
    assert r.status_code == 404


async def test_loot_route_missing_item_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    npc = await _get_npc_by_name(camp["id"], "Town Guard")

    r = await client.post(
        f"/v1/sessions/{sess['id']}/loot",
        headers={"X-User-Id": "user_a"},
        json={
            "npc_id": str(npc.id),
            "character_id": char["id"],
            "item_name": "Unobtainium Sword",
        },
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "item_not_found"
