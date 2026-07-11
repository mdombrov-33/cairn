import uuid

from httpx import AsyncClient

from cairn.application import day_roll
from cairn.db import client as db_client
from cairn.db.models.session import Session
from cairn.db.queries import characters as character_queries
from cairn.domain.services.rng import session_rng
from tests._factories import make_campaign, make_character, make_session


async def test_seeded_template_resolves_on_campaign_create(client: AsyncClient) -> None:
    # make_campaign posts template_id="tavern_v1"; it must resolve to the seeded template.
    body = await make_campaign(client)
    assert body["template_id"]  # FK UUID
    assert body["status"] == "active"


async def test_create_campaign_unknown_template_404(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "x", "template_id": "does_not_exist"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "template_not_found"


async def test_character_uses_classes_array(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(
        client, camp["id"], character_class="wizard", subclass=None, skill_choices=["Arcana", "History"]
    )
    assert char["class"] == "wizard"
    assert char["classes"][0]["name"] == "wizard"
    assert char["classes"][0]["level"] == 1


async def test_session_has_rng_seed(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    async with db_client.get_session() as db:
        from cairn.db.queries import sessions as session_queries

        db_sess = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        assert db_sess.rng_seed > 0


def test_session_rng_is_deterministic_for_seed() -> None:
    s1 = Session(rng_seed=42)
    s2 = Session(rng_seed=42)
    seq1 = [session_rng(s1).randint(1, 20) for _ in range(1)]
    # Same seed → same first roll; a fresh Random(42) predicts it.
    import random

    assert seq1[0] == random.Random(42).randint(1, 20)
    assert session_rng(s2).randint(1, 20) == session_rng(s1).randint(1, 20)


async def test_day_roll_writes_day_summary(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    await make_character(client, camp["id"])

    async with db_client.get_session() as db:
        from cairn.db.queries import sessions as session_queries

        db_sess = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        db_sess.in_game_hours_elapsed = 25  # past one full day
        written = await day_roll.maybe_roll_days(db, db_sess)
        await db.commit()

    assert len(written) == 1
    assert written[0].type == "DAY_SUMMARY"
    assert written[0].day_index == 1

    # Calendar route surfaces it.
    r = await client.get(f"/v1/campaigns/{camp['id']}/calendar", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    days = r.json()
    assert len(days) == 1
    assert days[0]["day_index"] == 1


async def test_day_roll_idempotent(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])

    async with db_client.get_session() as db:
        from cairn.db.queries import sessions as session_queries

        db_sess = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        db_sess.in_game_hours_elapsed = 25
        await day_roll.maybe_roll_days(db, db_sess)
        again = await day_roll.maybe_roll_days(db, db_sess)
        await db.commit()

    assert again == []


async def test_advance_act_moves_to_next_act(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    from cairn.application import campaigns as campaign_service

    async with db_client.get_session() as db:
        updated = await campaign_service.advance_act(db, campaign_id=uuid.UUID(camp["id"]))
        await db.commit()
    # tavern_v1 has 2 acts; advancing from act 0 lands on act 1 (the final act).
    assert updated.current_act_index == 1
    assert updated.status == "active"


async def test_advance_act_concludes_campaign(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    from cairn.application import campaigns as campaign_service

    async with db_client.get_session() as db:
        await campaign_service.advance_act(db, campaign_id=uuid.UUID(camp["id"]))  # -> final act
        concluded = await campaign_service.advance_act(db, campaign_id=uuid.UUID(camp["id"]))  # -> conclude
        await db.commit()
    assert concluded.status == "completed"

    # CAMPAIGN_CONCLUDED entry written to the world bible.
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/lore",
        headers={"X-User-Id": "user_a"},
        params={"type": "CAMPAIGN_CONCLUDED"},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_party_derives_from_campaign(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    sess = await make_session(client, camp["id"])
    await make_character(client, camp["id"], name="Aldric")
    await make_character(client, camp["id"], name="Mage", character_class="wizard", skill_choices=["Arcana", "History"])

    async with db_client.get_session() as db:
        party = await character_queries.get_party_for_session(db, uuid.UUID(sess["id"]))
    assert {c.name for c in party} == {"Aldric", "Mage"}
