from httpx import AsyncClient


async def _campaign(client: AsyncClient, user_id: str = "user_a") -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": user_id},
        json={"name": "Tavern", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# Standard array: [15, 14, 13, 12, 10, 8]
FIGHTER: dict = {
    "name": "Ser Aldric",
    "race": "human",
    "character_class": "fighter",
    "background": "soldier",
    "ability_scores": {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
    "skill_choices": ["Perception", "History"],
    "ac": 16,
    "alignment": "Lawful Good",
    "bio": "A seasoned warrior.",
    "personality": "Stoic and direct.",
}

WIZARD: dict = {
    "name": "Mira the Grey",
    "race": "elf",
    "character_class": "wizard",
    "background": "sage",
    "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 15, "wis": 13, "cha": 10},
    "skill_choices": ["Insight", "Investigation"],
    "ac": 12,
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

COMPANION: dict = {
    **FIGHTER,
    "name": "Bramble",
    "is_companion": True,
    "voice_traits": {"tone": "gruff", "manner": "blunt"},
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


# --- Auth / ownership ---


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
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_b"},
    )
    assert r.status_code == 404


# --- Creation: identity fields ---


async def test_create_returns_identity_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

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


# --- Creation: derived stats ---


async def test_create_derives_hp_from_hit_die_and_con(client: AsyncClient) -> None:
    # Fighter hit_die=10, CON=13 + human +1 = 14 → mod=+2 → max_hp=12
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["hit_die_size"] == 10
    assert char["max_hp"] == 12
    assert char["hp"] == 12
    assert char["temp_hp"] == 0
    assert char["death_save_successes"] == 0
    assert char["death_save_failures"] == 0


async def test_create_derives_speed_from_race(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert char["speed"] == 30  # human


async def test_create_derives_saving_throws_from_class(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert set(char["saving_throw_proficiencies"]) == {"str", "con"}


async def test_create_combines_background_and_class_skills(client: AsyncClient) -> None:
    # soldier bg: Athletics, Intimidation; fighter choices: Perception, History
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert set(char["skill_proficiencies"]) == {
        "Perception",
        "History",
        "Athletics",
        "Intimidation",
    }


async def test_create_derives_initiative_from_dex(client: AsyncClient) -> None:
    # DEX 14 → mod +2
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert char["initiative"] == 2


async def test_passive_perception_with_perception_proficiency(client: AsyncClient) -> None:
    # WIS 10 → mod 0, Perception proficient → 10 + 0 + 2 = 12
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert char["passive_perception"] == 12


async def test_passive_perception_without_perception_proficiency(client: AsyncClient) -> None:
    # Fighter with no Perception in choices, soldier bg doesn't give it either
    camp = await _campaign(client)
    char = await _character(
        client, camp["id"], body={**FIGHTER, "skill_choices": ["History", "Insight"]}
    )
    # WIS 10 → mod 0, no Perception → 10
    assert char["passive_perception"] == 10


async def test_proficiency_bonus_is_two_at_level_1(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    assert char["proficiency_bonus"] == 2


async def test_initiative_tracks_dex_modifier(client: AsyncClient) -> None:
    camp_a = await _campaign(client)
    camp_b = await _campaign(client)

    # DEX 8 + human +1 = 9 → mod -1
    low_dex = await _character(
        client,
        camp_a["id"],
        body={
            **FIGHTER,
            "ability_scores": {"str": 15, "dex": 8, "con": 14, "int": 12, "wis": 10, "cha": 13},
        },
    )
    # DEX 15 + human +1 = 16 → mod +3
    high_dex = await _character(
        client,
        camp_b["id"],
        body={
            **FIGHTER,
            "ability_scores": {"str": 14, "dex": 15, "con": 13, "int": 12, "wis": 10, "cha": 8},
        },
    )

    assert low_dex["initiative"] == -1
    assert high_dex["initiative"] == 3


# --- Creation: spellcasting ---


async def test_spellcaster_derives_spell_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"], body=WIZARD)

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
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={
            **WIZARD,
            "name": "Sister Mira",
            "character_class": "cleric",
            "skill_choices": ["Insight", "Religion"],
            "spell_choices": None,
        },
    )
    # 422 ValidationError → subclass required
    assert r.status_code == 422, r.text
    assert "subclass" in r.text.lower()


async def test_cleric_with_valid_subclass_creates(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={
            **WIZARD,
            "name": "Sister Mira",
            "character_class": "cleric",
            "skill_choices": ["Insight", "Religion"],
            "subclass": "life",
            "spell_choices": None,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["subclass"] == "life"


async def test_invalid_subclass_for_class_rejected(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**FIGHTER, "subclass": "berserker"},  # barbarian's subclass
    )
    assert r.status_code == 422, r.text
    assert "invalid subclass" in r.text.lower()


async def test_racial_bonuses_applied_to_ability_scores(client: AsyncClient) -> None:
    # Elf gets +2 DEX; Hill Dwarf gets +2 CON (dwarf) + +1 WIS (hill-dwarf)
    camp_elf = await _campaign(client)
    camp_dwarf = await _campaign(client)

    elf = await _character(
        client,
        camp_elf["id"],
        body={**WIZARD, "race": "elf", "subrace": "high-elf"},
    )
    dwarf = await _character(
        client,
        camp_dwarf["id"],
        body={**FIGHTER, "race": "dwarf", "subrace": "hill-dwarf"},
    )

    # Wizard base: DEX 14 + elf +2 = 16, INT 15 + high-elf +1 = 16
    assert elf["ability_scores"]["dex"] == 16
    assert elf["ability_scores"]["int"] == 16
    assert elf["subrace"] == "high-elf"

    # Fighter base: CON 13 + dwarf +2 = 15, WIS 10 + hill-dwarf +1 = 11
    assert dwarf["ability_scores"]["con"] == 15
    assert dwarf["ability_scores"]["wis"] == 11
    assert dwarf["subrace"] == "hill-dwarf"


async def test_non_spellcaster_has_null_spell_fields(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    assert char["spellcasting_ability"] is None
    assert char["spell_slots"] is None
    assert char["spells_known"] == []


# --- Creation: ability_scores validation ---


async def test_ability_scores_must_use_standard_array(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={
            **FIGHTER,
            "ability_scores": {"str": 18, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
        },
    )
    assert r.status_code == 422


async def test_ability_scores_must_have_all_six_keys(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**FIGHTER, "ability_scores": {"str": 15, "dex": 14, "con": 13}},
    )
    assert r.status_code == 422


# --- GET: list ---


async def test_get_returns_empty_list_before_create(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    assert r.json() == []


async def test_get_returns_created_character(client: AsyncClient) -> None:
    camp = await _campaign(client)
    created = await _character(client, camp["id"])

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
    camp = await _campaign(client)
    await _character(client, camp["id"])
    await _character(client, camp["id"], body=COMPANION)

    r = await client.get(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 200
    chars = r.json()
    assert len(chars) == 2
    names = {c["name"] for c in chars}
    assert names == {"Ser Aldric", "Bramble"}


# --- Companion creation ---


async def test_companion_requires_voice_traits(client: AsyncClient) -> None:
    camp = await _campaign(client)
    r = await client.post(
        f"/v1/campaigns/{camp['id']}/characters",
        headers={"X-User-Id": "user_a"},
        json={**FIGHTER, "is_companion": True, "voice_traits": {}},
    )
    assert r.status_code == 422


# --- PATCH ---


async def test_patch_name_and_bio(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    r = await client.patch(
        f"/v1/campaigns/{camp['id']}/characters/{char['id']}",
        headers={"X-User-Id": "user_a"},
        json={"name": "Sir Aldric the Bold", "bio": "Reborn from battle."},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Sir Aldric the Bold"
    assert r.json()["bio"] == "Reborn from battle."


async def test_patch_companion_returns_401(client: AsyncClient) -> None:
    camp = await _campaign(client)
    companion = await _character(client, camp["id"], body=COMPANION)

    r = await client.patch(
        f"/v1/campaigns/{camp['id']}/characters/{companion['id']}",
        headers={"X-User-Id": "user_a"},
        json={"name": "Different Name"},
    )
    assert r.status_code == 401


# --- DELETE ---


async def test_delete_removes_character(client: AsyncClient) -> None:
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

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
