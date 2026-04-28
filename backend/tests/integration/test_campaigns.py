from httpx import AsyncClient

CREATE_BODY = {"name": "Tavern", "template_id": "tavern_v1"}


async def _create(client: AsyncClient, user_id: str, **overrides: str) -> dict:
    body = {**CREATE_BODY, **overrides}
    r = await client.post(
        "/v1/campaigns", headers={"X-User-Id": user_id}, json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/v1/campaigns", json=CREATE_BODY)
    assert r.status_code == 401


async def test_create_returns_campaign(client: AsyncClient) -> None:
    body = await _create(client, "user_a", name="Tavern A")
    assert body["name"] == "Tavern A"
    assert body["template_id"] == "tavern_v1"
    assert body["owner_id"] == "user_a"
    assert body["world_bible_namespace"].startswith("campaign_")
    assert "id" in body
    assert "created_at" in body


async def test_list_returns_only_my_campaigns(client: AsyncClient) -> None:
    await _create(client, "user_a", name="A1")
    await _create(client, "user_a", name="A2")
    await _create(client, "user_b", name="B1")

    r_a = await client.get("/v1/campaigns", headers={"X-User-Id": "user_a"})
    r_b = await client.get("/v1/campaigns", headers={"X-User-Id": "user_b"})

    assert len(r_a.json()) == 2
    assert len(r_b.json()) == 1
    assert {c["name"] for c in r_a.json()} == {"A1", "A2"}


async def test_get_own_campaign(client: AsyncClient) -> None:
    created = await _create(client, "user_a")
    r = await client.get(
        f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"}
    )
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


async def test_get_others_campaign_returns_404(client: AsyncClient) -> None:
    created = await _create(client, "user_a")
    r = await client.get(
        f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_b"}
    )
    assert r.status_code == 404
    assert r.json() == {
        "error": {
            "code": "campaign_not_found",
            "message": f"campaign {created['id']} not found",
        }
    }


async def test_delete_own_campaign(client: AsyncClient) -> None:
    created = await _create(client, "user_a")
    r = await client.delete(
        f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"}
    )
    assert r.status_code == 204

    r = await client.get(
        f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"}
    )
    assert r.status_code == 404


async def test_delete_others_campaign_returns_404(client: AsyncClient) -> None:
    created = await _create(client, "user_a")
    r = await client.delete(
        f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_b"}
    )
    assert r.status_code == 404


async def test_delete_nonexistent_returns_404(client: AsyncClient) -> None:
    r = await client.delete(
        "/v1/campaigns/00000000-0000-0000-0000-000000000000",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 404
