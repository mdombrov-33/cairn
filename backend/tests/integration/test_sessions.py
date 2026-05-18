from httpx import AsyncClient

from tests._factories import make_campaign, make_session


async def test_start_session_requires_auth(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    r = await client.post(f"/v1/campaigns/{campaign['id']}/sessions")
    assert r.status_code == 401


async def test_start_session_returns_session(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    session = await make_session(client, campaign["id"])

    assert session["campaign_id"] == campaign["id"]
    assert "id" in session
    assert "started_at" in session
    assert session["ended_at"] is None
    assert session["summary"] is None


async def test_start_session_conflict_if_already_active(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    await make_session(client, campaign["id"])

    r = await client.post(
        f"/v1/campaigns/{campaign['id']}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_start_session_on_others_campaign_returns_404(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{campaign['id']}/sessions",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_get_session(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    started = await make_session(client, campaign["id"])

    r = await client.get(f"/v1/sessions/{started['id']}", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    assert r.json()["id"] == started["id"]


async def test_get_session_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    started = await make_session(client, campaign["id"])

    r = await client.get(f"/v1/sessions/{started['id']}", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404


async def test_end_session_sets_ended_at(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    started = await make_session(client, campaign["id"])

    r = await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    assert r.json()["ended_at"] is not None


async def test_end_session_allows_new_session_after(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    started = await make_session(client, campaign["id"])
    await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_a"})

    r = await client.post(f"/v1/campaigns/{campaign['id']}/sessions", headers={"X-User-Id": "user_a"})
    assert r.status_code == 201


async def test_end_session_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    started = await make_session(client, campaign["id"])

    r = await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404
