import uuid

import pytest
from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import campaigns as campaign_queries
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import NotFoundError
from tests._factories import make_campaign, make_character, make_session


async def test_create_requires_auth(client: AsyncClient) -> None:
    r = await client.post("/v1/campaigns", json={"name": "Tavern", "template_id": "tavern_v1"})
    assert r.status_code == 401


async def test_create_returns_campaign(client: AsyncClient) -> None:
    body = await make_campaign(client, name="Tavern A")
    assert body["name"] == "Tavern A"
    # template_id is now a FK UUID to the seeded CampaignTemplate, not the string key.
    assert body["template_id"]
    assert body["owner_id"] == "user_a"
    assert body["world_bible_namespace"].startswith("campaign_")
    assert body["status"] == "active"
    assert body["is_mutable"] is True
    assert body["current_act_index"] == 0
    assert "id" in body
    assert "created_at" in body


async def test_list_returns_only_my_campaigns(client: AsyncClient) -> None:
    await make_campaign(client, name="A1")
    await make_campaign(client, name="A2")
    await make_campaign(client, owner="user_b", name="B1")

    r_a = await client.get("/v1/campaigns", headers={"X-User-Id": "user_a"})
    r_b = await client.get("/v1/campaigns", headers={"X-User-Id": "user_b"})

    assert len(r_a.json()) == 2
    assert len(r_b.json()) == 1
    assert {c["name"] for c in r_a.json()} == {"A1", "A2"}


async def test_get_own_campaign(client: AsyncClient) -> None:
    created = await make_campaign(client)
    r = await client.get(f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


async def test_get_others_campaign_returns_404(client: AsyncClient) -> None:
    created = await make_campaign(client)
    r = await client.get(f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404
    assert r.json() == {
        "error": {
            "code": "campaign_not_found",
            "message": f"campaign {created['id']} not found",
        }
    }


async def test_settings_patch_deep_merges_and_returns_resolved_settings(client: AsyncClient) -> None:
    created = await make_campaign(client)

    r = await client.patch(
        f"/v1/campaigns/{created['id']}/settings",
        headers={"X-User-Id": "user_a"},
        json={"preset": "balanced", "overrides": {"companion": {"combat": "player"}}},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["preset"] == "balanced"
    assert body["overrides"] == {"companion": {"combat": "player"}}
    assert body["resolved"]["companion"]["combat"] == "player"
    assert body["resolved"]["companion"]["dialogue"] == "ai"

    saved = await client.get(f"/v1/campaigns/{created['id']}/settings", headers={"X-User-Id": "user_a"})
    assert saved.status_code == 200
    assert saved.json() == body


async def test_campaign_settings_reject_account_owned_model_fields(client: AsyncClient) -> None:
    created = await make_campaign(client)

    r = await client.patch(
        f"/v1/campaigns/{created['id']}/settings",
        headers={"X-User-Id": "user_a"},
        json={"overrides": {"llm": {"tier": "pro"}}},
    )

    assert r.status_code == 422


async def test_completed_campaign_rejects_settings_changes(client: AsyncClient) -> None:
    campaign = await make_campaign(client)

    async with db_client.get_session() as db:
        stored = await campaign_queries.get_campaign(db, uuid.UUID(campaign["id"]))
        stored.status = "completed"
        await db.commit()

    response = await client.patch(
        f"/v1/campaigns/{campaign['id']}/settings",
        headers={"X-User-Id": "user_a"},
        json={"preset": "balanced"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "campaign_completed"


@pytest.mark.parametrize("terminal_status", ["completed", "ended_dead"])
async def test_terminal_campaign_read_model_marks_it_immutable(client: AsyncClient, terminal_status: str) -> None:
    campaign = await make_campaign(client)

    async with db_client.get_session() as db:
        stored = await campaign_queries.get_campaign(db, uuid.UUID(campaign["id"]))
        stored.status = terminal_status
        await db.commit()

    response = await client.get(
        f"/v1/campaigns/{campaign['id']}",
        headers={"X-User-Id": "user_a"},
    )

    assert response.status_code == 200
    assert response.json()["is_mutable"] is False


@pytest.mark.parametrize(
    ("terminal_status", "error_code"),
    [("completed", "campaign_completed"), ("ended_dead", "campaign_ended_dead")],
)
async def test_terminal_campaign_rejects_player_mutations(
    client: AsyncClient, terminal_status: str, error_code: str
) -> None:
    campaign = await make_campaign(client)
    session = await make_session(client, campaign["id"])

    async with db_client.get_session() as db:
        stored = await campaign_queries.get_campaign(db, uuid.UUID(campaign["id"]))
        stored.status = terminal_status
        await db.commit()

    responses = [
        await client.patch(
            f"/v1/campaigns/{campaign['id']}/settings",
            headers={"X-User-Id": "user_a"},
            json={"preset": "balanced"},
        ),
        await client.post(
            f"/v1/campaigns/{campaign['id']}/characters",
            headers={"X-User-Id": "user_a"},
            json={
                "name": "Ser Aldric",
                "race": "human",
                "character_class": "fighter",
                "background": "soldier",
                "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
                "skill_choices": ["Perception", "Athletics"],
                "alignment": "Lawful Good",
            },
        ),
        await client.post(
            f"/v1/campaigns/{campaign['id']}/sessions",
            headers={"X-User-Id": "user_a"},
        ),
        await client.post(
            f"/v1/sessions/{session['id']}/short-rest",
            headers={"X-User-Id": "user_a"},
        ),
        await client.post(
            f"/v1/sessions/{session['id']}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I look around."},
        ),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.json()["error"]["code"] == error_code


@pytest.mark.parametrize("terminal_status", ["completed", "ended_dead"])
async def test_terminal_campaign_deletion_cascades_runtime_state(client: AsyncClient, terminal_status: str) -> None:
    campaign = await make_campaign(client)
    character = await make_character(client, campaign["id"])
    session = await make_session(client, campaign["id"])
    turn_response = await client.post(
        f"/v1/sessions/{session['id']}/turns",
        headers={"X-User-Id": "user_a"},
        json={"player_input": "I look around."},
    )
    assert turn_response.status_code == 201

    async with db_client.get_session() as db:
        stored = await campaign_queries.get_campaign(db, uuid.UUID(campaign["id"]))
        stored.status = terminal_status
        await db.commit()

    response = await client.delete(
        f"/v1/campaigns/{campaign['id']}",
        headers={"X-User-Id": "user_a"},
    )

    assert response.status_code == 204
    async with db_client.get_session() as db:
        with pytest.raises(NotFoundError):
            await campaign_queries.get_campaign(db, uuid.UUID(campaign["id"]))
        with pytest.raises(NotFoundError):
            await character_queries.get_character(db, uuid.UUID(character["id"]))
        with pytest.raises(NotFoundError):
            await session_queries.get_session(db, uuid.UUID(session["id"]))


async def test_delete_own_campaign(client: AsyncClient) -> None:
    created = await make_campaign(client)
    r = await client.delete(f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"})
    assert r.status_code == 204

    r = await client.get(f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_a"})
    assert r.status_code == 404


async def test_delete_others_campaign_returns_404(client: AsyncClient) -> None:
    created = await make_campaign(client)
    r = await client.delete(f"/v1/campaigns/{created['id']}", headers={"X-User-Id": "user_b"})
    assert r.status_code == 404


async def test_delete_nonexistent_returns_404(client: AsyncClient) -> None:
    r = await client.delete(
        "/v1/campaigns/00000000-0000-0000-0000-000000000000",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 404
