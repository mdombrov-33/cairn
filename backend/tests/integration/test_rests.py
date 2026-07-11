import uuid

import pytest
from httpx import AsyncClient

from cairn.application import rests as rest_service
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.exceptions import ConflictError
from cairn.domain.services.combat.helpers import empty_combat_state
from tests._factories import make_campaign, make_character, make_session, parse_sse

FIGHTER: dict = {}  # default make_character is a fighter

WARLOCK: dict = {
    "name": "Zara",
    "character_class": "warlock",
    "background": "charlatan",
    "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 10, "wis": 13, "cha": 15},
    "skill_choices": ["Deception", "Arcana"],
    "spell_choices": ["Eldritch Blast", "Hex"],
    "subclass": "fiend",
}

WIZARD: dict = {
    "name": "Mira",
    "character_class": "wizard",
    "background": "sage",
    "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 15, "wis": 13, "cha": 10},
    "skill_choices": ["Insight", "Investigation"],
    "spell_choices": ["Magic Missile", "Shield"],
    "subclass": "evocation",
}

CLERIC: dict = {
    "name": "Tara",
    "character_class": "cleric",
    "background": "acolyte",
    "ability_scores": {"str": 10, "dex": 8, "con": 13, "int": 12, "wis": 15, "cha": 14},
    "skill_choices": ["Insight", "Religion"],
    "subclass": "life",
}


# Short rest


