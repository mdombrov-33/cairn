import uuid
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient

from cairn.application.combat.zones import fallback_seed
from cairn.db import client as db_client
from cairn.db.queries import characters as character_queries
from cairn.tools.combat import start_combat
from cairn.tools.resources import adjust_resource, adjust_spell_slot, use_economy
from tests._factories import make_campaign, make_character, make_session


async def test_adjust_resource_and_spell_slot_preserve_both_directions(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    character = await make_character(client, campaign["id"])
    character_id = uuid.UUID(character["id"])
    async with db_client.get_session() as db:
        persisted = await character_queries.get_character(db, character_id)
        persisted.spell_slots = {"1": 3}
        persisted.resources = {"action_surge": {"current": 2, "max": 3, "resets_on": "short_rest"}}

    spent_slot = await adjust_spell_slot.ainvoke({"character_id": character["id"], "level": 1, "delta": -2})
    restored_slot = await adjust_spell_slot.ainvoke({"character_id": character["id"], "level": 1, "delta": 1})
    spent_resource = await adjust_resource.ainvoke(
        {"character_id": character["id"], "resource": "action_surge", "delta": -2}
    )
    restored_resource = await adjust_resource.ainvoke(
        {"character_id": character["id"], "resource": "action_surge", "delta": 1}
    )

    assert spent_slot["slots_remaining"] == 1
    assert restored_slot["slots_remaining"] == 2
    assert spent_resource["uses_remaining"] == 0
    assert restored_resource["uses_remaining"] == 1
    assert await adjust_spell_slot.ainvoke({"character_id": character["id"], "level": 1, "delta": 0}) == {
        "error": "delta must not be zero."
    }
    assert await adjust_resource.ainvoke({"character_id": character["id"], "resource": "action_surge", "delta": 0}) == {
        "error": "delta must not be zero."
    }


async def test_use_economy_covers_all_three_previous_tools(client: AsyncClient) -> None:
    campaign = await make_campaign(client)
    character = await make_character(client, campaign["id"])
    game_session = await make_session(client, campaign["id"])
    with patch("cairn.agents.zone_seeder.run", new=AsyncMock(return_value=fallback_seed())):
        await start_combat.ainvoke({"session_id": game_session["id"], "enemies_json": "[]"})

    action = await use_economy.ainvoke(
        {"session_id": game_session["id"], "combatant_id": character["id"], "economy_type": "action"}
    )
    bonus_action = await use_economy.ainvoke(
        {"session_id": game_session["id"], "combatant_id": character["id"], "economy_type": "bonus_action"}
    )
    reaction = await use_economy.ainvoke(
        {"session_id": game_session["id"], "combatant_id": character["id"], "economy_type": "reaction"}
    )

    assert action["action_used"] is True
    assert bonus_action["bonus_action_used"] is True
    assert reaction["reaction_used"] is True
