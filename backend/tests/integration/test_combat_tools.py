import json
import uuid
from unittest.mock import patch

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.tools.combat import (
    add_combatant,
    add_exhaustion,
    advance_turn,
    apply_aoe_damage,
    apply_damage,
    apply_temp_hp,
    award_xp,
    remove_combatant,
    remove_exhaustion,
    resolve_contest,
    roll_initiative,
    roll_saving_throw,
    roll_skill_check,
    stabilize_character,
    start_combat,
)

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


async def _campaign(client: AsyncClient) -> dict:
    r = await client.post(
        "/v1/campaigns",
        headers={"X-User-Id": "user_a"},
        json={"name": "Test", "template_id": "tavern_v1"},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _character(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/characters",
        headers={"X-User-Id": "user_a"},
        json=FIGHTER,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _session(client: AsyncClient, campaign_id: str) -> dict:
    r = await client.post(
        f"/v1/campaigns/{campaign_id}/sessions",
        headers={"X-User-Id": "user_a"},
    )
    assert r.status_code == 201, r.text
    return r.json()


# roll_saving_throw


async def test_roll_saving_throw_character_returns_expected_fields(client: AsyncClient) -> None:
    """roll_saving_throw for a character returns roll, modifier, total, dc, and success."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    result = await roll_saving_throw.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": char["id"],
            "combatant_type": "character",
            "ability": "con",
            "dc": 15,
        }
    )

    assert result["combatant"] == "Ser Aldric"
    assert result["ability"] == "con"
    assert isinstance(result["rolls"], list) and len(result["rolls"]) == 1
    assert isinstance(result["modifier"], int)
    assert result["dc"] == 15
    assert isinstance(result["success"], bool)
    assert result["total"] == result["rolls"][0] + result["modifier"]


async def test_roll_saving_throw_monster_reads_srd_data(client: AsyncClient) -> None:
    """roll_saving_throw for a monster uses SRD ability scores and returns correct fields."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    started = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    goblin = next(c for c in started["combat_state"]["combatants"] if c["type"] == "monster")

    result = await roll_saving_throw.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": goblin["id"],
            "combatant_type": "monster",
            "ability": "dex",
            "dc": 12,
        }
    )

    assert result["combatant"] == goblin["name"]
    assert result["ability"] == "dex"
    assert isinstance(result["modifier"], int)
    assert isinstance(result["success"], bool)
    assert result["total"] == result["rolls"][0] + result["modifier"]


# roll_skill_check


async def test_roll_skill_check_proficient_character_applies_bonus(client: AsyncClient) -> None:
    """Fighter with Perception proficiency gets wis_mod(0) + prof_bonus(2) = modifier 2."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    result = await roll_skill_check.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": char["id"],
            "combatant_type": "character",
            "skill": "Perception",
            "dc": 12,
        }
    )

    assert result["combatant"] == "Ser Aldric"
    assert result["skill"] == "Perception"
    assert result["ability"] == "wis"
    assert result["modifier"] == 2  # wis_mod 0 + proficiency_bonus 2
    assert isinstance(result["success"], bool)
    assert result["total"] == result["rolls"][0] + result["modifier"]


async def test_roll_skill_check_unknown_skill_returns_error(client: AsyncClient) -> None:
    """roll_skill_check with an unrecognized skill name returns an error dict."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    result = await roll_skill_check.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": char["id"],
            "combatant_type": "character",
            "skill": "Bluffing",
            "dc": 10,
        }
    )

    assert "error" in result


# resolve_contest