async def test_short_rest_resets_action_surge(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 2
        char.resources = {"action_surge": {"current": 0, "max": 1, "resets_on": "short_rest"}}
        await db.commit()

    async with db_client.get_session() as db:
        result = await rest_service.apply_short_rest(db, session_id=uuid.UUID(sess["id"]))

    assert result["rest_type"] == "short"
    char_result = next(r for r in result["results"] if r["character_id"] == str(cid))
    assert "action_surge" in char_result["resources_reset"]

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.resources["action_surge"]["current"] == 1


async def test_short_rest_restores_warlock_slots(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WARLOCK)
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.spell_slots = {"1": 0}  # fully spent
        await db.commit()

    async with db_client.get_session() as db:
        result = await rest_service.apply_short_rest(db, session_id=uuid.UUID(sess["id"]))

    char_result = next(r for r in result["results"] if r["character_id"] == str(cid))
    assert char_result["spell_slots_restored"] is True

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.spell_slots is not None
        assert all(v > 0 for v in char.spell_slots.values())


async def test_short_rest_advances_in_game_time(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    async with db_client.get_session() as db:
        await rest_service.apply_short_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        assert session.in_game_hours_elapsed == 1


async def test_short_rest_blocked_in_combat(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    async with db_client.get_session() as db:
        await session_queries.update_combat_state(
            db, uuid.UUID(sess["id"]), combat_state=empty_combat_state(), combat_active=True
        )
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ConflictError, match="in_combat"):
            await rest_service.apply_short_rest(db, session_id=uuid.UUID(sess["id"]))


# Long rest


async def test_long_rest_restores_full_hp(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.hp = 1
        await db.commit()

    async with db_client.get_session() as db:
        await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.hp == char.max_hp


async def test_long_rest_resets_long_rest_resources(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(
        client,
        camp["id"],
        character_class="barbarian",
        skill_choices=["Athletics", "Survival"],
    )
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.resources = {"rage": {"current": 0, "max": 2, "resets_on": "long_rest"}}
        await db.commit()

    async with db_client.get_session() as db:
        await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.resources["rage"]["current"] == 2


async def test_long_rest_restores_spell_slots_for_wizard(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WIZARD)
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.spell_slots = {"1": 0}  # fully spent
        await db.commit()

    async with db_client.get_session() as db:
        await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.spell_slots is not None
        assert all(v > 0 for v in char.spell_slots.values())


async def test_long_rest_clears_prepared_spells_for_prepared_casters(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WIZARD)
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.prepared_spells = ["Magic Missile", "Shield"]
        await db.commit()

    async with db_client.get_session() as db:
        result = await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    assert str(cid) in result["spell_prep_required"]

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.prepared_spells == []


async def test_long_rest_does_not_clear_prepared_spells_for_known_casters(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WARLOCK)
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        result = await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    char_result = next(r for r in result["results"] if r["character_id"] == str(cid))
    assert char_result["prepared_spells_cleared"] is False
    assert str(cid) not in result["spell_prep_required"]


async def test_long_rest_restores_half_hit_dice(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 4
        char.hit_dice_remaining = 0
        await db.commit()

    async with db_client.get_session() as db:
        await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        assert char.hit_dice_remaining == 2  # half of 4


async def test_long_rest_advances_in_game_time_by_8(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    async with db_client.get_session() as db:
        await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        assert session.in_game_hours_elapsed == 8


async def test_long_rest_blocked_in_combat(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    async with db_client.get_session() as db:
        await session_queries.update_combat_state(
            db, uuid.UUID(sess["id"]), combat_state=empty_combat_state(), combat_active=True
        )
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ConflictError, match="in_combat"):
            await rest_service.apply_long_rest(db, session_id=uuid.UUID(sess["id"]))


# Hit dice


async def test_roll_hit_die_heals_and_spends_die(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.hp = 1
        char.hit_dice_remaining = 3
        await db.commit()

    async with db_client.get_session() as db:
        result = await rest_service.roll_hit_die(db, character_id=cid)

    assert result["die_size"] == 10  # fighter d10
    assert result["hp_gained"] >= 1
    assert result["hp_new"] > 1
    assert result["hit_dice_remaining"] == 2


async def test_roll_hit_die_cannot_exceed_max_hp(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        max_hp = char.max_hp
        char.hp = max_hp  # already full
        char.hit_dice_remaining = 3
        await db.commit()

    async with db_client.get_session() as db:
        result = await rest_service.roll_hit_die(db, character_id=cid)

    assert result["hp_new"] == max_hp


async def test_roll_hit_die_no_dice_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.hit_dice_remaining = 0
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ConflictError, match="no hit dice"):
            await rest_service.roll_hit_die(db, character_id=cid)


# Spell preparation


async def test_prepare_spells_wizard(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WIZARD)
    cid = uuid.UUID(char_resp["id"])

    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{cid}/prepare-spells",
        headers={"X-User-Id": "user_a"},
        json={"spells": ["Magic Missile", "Shield"]},
    )
    assert r.status_code == 200
    assert r.json()["prepared_spells"] == ["Magic Missile", "Shield"]


async def test_prepare_spells_fighter_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{cid}/prepare-spells",
        headers={"X-User-Id": "user_a"},
        json={"spells": ["Magic Missile"]},
    )
    assert r.status_code == 422


async def test_prepare_spells_exceeds_max_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **CLERIC)
    cid = uuid.UUID(char_resp["id"])

    # Human cleric L1, WIS 15 + racial +1 = 16, mod=+3, max = 3+1=4 spells; send 5
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{cid}/prepare-spells",
        headers={"X-User-Id": "user_a"},
        json={"spells": ["Cure Wounds", "Bless", "Healing Word", "Guiding Bolt", "Sacred Flame"]},
    )
    assert r.status_code == 422


# Routes smoke tests


async def test_short_rest_route(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    r = await client.post(f"/v1/sessions/{sess['id']}/short-rest", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    events = parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "rest_applied"
    assert "token" in types
    assert types[-1] == "rest_end"
    assert events[0]["data"]["rest_type"] == "short"


async def test_long_rest_route(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    r = await client.post(f"/v1/sessions/{sess['id']}/long-rest", headers={"X-User-Id": "user_a"})
    assert r.status_code == 200
    events = parse_sse(r.text)
    types = [e["type"] for e in events]
    assert types[0] == "rest_applied"
    assert "token" in types
    assert types[-1] == "rest_end"
    assert events[0]["data"]["rest_type"] == "long"
