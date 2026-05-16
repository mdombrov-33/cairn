from httpx import AsyncClient

from tests._factories import DEFAULT_CHARACTER, make_campaign, make_character

# Class-specific payloads. Pass as `**WIZARD` etc. to override the default fighter.
WIZARD: dict = {
    "name": "Mira the Grey",
    "race": "elf",
    "character_class": "wizard",
    "background": "sage",
    "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 15, "wis": 13, "cha": 10},
    "skill_choices": ["Insight", "Investigation"],
    "alignment": "Neutral Good",
    "bio": "A dedicated scholar.",
    "personality": "Methodical and curious.",
    "spell_choices": [
        "Magic Missile",
        "Shield",
        "Fire Bolt",
        "Ray of Frost",
        "Mage Hand",
        "Prestidigitation",
    ],
}

COMPANION_OVERRIDES: dict = {
    "name": "Bramble",
    "is_companion": True,
    "voice_traits": {"tone": "gruff", "manner": "blunt"},
}

BARBARIAN: dict = {
    "name": "Grok",
    "race": "human",
    "character_class": "barbarian",
    "background": "soldier",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 8, "wis": 10, "cha": 12},
    "skill_choices": ["Athletics", "Survival"],
    "alignment": "Chaotic Good",
    "bio": "A savage warrior from the north.",
    "personality": "Loud and fearless.",
}

MONK: dict = {
    "name": "Liang",
    "race": "human",
    "character_class": "monk",
    "background": "hermit",
    "ability_scores": {"str": 8, "dex": 15, "con": 13, "int": 10, "wis": 14, "cha": 12},
    "skill_choices": ["Insight", "Athletics"],
    "alignment": "Lawful Neutral",
    "bio": "A disciplined warrior of wind.",
    "personality": "Calm and focused.",
}

CLERIC: dict = {
    **WIZARD,
    "name": "Sister Mira",
    "character_class": "cleric",
    "skill_choices": ["Insight", "Religion"],
    "subclass": "life",
    "spell_choices": None,
}


# Auth / ownership


async def test_create_requires_auth(client: AsyncClient) -> None:
    r = await client.post(
        "/v1/campaigns/00000000-0000-0000-0000-000000000000/characters",
        json=DEFAULT_CHARACTER,
    )
    assert r.status_code == 401


async def test_get_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/v1/campaigns/00000000-0000-0000-0000-000000000000/characters")
    assert r.status_code == 401


async def test_create_on_others_campaign_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_b"},
        json=DEFAULT_CHARACTER,
    )
    assert r.status_code == 404


async def test_get_on_others_campaign_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


# Creation: identity fields


async def test_create_returns_identity_fields(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])

    assert char["name"] == "Ser Aldric"
    assert char["race"] == "human"
    assert char["class"] == "fighter"
    assert char["background"] == "soldier"
    assert char["campaign_id"] == camp["id"]
    assert char["owner_id"] == "user_a"
    assert char["level"] == 1
    assert char["xp"] == 0
    assert char["alignment"] == "Lawful Good"
    assert char["status"] == "active"


# Creation: derived stats


async def test_create_derives_hp_from_hit_die_and_con(client: AsyncClient) -> None:
    # Fighter hit_die=10, CON=13 + human +1 = 14 → mod=+2 → max_hp=12
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])

    assert char["hit_die_size"] == 10
    assert char["max_hp"] == 12
    assert char["hp"] == 12
    assert char["temp_hp"] == 0
    assert char["death_save_successes"] == 0
    assert char["death_save_failures"] == 0


