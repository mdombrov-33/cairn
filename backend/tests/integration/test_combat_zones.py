"""Tactical-zone behavior through the public combat tools."""

import copy
import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.db.queries import sessions as session_queries
from cairn.domain.combat import ZoneSeed
from cairn.tools.combat import (
    apply_aoe_damage,
    apply_damage,
    cast_concentration_spell,
    get_combatants_in_zone,
    get_zones_in_range,
    move_combatant,
    set_condition,
    start_combat,
)
from tests._factories import make_campaign, make_character, make_session

TAVERN_ZONES: ZoneSeed = {
    "zones": [
        {
            "id": "tavern_front",
            "name": "Tavern Front",
            "description": "Open floor by the door.",
            "cover": "none",
            "cover_ac_bonus": 0,
            "cover_save_bonus": 0,
            "difficult_terrain": False,
            "hazard": None,
            "distances": {"behind_bar": "close"},
        },
        {
            "id": "behind_bar",
            "name": "Behind the Bar",
            "description": "A cramped lane behind solid oak.",
            "cover": "half",
            "cover_ac_bonus": 2,
            "cover_save_bonus": 2,
            "difficult_terrain": False,
            "hazard": None,
            "distances": {"tavern_front": "close"},
        },
        {
            "id": "stairs",
            "name": "Stairs",
            "description": "A narrow staircase overlooking the room.",
            "cover": "three_quarters",
            "cover_ac_bonus": 5,
            "cover_save_bonus": 5,
            "difficult_terrain": False,
            "hazard": None,
            "distances": {"tavern_front": "far"},
        },
    ],
    "player_start": "tavern_front",
    "enemy_start": "behind_bar",
}


async def test_dwarf_cannot_move_farther_than_remaining_speed(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    dwarf = await make_character(client, camp["id"], race="dwarf", subrace="hill-dwarf")
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        await start_combat.ainvoke({"session_id": sess["id"], "enemies_json": "[]"})

    result = await move_combatant.ainvoke(
        {"session_id": sess["id"], "combatant_id": dwarf["id"], "target_zone": "behind_bar"}
    )

    assert result == {"error": "Behind the Bar costs 30ft; only 25ft of movement remains."}


async def test_wood_elf_can_make_close_hop_with_five_feet_remaining(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    wood_elf = await make_character(client, camp["id"], race="elf", subrace="wood-elf")
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        await start_combat.ainvoke({"session_id": sess["id"], "enemies_json": "[]"})

    result = await move_combatant.ainvoke(
        {"session_id": sess["id"], "combatant_id": wood_elf["id"], "target_zone": "behind_bar"}
    )

    assert result["to_zone"] == "behind_bar"
    assert result["movement_spent"] == 30
    assert result["movement_remaining"] == 5


async def test_difficult_terrain_doubles_a_zone_hop_cost(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    wood_elf = await make_character(client, camp["id"], race="elf", subrace="wood-elf")
    sess = await make_session(client, camp["id"])
    seed = copy.deepcopy(TAVERN_ZONES)
    seed["zones"][1]["difficult_terrain"] = True

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=seed)):
        await start_combat.ainvoke({"session_id": sess["id"], "enemies_json": "[]"})

    result = await move_combatant.ainvoke(
        {"session_id": sess["id"], "combatant_id": wood_elf["id"], "target_zone": "behind_bar"}
    )

    assert result == {"error": "Behind the Bar costs 60ft; only 35ft of movement remains."}


async def test_grappled_combatant_cannot_move(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    fighter = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        await start_combat.ainvoke({"session_id": sess["id"], "enemies_json": "[]"})

    await set_condition.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": fighter["id"],
            "condition": "grappled",
            "active": True,
        }
    )

    result = await move_combatant.ainvoke(
        {"session_id": sess["id"], "combatant_id": fighter["id"], "target_zone": "behind_bar"}
    )

    assert result == {"error": "Ser Aldric cannot move while grappled."}

    removed = await set_condition.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": fighter["id"],
            "condition": "grappled",
            "active": False,
        }
    )
    assert removed["conditions"] == []


