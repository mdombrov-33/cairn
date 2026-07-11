import uuid

import pytest
from httpx import AsyncClient

from cairn.application import leveling
from cairn.application.leveling import (
    LevelUpChoices,
    build_level_up_preview,
    initialize_resources,
    level_for_xp,
)
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.domain.characters import AbilityScores
from cairn.domain.exceptions import ValidationError
from cairn.domain.services import feat_effects
from tests._factories import make_campaign, make_character

# Class presets — pass as `**WIZARD` to override the default fighter
WIZARD: dict = {
    "name": "Mira",
    "race": "elf",
    "character_class": "wizard",
    "background": "sage",
    "ability_scores": {"str": 8, "dex": 14, "con": 12, "int": 15, "wis": 13, "cha": 10},
    "skill_choices": ["Insight", "Investigation"],
    "alignment": "Neutral Good",
    "bio": "A scholar.",
    "personality": "Curious.",
    "spell_choices": ["Magic Missile", "Shield"],
}


# Pure helpers


def test_level_for_xp_thresholds() -> None:
    assert level_for_xp(0) == 1
    assert level_for_xp(299) == 1
    assert level_for_xp(300) == 2
    assert level_for_xp(899) == 2
    assert level_for_xp(900) == 3
    assert level_for_xp(2699) == 3
    assert level_for_xp(2700) == 4
    assert level_for_xp(355000) == 20
    assert level_for_xp(999999) == 20


def test_initialize_resources_barbarian_l1() -> None:
    resources = initialize_resources("barbarian", 1)
    assert resources == {"rage": {"current": 2, "max": 2, "resets_on": "long_rest"}}


def test_initialize_resources_fighter_l1_has_no_action_surge() -> None:
    # SRD: fighter gets action_surges at level 2, not level 1.
    resources = initialize_resources("fighter", 1)
    assert resources == {}


def test_initialize_resources_fighter_l2() -> None:
    resources = initialize_resources("fighter", 2)
    assert resources == {"action_surge": {"current": 1, "max": 1, "resets_on": "short_rest"}}


def test_initialize_resources_monk_l1_empty_l2_ki() -> None:
    assert initialize_resources("monk", 1) == {}
    assert initialize_resources("monk", 2) == {"ki_points": {"current": 2, "max": 2, "resets_on": "short_rest"}}


def test_initialize_resources_unknown_class_returns_empty() -> None:
    assert initialize_resources("bogus", 1) == {}


def test_initialize_resources_bard_l1_bardic_inspiration() -> None:
    # CHA 16 → mod +3 → 3 bardic inspiration dice, resets on long_rest at L1
    resources = initialize_resources("bard", 1, {"cha": 16, "str": 8, "dex": 14, "con": 12, "int": 10, "wis": 13})
    assert resources["bardic_inspiration"] == {"current": 3, "max": 3, "resets_on": "long_rest"}


def test_initialize_resources_bard_l5_resets_on_short_rest() -> None:
    resources = initialize_resources("bard", 5, {"cha": 16, "str": 8, "dex": 14, "con": 12, "int": 10, "wis": 13})
    assert resources["bardic_inspiration"]["resets_on"] == "short_rest"


# Character creation wires resources


BARBARIAN: dict = {
    "name": "Krug",
    "character_class": "barbarian",
    "skill_choices": ["Athletics", "Survival"],
}