async def test_create_derives_speed_from_race(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["speed"] == 30  # human


async def test_create_derives_saving_throws_from_class(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert set(char["saving_throw_proficiencies"]) == {"str", "con"}


async def test_create_combines_background_and_class_skills(client: AsyncClient) -> None:
    # soldier bg: Athletics, Intimidation; fighter choices: Perception, Athletics (default)
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert set(char["skill_proficiencies"]) == {
        "Perception",
        "Athletics",
        "Intimidation",
    }


async def test_create_derives_initiative_from_dex(client: AsyncClient) -> None:
    # DEX 14 → mod +2
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["initiative"] == 2


async def test_passive_perception_with_perception_proficiency(client: AsyncClient) -> None:
    # WIS 10 → mod 0, Perception proficient → 10 + 0 + 2 = 12
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["passive_perception"] == 12


async def test_passive_perception_without_perception_proficiency(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], skill_choices=["History", "Insight"])
    # WIS 10 → mod 0, no Perception → 10
    assert char["passive_perception"] == 10


async def test_proficiency_bonus_is_two_at_level_1(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["proficiency_bonus"] == 2


async def test_initiative_tracksdex_modifier(client: AsyncClient) -> None:
    camp_a = await make_campaign(client)
    camp_b = await make_campaign(client)

    low_dex = await make_character(
        client,
        camp_a["id"],
        ability_scores={"str": 15, "dex": 8, "con": 14, "int": 12, "wis": 10, "cha": 13},
    )
    high_dex = await make_character(
        client,
        camp_b["id"],
        ability_scores={"str": 14, "dex": 15, "con": 13, "int": 12, "wis": 10, "cha": 8},
    )

    assert low_dex["initiative"] == -1
    assert high_dex["initiative"] == 3


# Creation: spellcasting


async def test_spellcaster_derives_spell_fields(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **WIZARD)

    assert char["spellcasting_ability"] == "int"
    assert char["spell_slots"] == {"1": 2}
    assert set(char["spells_known"]) == {
        "Magic Missile",
        "Shield",
        "Fire Bolt",
        "Ray of Frost",
        "Mage Hand",
        "Prestidigitation",
    }


async def test_cleric_requires_subclass_at_creation(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**CLERIC, "subclass": None},
    )
    assert r.status_code == 422, r.text
    assert "subclass" in r.text.lower()


async def test_cleric_with_valid_subclass_creates(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **CLERIC)
    assert char["subclass"] == "life"


async def test_invalid_subclass_for_class_rejected(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**DEFAULT_CHARACTER, "subclass": "berserker"},  # barbarian's subclass
    )
    assert r.status_code == 422, r.text
    assert "invalid subclass" in r.text.lower()


async def test_racial_bonuses_applied_to_ability_scores(client: AsyncClient) -> None:
    # Elf gets +2 DEX; Hill Dwarf gets +2 CON (dwarf) + +1 WIS (hill-dwarf)
    camp_elf = await make_campaign(client)
    camp_dwarf = await make_campaign(client)

    elf = await make_character(client, camp_elf["id"], **WIZARD, subrace="high-elf")
    dwarf = await make_character(client, camp_dwarf["id"], race="dwarf", subrace="hill-dwarf")

    assert elf["ability_scores"]["dex"] == 16
    assert elf["ability_scores"]["int"] == 16
    assert elf["subrace"] == "high-elf"

    assert dwarf["ability_scores"]["con"] == 15
    assert dwarf["ability_scores"]["wis"] == 11
    assert dwarf["subrace"] == "hill-dwarf"


async def test_non_spellcaster_has_null_spell_fields(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])

    assert char["spellcasting_ability"] is None
    assert char["spell_slots"] is None
    assert char["spells_known"] == []


# Creation: ability_scores validation


async def test_ability_scores_must_use_standard_array(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={
            **DEFAULT_CHARACTER,
            "ability_scores": {"str": 18, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
        },
    )
    assert r.status_code == 422


async def test_ability_scores_must_have_all_six_keys(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**DEFAULT_CHARACTER, "ability_scores": {"str": 15, "dex": 14, "con": 13}},
    )
    assert r.status_code == 422


# GET: list


