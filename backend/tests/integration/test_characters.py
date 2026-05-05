from httpx import AsyncClient


async def _campaign(client: AsyncClient, user_id: str = "user_a") -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": user_id},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


FIGHTER: dict = {
    "name": "Ser Aldric",
    "race": "Human",
    "character_class": "Fighter",
    "background": "Soldier",
    "level": 3,
    "stats": {"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 13},
    "hp": 24,
    "max_hp": 32,
    "ac": 16,
    "speed": 30,
    "saving_throw_proficiencies": ["str", "con"],
    "skill_proficiencies": ["athletics", "perception", "intimidation"],
    "features": ["Action Surge", "Second Wind", "Combat Superiority"],
    "inventory": [{"name": "Longsword", "quantity": 1, "weight": 3, "notes": "", "equipped": True}],
    "currency": {"gp": 30, "sp": 5, "cp": 0},
}

WIZARD: dict = {
    "name": "Mira the Grey",
    "race": "Elf",
    "character_class": "Wizard",
    "background": "Sage",
    "level": 3,
    "stats": {"str": 8, "dex": 14, "con": 12, "int": 17, "wis": 13, "cha": 10},
    "hp": 14,
    "max_hp": 14,
    "ac": 12,
    "speed": 30,
    "saving_throw_proficiencies": ["int", "wis"],
    "skill_proficiencies": ["arcana", "history"],
    "spellcasting_ability": "int",
    "spell_slots": {"1": {"current": 4, "max": 4}, "2": {"current": 2, "max": 2}},
    "spells_known": ["Fireball", "Mage Armor", "Magic Missile", "Fire Bolt"],
    "features": ["Arcane Recovery"],
    "inventory": [],
    "currency": {"gp": 5, "sp": 0, "cp": 0},
}


async def _character(
    client: AsyncClient,
    campaign_id: str,
    user_id: str = "user_a",
    body: dict | None = None,
) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/characters",
        headers={"X-User-Id": user_id},
        json=body or FIGHTER,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_requires_auth(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/campaigns/00000000-0000-0000-0000-000000000000/characters",
        json=FIGHTER,
    )
    assert r.status_code == 401


async def test_get_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/v1/campaigns/00000000-0000-0000-0000-000000000000/characters")
    assert r.status_code == 401


async def test_create_on_others_campaign_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client, "user_a")
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_b"},
        json=FIGHTER,
    )
    assert r.status_code == 404


async def test_get_on_others_campaign_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client, "user_a")
    await _character(client, camp["id"])

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


async def test_get_before_create_returns_404(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "character_not_found"


async def test_create_returns_all_identity_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["name"] == "Ser Aldric"
    assert char["race"] == "Human"
    assert char["class"] == "Fighter"
    assert char["background"] == "Soldier"
    assert char["campaign_id"] == camp["id"]
    assert char["owner_id"] == "user_a"
    assert char["level"] == 3
    assert char["xp"] == 0
    assert char["alignment"] is None
    assert char["portrait_url"] is None


async def test_create_returns_correct_combat_defaults(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["hp"] == 24
    assert char["max_hp"] == 32
    assert char["temp_hp"] == 0
    assert char["ac"] == 16
    assert char["speed"] == 30
    assert char["death_save_successes"] == 0
    assert char["death_save_failures"] == 0


async def test_derived_fields_fighter_level_3(client: AsyncClient) -> None:
    """
    level 3  → proficiency_bonus = 2
    DEX 12   → initiative = +1
    WIS 10, perception proficient → passive_perception = 10 + 0 + 2 = 12
    """
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["proficiency_bonus"] == 2
    assert char["initiative"] == 1
    assert char["passive_perception"] == 12


async def test_passive_perception_without_perception_proficiency(client: AsyncClient) -> None:
    """Without perception in skill_proficiencies, passive perception = 10 + WIS mod only."""
    camp = await _campaign(client)
    body = {**FIGHTER, "skill_proficiencies": ["athletics", "intimidation"]}
    char = await _character(client, camp["id"], body=body)

    # WIS 10 → mod 0, no perception prof → 10
    assert char["passive_perception"] == 10


async def test_proficiency_bonus_jumps_at_level_5(client: AsyncClient) -> None:
    """Proficiency bonus is +2 at levels 1–4 and +3 at levels 5–8."""
    camp_a = await _campaign(client)
    camp_b = await _campaign(client)

    char_4 = await _character(client, camp_a["id"], body={**FIGHTER, "level": 4})
    char_5 = await _character(client, camp_b["id"], body={**FIGHTER, "level": 5})

    assert char_4["proficiency_bonus"] == 2
    assert char_5["proficiency_bonus"] == 3


async def test_initiative_tracks_dex_modifier(client: AsyncClient) -> None:
    """DEX 8 → mod -1, DEX 18 → mod +4."""
    camp_a = await _campaign(client)
    camp_b = await _campaign(client)

    low_dex = await _character(
        client, camp_a["id"], body={**FIGHTER, "stats": {**FIGHTER["stats"], "dex": 8}}
    )
    high_dex = await _character(
        client, camp_b["id"], body={**FIGHTER, "stats": {**FIGHTER["stats"], "dex": 18}}
    )

    assert low_dex["initiative"] == -1
    assert high_dex["initiative"] == 4


async def test_spellcaster_fields_round_trip(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"], body=WIZARD)

    assert char["spellcasting_ability"] == "int"
    assert char["spell_slots"] == {"1": {"current": 4, "max": 4}, "2": {"current": 2, "max": 2}}
    assert set(char["spells_known"]) == {"Fireball", "Mage Armor", "Magic Missile", "Fire Bolt"}


async def test_non_spellcaster_has_null_spell_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["spellcasting_ability"] is None
    assert char["spell_slots"] is None
    assert char["spells_known"] == []


async def test_get_returns_created_character(client: AsyncClient) -> None:
    camp = await _campaign(client)
    created = await _character(client, camp["id"])

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    got = r.json()
    assert got["id"] == created["id"]
    assert got["stats"] == created["stats"]
    assert got["inventory"] == created["inventory"]
    assert got["currency"] == created["currency"]
    assert got["features"] == created["features"]