async def test_zone_queries_expose_occupants_and_reachable_regions(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )

    occupants = await get_combatants_in_zone.ainvoke({"session_id": sess["id"], "zone_id": "behind_bar"})
    reachable = await get_zones_in_range.ainvoke(
        {"session_id": sess["id"], "from_zone": "tavern_front", "range_category": "close"}
    )

    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")
    assert [item["id"] for item in occupants["combatants"]] == [goblin["id"]]
    assert [zone["id"] for zone in reachable["zones"]] == ["behind_bar"]


async def test_leaving_enemy_zone_triggers_opportunity_attack(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    fighter = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    seed = copy.deepcopy(TAVERN_ZONES)
    seed["enemy_start"] = "tavern_front"

    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        session.rng_seed = 0  # Goblin rolls 13 + 4 to hit, then 1d6+2 damage.
        await db.commit()

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=seed)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    result = await move_combatant.ainvoke(
        {"session_id": sess["id"], "combatant_id": fighter["id"], "target_zone": "behind_bar"}
    )

    assert result["to_zone"] == "behind_bar"
    assert result["opportunity_attacks"] == [
        {
            "attacker_id": goblin["id"],
            "attacker": "Goblin",
            "attack": "Scimitar",
            "attack_roll": 13,
            "attack_total": 17,
            "hit": True,
            "damage": 6,
        }
    ]
    async with db_client.get_session() as db:
        session = await session_queries.get_session(db, uuid.UUID(sess["id"]))
        assert session.combat_state is not None
        assert session.combat_state["turn_economy"][goblin["id"]]["reaction_used"] is True
        persisted = await character_queries.get_character(db, uuid.UUID(fighter["id"]))
        assert persisted.hp == fighter["hp"] - 6


async def test_melee_damage_is_rejected_across_zones(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    fighter = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    result = await apply_damage.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": goblin["id"],
            "combatant_type": "monster",
            "amount": 5,
            "damage_type": "slashing",
            "attacker_id": fighter["id"],
            "weapon_range_ft": 5,
        }
    )

    assert result == {"error": "Goblin is out of range for a 5ft attack."}


async def test_subdual_damage_requires_same_zone(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    fighter = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    result = await apply_damage.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": goblin["id"],
            "combatant_type": "monster",
            "amount": 99,
            "subdue": True,
            "attacker_id": fighter["id"],
        }
    )

    assert result == {"error": "Subdual damage requires the attacker and target to share a zone."}


async def test_touch_concentration_spell_is_rejected_across_zones(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    caster = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=TAVERN_ZONES)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    result = await cast_concentration_spell.ainvoke(
        {
            "session_id": sess["id"],
            "caster_id": caster["id"],
            "caster_type": "character",
            "spell_name": "Imaginary Touch Spell",
            "level": 1,
            "target_id": goblin["id"],
            "effect_name": "Touched",
            "duration_rounds": 1,
            "spell_range_ft": 5,
        }
    )

    assert result == {"error": "Goblin is out of range for a 5ft spell."}


async def test_aoe_spell_targets_all_occupants_of_its_origin_zone(client: AsyncClient) -> None:
    camp = await make_campaign(client)
    caster = await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    seed = copy.deepcopy(TAVERN_ZONES)
    seed["player_start"] = "stairs"
    seed["zones"][2]["distances"]["behind_bar"] = "far"

    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=seed)):
        started = await start_combat.ainvoke(
            {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
        )
    goblin = next(item for item in started["combat_state"]["combatants"] if item["type"] == "monster")

    result = await apply_aoe_damage.ainvoke(
        {
            "session_id": sess["id"],
            "targets_json": "[]",
            "damage_dice": "1d6",
            "save_ability": "dex",
            "save_dc": 30,
            "caster_id": caster["id"],
            "origin_zone": "behind_bar",
            "spell_range_ft": 150,
        }
    )

    assert result["origin_zone"] == "behind_bar"
    assert [entry["combatant"] for entry in result["results"]] == [goblin["name"]]
    assert result["results"][0]["cover_save_bonus"] == 2