async def test_get_returns_empty_list_before_create(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_get_returns_created_character(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    created = await make_character(client, camp["id"])

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    chars = r.json()
    assert len(chars) == 1
    assert chars[0]["id"] == created["id"]
    assert chars[0]["ability_scores"] == created["ability_scores"]


async def test_get_returns_player_and_companion(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    await make_character(client, camp["id"], **COMPANION_OVERRIDES)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    chars = r.json()
    assert len(chars) == 2
    names = {c["name"] for c in chars}
    assert names == {"Ser Aldric", "Bramble"}


# Companion creation


async def test_companion_requires_voice_traits(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**DEFAULT_CHARACTER, "is_companion": True, "voice_traits": {}},
    )
    assert r.status_code == 422


# PATCH


async def test_patch_name_and_bio(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])

    r = await client.patch(
        f"/v1/campaigns/{camp['id']}/characters/{char['id']}",
        headers={"X-User-Id": "user_a"},
        json={"name": "Sir Aldric the Bold", "bio": "Reborn from battle."},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Sir Aldric the Bold"
    assert r.json()["bio"] == "Reborn from battle."


async def test_patch_companion_returns_401(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    companion = await make_character(client, camp["id"], **COMPANION_OVERRIDES)

    r = await client.patch(
        f"/v1/campaigns/{camp['id']}/characters/{companion['id']}",
        headers={"X-User-Id": "user_a"},
        json={"name": "Different Name"},
    )
    assert r.status_code == 401


# DELETE


async def test_delete_removes_character(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])

    r = await client.delete(
        f"/v1/campaigns/{camp['id']}/characters/{char['id']}",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 204

    remaining = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert remaining.json() == []


# AC derivation


async def test_fighter_ac_derived_unarmored(client: AsyncClient) -> None:
    # No armor equipped → unarmored: 10 + DEX_mod.
    # DEX 14 + human +1 = 15 → mod +2 → AC 12.
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["ac"] == 12


async def test_barbarian_ac_uses_unarmored_defense(client: AsyncClient) -> None:
    # Barbarian unarmored defense: 10 + DEX + CON.
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **BARBARIAN)
    dex_mod = (char["ability_scores"]["dex"] - 10) // 2
    con_mod = (char["ability_scores"]["con"] - 10) // 2
    assert char["ac"] == 10 + dex_mod + con_mod


async def test_monk_ac_uses_unarmored_defense(client: AsyncClient) -> None:
    # Monk unarmored defense: 10 + DEX + WIS.
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **MONK)
    dex_mod = (char["ability_scores"]["dex"] - 10) // 2
    wis_mod = (char["ability_scores"]["wis"] - 10) // 2
    assert char["ac"] == 10 + dex_mod + wis_mod


async def test_cleric_ac_includes_starting_shield(client: AsyncClient) -> None:
    # Cleric starting_equipment contains a shield (auto-equipped). +2 AC.
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **CLERIC)
    shield_item = next(
        (i for i in char["inventory"] if i.get("srd_index") == "shield"),
        None,
    )
    assert shield_item is not None
    assert shield_item["equipped"] is True
    dex_mod = (char["ability_scores"]["dex"] - 10) // 2
    assert char["ac"] == 10 + dex_mod + 2


async def test_fighter_proficiencies_from_class(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert set(char["armor_proficiencies"]) == {"light", "medium", "heavy", "shield"}
    assert set(char["weapon_proficiencies"]) == {"simple", "martial"}


async def test_barbarian_proficiencies_from_class(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **BARBARIAN)
    assert set(char["armor_proficiencies"]) == {"light", "medium", "shield"}
    assert set(char["weapon_proficiencies"]) == {"simple", "martial"}


async def test_monk_proficiencies_from_class(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **MONK)
    assert set(char["armor_proficiencies"]) == set()
    assert "simple" in char["weapon_proficiencies"]
    assert "shortswords" in char["weapon_proficiencies"]


async def test_dwarf_race_weapon_proficiencies(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], race="dwarf", subrace="hill-dwarf")
    for prof in ["battleaxes", "handaxes", "light-hammers", "warhammers"]:
        assert prof in char["weapon_proficiencies"], f"missing {prof}"


# Equip / unequip


async def test_equip_adds_item_to_equipped_and_derives_ac(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    cleric = await make_character(client, camp["id"], **CLERIC)
    assert cleric["ac"] > 10  # shield equipped at creation

    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{cleric['id']}/unequip",
        headers={"X-User-Id": "user_a"},
        json={"item_name": "Shield"},
    )
    assert r.status_code == 200
    unequipped = r.json()
    dex_mod = (unequipped["ability_scores"]["dex"] - 10) // 2
    assert unequipped["ac"] == 10 + dex_mod

    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{cleric['id']}/equip",
        headers={"X-User-Id": "user_a"},
        json={"item_name": "Shield"},
    )
    assert r.status_code == 200
    reequipped = r.json()
    assert reequipped["ac"] == unequipped["ac"] + 2


async def test_equip_unknown_item_returns_404(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters/{char['id']}/equip",
        headers={"X-User-Id": "user_a"},
        json={"item_name": "Vorpal Sword of Doom"},
    )
    assert r.status_code == 404