async def test_resolve_contest_tie_goes_to_defender(client: AsyncClient) -> None:
    """When both totals are equal, the defender wins (PHB p. 174)."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )

    # Using the same combatant for both sides guarantees equal modifiers.
    # Patching roll_d20 to return the same value ensures totals tie.
    with patch("cairn.domain.services.combat.rolls.roll_d20", return_value=([10], 10)):
        result = await resolve_contest.ainvoke(
            {
                "session_id": sess["id"],
                "attacker_id": char["id"],
                "attacker_type": "character",
                "attacker_skill": "Athletics",
                "defender_id": char["id"],
                "defender_type": "character",
                "defender_skill": "Athletics",
            }
        )

    assert result["tied"] is True
    assert result["winner"] == "Ser Aldric"  # defender wins on tie


#
# apply_aoe_damage


async def test_apply_aoe_damage_all_fail_take_full_damage(client: AsyncClient) -> None:
    """With DC 30, all targets fail saves and each takes the full shared damage roll."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    started = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin", "count": 2}]',
        }
    )
    goblins = [c for c in started["combat_state"]["combatants"] if c["type"] == "monster"]
    targets_json = json.dumps([{"id": g["id"], "type": "monster"} for g in goblins])

    result = await apply_aoe_damage.ainvoke(
        {
            "session_id": sess["id"],
            "targets_json": targets_json,
            "damage_dice": "2d6",
            "save_ability": "dex",
            "save_dc": 30,
            "damage_type": "fire",
            "half_on_save": True,
        }
    )

    assert "damage_roll" in result
    assert len(result["results"]) == 2
    for r in result["results"]:
        assert r["saved"] is False
        assert r["damage"] == result["damage_roll"]


async def test_apply_aoe_damage_all_save_take_half(client: AsyncClient) -> None:
    """With DC 0, all targets save and take half damage (half_on_save=True)."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    started = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin", "count": 2}]',
        }
    )
    goblins = [c for c in started["combat_state"]["combatants"] if c["type"] == "monster"]
    targets_json = json.dumps([{"id": g["id"], "type": "monster"} for g in goblins])

    # Fix damage roll to an even number so half is exact.
    with patch("cairn.domain.services.combat.mutations.parse_and_roll", return_value=8):
        result = await apply_aoe_damage.ainvoke(
            {
                "session_id": sess["id"],
                "targets_json": targets_json,
                "damage_dice": "2d6",
                "save_ability": "dex",
                "save_dc": 0,
                "damage_type": "fire",
                "half_on_save": True,
            }
        )

    assert result["damage_roll"] == 8
    for r in result["results"]:
        assert r["saved"] is True
        assert r["damage"] == 4


# add_combatant / remove_combatant (turn_index correctness)


async def test_add_combatant_before_active_increments_turn_index(client: AsyncClient) -> None:
    """Inserting a combatant before the current turn position increments turn_index."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    # turn_index starts at 0. Advance once → turn_index becomes 1.
    await advance_turn.ainvoke({"session_id": session_id})

    # Insert a combatant with an initiative high enough to land at position 0.
    result = await add_combatant.ainvoke(
        {
            "session_id": session_id,
            "combatant_type": "monster",
            "name_or_id": "goblin",
            "initiative_roll": 9999,
            "team": "enemies",
        }
    )
    assert result["combatant_added"] is True
    assert result["position"] == 0

    # turn_index must have shifted from 1 to 2 to keep pointing at the same combatant.
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
    state = session.combat_state
    assert state is not None
    assert state["turn_index"] == 2


async def test_remove_combatant_before_active_decrements_turn_index(client: AsyncClient) -> None:
    """Removing a combatant before the current turn position decrements turn_index."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    started = await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    combatants = started["combat_state"]["combatants"]
    first = combatants[0]  # highest initiative, at index 0
    second = combatants[1]  # at index 1

    # Advance to index 1 so first is behind the active combatant.
    await advance_turn.ainvoke({"session_id": session_id})

    result = await remove_combatant.ainvoke({"session_id": session_id, "combatant_id": first["id"]})
    assert result["combatant_removed"] is True

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(session_id))
    state = session.combat_state
    assert state is not None
    # turn_index decremented from 1 to 0, still pointing at the same (second) combatant.
    assert state["turn_index"] == 0
    assert state["combatants"][0]["id"] == second["id"]


# add_exhaustion / remove_exhaustion


async def test_add_exhaustion_tracks_level_in_conditions(client: AsyncClient) -> None:
    """add_exhaustion stores exhaustion-N in conditions and reports the level."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    result = await add_exhaustion.ainvoke({"character_id": char["id"], "levels": 2})

    assert result["exhaustion_level"] == 2
    assert result["dead"] is False
    assert "exhaustion-2" in result["conditions"]