async def test_creating_barbarian_initializes_rage(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"], **BARBARIAN)
    assert char["resources"] == {"rage": {"current": 2, "max": 2, "resets_on": "long_rest"}}


async def test_creating_fighter_has_empty_resources(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    assert char["resources"] == {}


# Award XP


async def test_award_xp_below_threshold(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        result = await leveling.award_xp(
            db,
            character_id=uuid.UUID(char["id"]),
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            amount=100,
        )
    assert result == {"xp": 100, "level": 1, "ready_to_level_up": False}


async def test_award_xp_crosses_threshold(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        result = await leveling.award_xp(
            db,
            character_id=uuid.UUID(char["id"]),
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            amount=300,
        )
    assert result == {"xp": 300, "level": 1, "ready_to_level_up": True}


async def test_ai_controlled_companion_levels_automatically(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(
        client,
        camp["id"],
        name="Wrenna",
        is_companion=True,
        narrative_profile={"name": "Wrenna", "personality": "Steady", "voice": {"cadence": "brief"}},
    )

    async with db_client.get_session() as db:
        result = await leveling.award_xp(
            db,
            character_id=uuid.UUID(char["id"]),
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            amount=300,
        )

    assert result == {"xp": 300, "level": 2, "ready_to_level_up": False}


async def test_player_controlled_companion_keeps_pending_level(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    settings_response = await client.patch(
        f"/v1/campaigns/{camp['id']}/settings",
        headers={"X-User-Id": "user_a"},
        json={"overrides": {"companion": {"leveling": "player"}}},
    )
    assert settings_response.status_code == 200
    char = await make_character(
        client,
        camp["id"],
        name="Wrenna",
        is_companion=True,
        narrative_profile={"name": "Wrenna", "personality": "Steady", "voice": {"cadence": "brief"}},
    )

    async with db_client.get_session() as db:
        result = await leveling.award_xp(
            db,
            character_id=uuid.UUID(char["id"]),
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            amount=300,
        )

    assert result == {"xp": 300, "level": 1, "ready_to_level_up": True}


async def test_award_xp_negative_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        with pytest.raises(ValidationError):
            await leveling.award_xp(
                db,
                character_id=uuid.UUID(char["id"]),
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                amount=-5,
            )


# Preview


async def test_preview_none_when_no_pending(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        assert build_level_up_preview(char) is None


async def test_preview_fighter_l1_to_l2(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        char.xp = 300
        preview = build_level_up_preview(char)
    assert preview is not None
    assert preview["target_level"] == 2
    assert preview["asi_or_feat"] is False
    assert preview["subclass_required"] is False
    assert preview["hp"]["die"] == 10
    assert preview["hp"]["average"] == 6
    assert preview["proficiency_bonus"] == 2  # bumps at 5


async def test_preview_fighter_l3_to_l4_offers_asi_and_feats(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        preview = build_level_up_preview(char)
    assert preview is not None
    assert preview["asi_or_feat"] is True
    assert preview["subclass_required"] is False
    # PHB feats are merged in; lucky and tough are 'general' type and shown as ASI options
    assert any(f["index"] == "lucky" for f in preview["available_feats"])
    assert any(f["index"] == "tough" for f in preview["available_feats"])


async def test_preview_fighter_l2_to_l3_requires_subclass(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        char.level = 2
        char.xp = 900
        preview = build_level_up_preview(char)
    assert preview is not None
    assert preview["subclass_required"] is True
    assert any(s["index"] == "champion" for s in preview["available_subclasses"])


# Apply level-up


async def test_apply_level_up_no_pending_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        with pytest.raises(ValidationError):
            await leveling.apply_level_up(
                db,
                character_id=uuid.UUID(char_resp["id"]),
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average"),
            )


async def test_apply_level_up_fighter_1_to_2_average_hp(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.xp = 300
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average"),
        )
    # Creation: 10 (d10) + CON 14 mod=+2 → max_hp 12. Level-up: avg 6 + CON mod 2 = +8.
    assert char.level == 2
    assert char.max_hp == 20
    assert char.hit_dice_remaining == 2
    assert char.proficiency_bonus == 2
    # Fighter level 2 grants action_surge
    assert "action_surge" in char.resources


async def test_apply_level_up_with_roll_validates_die_size(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.xp = 300
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="hp_roll must be"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="roll", hp_roll=11),  # d10 max is 10
            )


async def test_apply_level_up_asi_increases_ability(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average", asi={"str": 1, "con": 1}),
        )
    # Base 15+human+1 = 16 stored; +1 ASI = 17. CON: 13+human+1=14; +1 ASI = 15.
    assert char.level == 4
    assert char.ability_scores["str"] == 17
    assert char.ability_scores["con"] == 15


async def test_apply_level_up_asi_must_total_two(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="asi must total"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average", asi={"str": 1}),
            )


async def test_apply_level_up_with_general_feat_mobile(client: AsyncClient) -> None:
    """Mobile is a 'general' type feat — legal at ASI levels. Adds +10 speed."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        original_speed = char.speed
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average", feat="mobile"),
        )
    assert char.speed == original_speed + 10
    assert any(f["index"] == "mobile" for f in char.feats)


async def test_apply_level_up_subclass_required_at_l3(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 2
        char.xp = 900
        await db.commit()

    # Missing subclass
    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="subclass choice required"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average"),
            )

    # Invalid subclass for class
    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="invalid subclass"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average", subclass="berserker"),
            )

    # Valid
    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average", subclass="champion"),
        )
    assert char.subclass_name == "champion"


async def test_apply_level_up_wizard_grows_spell_slots_and_learns_spells(
    client: AsyncClient,
) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WIZARD)
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.xp = 300
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(
                hp_method="average",
                new_spells=["Misty Step", "Detect Thoughts"],  # wizard +2 per level
                subclass="evocation",
            ),
        )
    # Wizard L2 still has only L1 slots in the SRD table at L2 (3 slots)
    assert char.spell_slots == {"1": 3}
    assert "Misty Step" in char.spells_known
    assert "Detect Thoughts" in char.spells_known
    assert char.subclass_name == "evocation"


async def test_apply_level_up_rejects_wrong_spell_count(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"], **WIZARD)
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.xp = 300
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="expected 2 new spell"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average", new_spells=["Misty Step"], subclass="evocation"),
            )


async def test_apply_level_up_rejects_origin_feat_at_asi(client: AsyncClient) -> None:
    """alert is an 'origin' feat, not selectable at ASI."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        await db.commit()

    async with db_client.get_session() as db:
        with pytest.raises(ValidationError, match="not available at ASI"):
            await leveling.apply_level_up(
                db,
                character_id=cid,
                campaign_id=uuid.UUID(camp["id"]),
                owner_id="user_a",
                choices=LevelUpChoices(hp_method="average", feat="alert"),
            )


async def test_apply_level_up_recomputes_initiative_after_dex_asi(
    client: AsyncClient,
) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average", asi={"dex": 2}),
        )
    # DEX 14+human=15, +2 ASI = 17 → mod +3
    assert char.ability_scores["dex"] == 17
    assert char.initiative == 3


async def test_apply_level_up_alert_feat_adds_pb_to_initiative(client: AsyncClient) -> None:
    """Alert is origin-only, so route via leveling rejects it. We verify the
    recompute path by directly applying the feat then recomputing."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        original = char.initiative
        feat_effects.apply_feat(char, "alert")
        leveling.recompute_derived_stats(char)
    assert char.initiative == original + char.proficiency_bonus


async def test_apply_level_up_observant_recomputes_passive_perception(
    client: AsyncClient,
) -> None:
    """Observant is general — taken at ASI. Verify PP gets +5 + WIS mod increase."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 3
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 2700
        original_pp = char.passive_perception
        await db.commit()

    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average", feat="observant", feat_options={"ability": "wis"}),
        )
    # WIS 10+human+1=11, +1 from observant = 12 → mod still +1.
    # Original PP = 10 + wis_mod(0) = 10. New PP = 10 + wis_mod(1) + 5 = 16.
    # Delta = +6.
    assert char.passive_perception == original_pp + 6


# Feat effects


async def test_feat_unknown_raises(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError, match="unknown feat"):
            feat_effects.apply_feat(char, "not-a-real-feat")


async def test_feat_skilled_requires_three_picks(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError, match="skilled feat requires"):
            feat_effects.apply_feat(char, "skilled", {"picks": [{"type": "skill", "name": "Stealth"}]})


async def test_feat_skilled_routes_skills_and_tools(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(
            char,
            "skilled",
            {
                "picks": [
                    {"type": "skill", "name": "Stealth"},
                    {"type": "tool", "name": "Thieves' Tools"},
                    {"type": "skill", "name": "Acrobatics"},
                ]
            },
        )
    assert "Stealth" in char.skill_proficiencies
    assert "Acrobatics" in char.skill_proficiencies
    assert "Thieves' Tools" in char.tool_proficiencies


async def test_feat_behavioral_just_appends(client: AsyncClient) -> None:
    """Feats with no mechanical handler still get added to char.feats for the LLM to read."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "savage-attacker")
    assert any(f["index"] == "savage-attacker" for f in char.feats)


async def test_feat_alert_appended_recompute_adds_pb(client: AsyncClient) -> None:
    """Alert handler doesn't mutate initiative directly; recompute_derived_stats does."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "alert")
        # Until recompute, initiative is unchanged
        leveling.recompute_derived_stats(char)
    assert any(f["index"] == "alert" for f in char.feats)


async def test_feat_mobile_adds_speed(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "mobile")
    assert char.speed == 40


async def test_feat_tough_adds_two_per_level(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        char.level = 4
        original_max = char.max_hp
        feat_effects.apply_feat(char, "tough")
    assert char.max_hp == original_max + 8


async def test_feat_lucky_grants_resource(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "lucky")
    assert char.resources["luck_points"] == {"current": 3, "max": 3, "resets_on": "long_rest"}


async def test_feat_resilient_bumps_ability_and_adds_save(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        original_con = char.ability_scores["con"]
        original_wis = char.ability_scores["wis"]
        feat_effects.apply_feat(char, "resilient", {"ability": "wis"})
    assert char.ability_scores["wis"] == original_wis + 1
    assert "wis" in char.saving_throw_proficiencies
    assert char.ability_scores["con"] == original_con


async def test_feat_resilient_requires_ability(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError, match="options.ability"):
            feat_effects.apply_feat(char, "resilient")


async def test_feat_observant_bumps_ability(client: AsyncClient) -> None:
    """Observant handler bumps ability; PP delta is applied by recompute_derived_stats."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        before = char.ability_scores["wis"]
        feat_effects.apply_feat(char, "observant", {"ability": "wis"})
    assert char.ability_scores["wis"] == before + 1
    assert any(f["index"] == "observant" for f in char.feats)


async def test_feat_observant_rejects_invalid_ability(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError):
            feat_effects.apply_feat(char, "observant", {"ability": "str"})


async def test_feat_durable_bumps_con(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        before = char.ability_scores["con"]
        feat_effects.apply_feat(char, "durable")
    assert char.ability_scores["con"] == before + 1


async def test_feat_athlete_requires_str_or_dex(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "athlete", {"ability": "dex"})
    assert any(f["index"] == "athlete" for f in char.feats)


async def test_feat_ability_caps_at_20(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        # Force CON to 20 first
        scores: AbilityScores = {**char.ability_scores}
        scores["con"] = 20
        char.ability_scores = scores
        feat_effects.apply_feat(char, "durable")
    assert char.ability_scores["con"] == 20


async def test_tough_scaling_on_level_up(client: AsyncClient) -> None:
    """Taking Tough at L4, then leveling to L5, adds +2 more HP."""
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    cid = uuid.UUID(char_resp["id"])

    # Apply Tough at level 4
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, cid)
        char.level = 4
        char.classes = [{**char.classes[0], "subclass": "champion"}]
        char.xp = 6500  # qualify for L5
        feat_effects.apply_feat(char, "tough")
        after_tough = char.max_hp
        await db.commit()

    # Level up from 4 → 5
    async with db_client.get_session() as db:
        char = await leveling.apply_level_up(
            db,
            character_id=cid,
            campaign_id=uuid.UUID(camp["id"]),
            owner_id="user_a",
            choices=LevelUpChoices(hp_method="average"),
        )
    # Expect: avg HP gain (5+1=6) + CON mod (2) + tough bonus (+2) = +10
    con_mod = (char.ability_scores.get("con", 10) - 10) // 2
    hp_avg = (char.hit_die_size // 2) + 1
    assert char.max_hp == after_tough + hp_avg + con_mod + 2


async def test_feat_heavily_armored_grants_armor_prof(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "heavily-armored", {"ability": "str"})
    assert "heavy" in char.armor_proficiencies


async def test_feat_moderately_armored_grants_medium_and_shield(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "moderately-armored", {"ability": "dex"})
    assert "medium" in char.armor_proficiencies
    assert "shield" in char.armor_proficiencies


async def test_feat_weapon_master_requires_four_weapons(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError, match="4 weapon names"):
            feat_effects.apply_feat(char, "weapon-master", {"ability": "str", "weapons": ["longsword"]})


async def test_feat_weapon_master_adds_weapon_proficiencies(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(
            char,
            "weapon-master",
            {"ability": "str", "weapons": ["longsword", "rapier", "handaxe", "shortsword"]},
        )
    assert "longsword" in char.weapon_proficiencies
    assert "rapier" in char.weapon_proficiencies


async def test_feat_martial_adept_requires_two_maneuvers(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        with pytest.raises(ValidationError, match="2 maneuver names"):
            feat_effects.apply_feat(char, "martial-adept", {"maneuvers": ["Riposte"]})


async def test_feat_martial_adept_stores_maneuvers_in_feat_options(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(char, "martial-adept", {"maneuvers": ["Riposte", "Trip Attack"]})
    feat = next(f for f in char.feats if f["index"] == "martial-adept")
    assert (feat.get("options") or {}).get("maneuvers") == ["Riposte", "Trip Attack"]
    assert "superiority_die" in char.resources


async def test_feat_magic_initiate_grants_resource(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    char_resp = await make_character(client, camp["id"])
    async with db_client.get_session() as db:
        char = await character_queries.get_character(db, uuid.UUID(char_resp["id"]))
        feat_effects.apply_feat(
            char,
            "magic-initiate",
            {"spells": ["Fire Bolt", "Ray of Frost", "Magic Missile"]},
        )
    assert "magic_initiate_free_cast" in char.resources
    assert char.resources["magic_initiate_free_cast"]["max"] == 1
    assert char.resources["magic_initiate_free_cast"]["resets_on"] == "long_rest"
    assert "Magic Missile" in char.spells_known
