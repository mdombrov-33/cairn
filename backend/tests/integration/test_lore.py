import asyncio
import json

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


async def test_lore_endpoint_requires_auth(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    r = await client.get(f"/v1/sessions/{sess['id']}/lore")
    assert r.status_code == 401


async def test_lore_endpoint_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_lore_empty_before_any_turns(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_lore_populates_after_turn(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": "I look around the tavern"},
    )
    # give the background task time to complete
    await asyncio.sleep(0.5)

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    entries = r.json()
    assert len(entries) >= 1
    assert all(e["type"] in ("NPC", "PLACE", "EVENT", "QUEST") for e in entries)
    assert all("key" in e and "content" in e for e in entries)


async def test_lore_type_filter(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    await client.post(
        f"/v1/sessions/{sess['id']}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": "I look around the tavern"},
    )
    await asyncio.sleep(0.5)

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_a"},
        params={"type": "PLACE"},
    )
    assert r.status_code == 200
    assert all(e["type"] == "PLACE" for e in r.json())


async def test_lore_upserts_on_repeat_key(client: AsyncClient) -> None:
    camp = await _campaign(client)
    sess = await _session(client, camp["id"])

    for _ in range(2):
        await client.post(
            f"/v1/sessions/{sess['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I look around the tavern"},
        )
    await asyncio.sleep(0.5)

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_a"},
    )
    # same key should be upserted, not duplicated
    keys = [e["key"] for e in r.json()]
    assert len(keys) == len(set(keys))
