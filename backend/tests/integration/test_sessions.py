from httpx import AsyncClient


async def _create_campaign(client: AsyncClient, user_id: str) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": user_id},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _start_session(client: AsyncClient, campaign_id: str, user_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": user_id},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_start_session_requires_auth(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    r = await client.post(f"/v1/campaigns/{campaign['id']}/sessions")
    assert r.status_code == 401


async def test_start_session_returns_session(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    session = await _start_session(client, campaign["id"], "user_a")

    assert session["campaign_id"] == campaign["id"]
    assert "id" in session
    assert "started_at" in session
    assert session["ended_at"] is None
    assert session["summary"] is None


async def test_start_session_conflict_if_already_active(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    await _start_session(client, campaign["id"], "user_a")

    r = await client.post(
        f"/v1/campaigns/{campaign['id']}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


async def test_start_session_on_others_campaign_returns_404(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    r = await client.post(
        f"/v1/campaigns/{campaign['id']}/sessions",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_get_session(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    started = await _start_session(client, campaign["id"], "user_a")

    r = await client.get(f"/v1/sessions/{started['id']}", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    assert r.json()["id"] == started["id"]


async def test_get_session_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    started = await _start_session(client, campaign["id"], "user_a")

    r = await client.get(f"/v1/sessions/{started['id']}", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404


async def test_end_session_sets_ended_at(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    started = await _start_session(client, campaign["id"], "user_a")

    r = await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    assert r.json()["ended_at"] is not None


async def test_end_session_allows_new_session_after(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    started = await _start_session(client, campaign["id"], "user_a")
    await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_a"})

    r = await client.post(
        f"/v1/campaigns/{campaign['id']}/sessions", headers={"X-User-Id": "user_a"}
    )
    assert r.status_code == 201


async def test_end_session_wrong_owner_returns_404(client: AsyncClient) -> None:
    campaign = await _create_campaign(client, "user_a")
    started = await _start_session(client, campaign["id"], "user_a")

    r = await client.post(f"/v1/sessions/{started['id']}/end", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404