async def test_add_exhaustion_level_6_kills_character(client: AsyncClient) -> None:
    """Reaching exhaustion 6 sets hp=0 and status=dead on the character."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    await add_exhaustion.ainvoke({"character_id": char["id"], "levels": 5})
    result = await add_exhaustion.ainvoke({"character_id": char["id"], "levels": 1})

    assert result["exhaustion_level"] == 6
    assert result["dead"] is True

    async with db_client.get_session() as db:
        char_db = await character_queries.get_character(db, uuid.UUID(char["id"]))
    assert char_db.hp == 0
    assert char_db.status == "dead"


async def test_remove_exhaustion_reduces_level(client: AsyncClient) -> None:
    """remove_exhaustion decrements the exhaustion-N condition by the given amount."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    await add_exhaustion.ainvoke({"character_id": char["id"], "levels": 3})
    result = await remove_exhaustion.ainvoke({"character_id": char["id"], "levels": 2})

    assert result["exhaustion_level"] == 1
    assert "exhaustion-1" in result["conditions"]


# stabilize_character


async def test_stabilize_character_clears_death_save_counters(client: AsyncClient) -> None:
    """stabilize_character resets death_save counters for a character at 0 HP."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    # Bring character to 0 HP.
    await apply_damage.ainvoke(
        {
            "session_id": session_id,
            "combatant_id": char["id"],
            "combatant_type": "character",
            "amount": 9999,
            "damage_type": "bludgeoning",
        }
    )

    result = await stabilize_character.ainvoke({"character_id": char["id"]})

    assert result["stabilized"] is True
    assert result["hp"] == 0

    async with db_client.get_session() as db:
        char_db = await character_queries.get_character(db, uuid.UUID(char["id"]))
    assert char_db.death_save_successes == 0
    assert char_db.death_save_failures == 0


# apply_temp_hp (no-stack rule)


async def test_apply_temp_hp_lower_amount_does_not_replace(client: AsyncClient) -> None:
    """Granting temp HP lower than current temp HP leaves temp HP unchanged."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )

    r1 = await apply_temp_hp.ainvoke(
        {
            "session_id": session_id,
            "combatant_id": char["id"],
            "combatant_type": "character",
            "amount": 5,
        }
    )
    assert r1["temp_hp"] == 5
    assert r1["replaced"] is True

    r2 = await apply_temp_hp.ainvoke(
        {
            "session_id": session_id,
            "combatant_id": char["id"],
            "combatant_type": "character",
            "amount": 3,
        }
    )
    assert r2["temp_hp"] == 5  # unchanged
    assert r2["replaced"] is False


async def test_apply_temp_hp_higher_amount_replaces(client: AsyncClient) -> None:
    """Granting temp HP higher than current temp HP replaces it."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    await apply_temp_hp.ainvoke(
        {
            "session_id": session_id,
            "combatant_id": char["id"],
            "combatant_type": "character",
            "amount": 5,
        }
    )

    r = await apply_temp_hp.ainvoke(
        {
            "session_id": session_id,
            "combatant_id": char["id"],
            "combatant_type": "character",
            "amount": 10,
        }
    )
    assert r["temp_hp"] == 10
    assert r["replaced"] is True


# award_xp


async def test_award_xp_accumulates_correctly(client: AsyncClient) -> None:
    """award_xp accumulates across calls and returns updated xp and level."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])

    r1 = await award_xp.ainvoke({"character_id": char["id"], "amount": 100})
    assert r1["xp"] == 100
    assert r1["level"] == 1

    r2 = await award_xp.ainvoke({"character_id": char["id"], "amount": 200})
    assert r2["xp"] == 300


# roll_initiative


async def test_roll_initiative_character_returns_expected_fields(client: AsyncClient) -> None:
    """roll_initiative for a character returns rolls, modifier, and initiative total."""
    camp = await _campaign(client)
    char = await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    result = await roll_initiative.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": char["id"],
            "combatant_type": "character",
        }
    )

    assert result["combatant"] == "Ser Aldric"
    assert isinstance(result["rolls"], list) and len(result["rolls"]) == 1
    assert isinstance(result["modifier"], int)
    assert result["initiative"] == result["rolls"][0] + result["modifier"]
