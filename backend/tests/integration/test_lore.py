import asyncio

from httpx import AsyncClient

from tests._factories import make_campaign, make_session


async def test_lore_endpoint_requires_auth(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    r = await client.get(f"/v1/sessions/{sess['id']}/lore")
    assert r.status_code == 401


async def test_lore_endpoint_wrong_owner_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_lore_empty_before_any_turns(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    r = await client.get(
        f"/v1/sessions/{sess['id']}/lore",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_lore_populates_after_turn(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

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
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

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
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

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
