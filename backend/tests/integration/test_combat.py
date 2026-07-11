import json
import uuid
from unittest.mock import MagicMock, patch

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import npcs as npc_queries
from cairn.tools import fetch_combat_context
from cairn.tools.combat import advance_turn, apply_damage, apply_effect, start_combat
from tests._factories import make_campaign, make_character, make_session, parse_sse


def _content_response(content: str) -> MagicMock:
    msg = MagicMock()
    msg.tool_calls = None
    msg.content = content
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def _tool_call_response(name: str, args: dict) -> MagicMock:
    tc = MagicMock()
    tc.id = f"tc_{name}"
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    msg = MagicMock()
    msg.tool_calls = [tc]
    msg.content = None
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message = msg
    resp.usage = MagicMock()
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


async def _fake_stream():
    for text in ["The fighter ", "strikes!"]:
        chunk = MagicMock()
        chunk.choices = [MagicMock()]
        chunk.choices[0].delta.content = text
        yield chunk


async def test_start_combat_initialises_state(client: AsyncClient) -> None:
    """start_combat tool creates expected state: effects list, team fields, sorted initiative."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    result = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin", "count": 2}]',
        }
    )

    assert result.get("combat_started") is True
    state = result["combat_state"]

    assert state["effects"] == []

    for c in state["combatants"]:
        assert "team" in c, f"combatant {c['name']} missing team field"

    fighter = next(c for c in state["combatants"] if c["name"] == "Ser Aldric")
    assert fighter["team"] == "players"

    goblins = [c for c in state["combatants"] if "Goblin" in c["name"]]
    assert len(goblins) == 2
    for g in goblins:
        assert g["team"] == "enemies"

    rolls = [c["initiative_roll"] for c in state["combatants"]]
    assert rolls == sorted(rolls, reverse=True)


async def test_start_combat_falls_back_to_open_ground_and_places_everyone(client: AsyncClient) -> None:
    """A bad zone-seeder response cannot block combat or leave combatants unplaced."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    result = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )

    state = result["combat_state"]
    assert state["zones"] == [
        {
            "id": "open_ground",
            "name": "Open Ground",
            "description": "An open area with no meaningful tactical divisions.",
            "cover": "none",
            "cover_ac_bonus": 0,
            "cover_save_bonus": 0,
            "difficult_terrain": False,
            "hazard": None,
            "distances": {},
        }
    ]
    assert {combatant["zone"] for combatant in state["combatants"]} == {"open_ground"}


async def test_start_combat_seeds_first_turn_movement_from_character_speed(client: AsyncClient) -> None:
    """The opening combatant can move using its real Speed without a 30ft default."""
    camp = await make_campaign(client)
    dwarf = await make_character(client, camp["id"], race="dwarf", subrace="hill-dwarf")
    sess = await make_session(client, camp["id"])

    result = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": "[]",
        }
    )

    state = result["combat_state"]
    combatant = next(item for item in state["combatants"] if item["id"] == dwarf["id"])
    assert combatant["speed"] == 25
    assert state["turn_economy"][dwarf["id"]]["movement_remaining"] == 25


async def test_apply_damage_reduces_hp(client: AsyncClient) -> None:
    """apply_damage reduces monster HP tracked in combat_state."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    started = await start_combat.ainvoke(
        {
            "session_id": sess["id"],
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    goblin = next(c for c in started["combat_state"]["combatants"] if c["type"] == "monster")

    result = await apply_damage.ainvoke(
        {
            "session_id": sess["id"],
            "combatant_id": goblin["id"],
            "combatant_type": "monster",
            "amount": 5,
            "damage_type": "slashing",
        }
    )

    assert result["damage_taken"] == 5
    assert result["hp"] == max(0, goblin["hp"] - 5)


async def test_advance_turn_ticks_and_expires_effects(client: AsyncClient) -> None:
    """advance_turn at end of goblin's turn triggers and expires a 1-round effect."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    session_id = sess["id"]

    started = await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )
    goblin = next(c for c in started["combat_state"]["combatants"] if c["type"] == "monster")

    await apply_effect.ainvoke(
        {
            "session_id": session_id,
            "target_id": goblin["id"],
            "effect_name": "Bane",
            "duration_rounds": 1,
            "tick": "end_of_target_turn",
            "save_ability": "cha",
            "save_dc": 13,
            "mechanical_notes": "On save, effect ends.",
        }
    )

    state = started["combat_state"]
    result = None
    for _ in range(len(state["combatants"]) + 1):
        result = await advance_turn.ainvoke({"session_id": session_id})
        if result.get("end_of_turn_ticks") or result.get("expired_effects"):
            break

    assert result is not None
    assert "Bane" in result.get("expired_effects", [])


async def test_full_combat_turn_emits_sse_events(client: AsyncClient) -> None:
    """Submit a combat turn: verify SSE turn_start, token, and turn_end are emitted."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": '[{"type": "monster", "name": "goblin"}]',
        }
    )

    async def _fake_acompletion(model: str, messages: list, stream: bool = False, **kwargs):  # type: ignore[return]
        if stream:
            return _fake_stream()
        prompt = messages[-1]["content"]
        actor_id = next(
            combatant["id"]
            for combatant in (await fetch_combat_context(session_id))[0]["combatants"]
            if combatant["name"] in prompt
        )
        return _content_response(
            json.dumps(
                {
                    "operations": [{"kind": "advance_turn", "actor_id": actor_id}],
                    "summary": "Advance after the planned action.",
                }
            )
        )

    with patch("litellm.acompletion", side_effect=_fake_acompletion):
        r = await client.post(
            f"/v1/sessions/{session_id}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I attack the goblin with my longsword!"},
        )

    assert r.status_code == 201
    events = parse_sse(r.text)
    event_types = [e["type"] for e in events]

    assert "turn_start" in event_types
    assert "turn_end" in event_types
    assert any(e["type"] == "token" for e in events)

    turn_start = next(e for e in events if e["type"] == "turn_start")
    assert turn_start["data"]["intent"] == "combat_action"


async def test_combat_start_route_removed_get_state_still_works(client: AsyncClient) -> None:
    """Combat now starts inside the turn graph — the client-facing start route is gone, but the
    read endpoint the UI tracker uses remains."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])

    started = await client.post(
        f"/v1/sessions/{sess['id']}/combat/start",
        headers={"X-User-Id": "user_a"},
        json={"enemies": [{"type": "monster", "name": "goblin"}]},
    )
    assert started.status_code == 404

    state = await client.get(f"/v1/sessions/{sess['id']}/combat", headers={"X-User-Id": "user_a"})
    assert state.status_code == 200
    assert state.json()["combat_active"] is False


async def test_ally_npc_enrolled_with_players_team(client: AsyncClient) -> None:
    """An NPC enrolled with team='players' gets the correct team in combat state."""
    camp = await make_campaign(client)
    await make_character(client, camp["id"])
    sess = await make_session(client, camp["id"])
    session_id = sess["id"]

    async with db_client.get_session() as db:
        npc = await npc_queries.create_npc(
            db,
            campaign_id=uuid.UUID(camp["id"]),
            name="Hired Guard",
            race="Human",
            narrative_profile={"name": "Hired Guard", "personality": "Quiet and professional."},
            hp=12,
            max_hp=12,
            ac=13,
            initiative=1,
        )
        await db.commit()
        npc_id = str(npc.id)

    result = await start_combat.ainvoke(
        {
            "session_id": session_id,
            "enemies_json": json.dumps(
                [
                    {"type": "monster", "name": "goblin"},
                    {"type": "npc", "id": npc_id, "team": "players"},
                ]
            ),
        }
    )

    assert result.get("combat_started") is True
    ally = next(c for c in result["combat_state"]["combatants"] if c["name"] == "Hired Guard")
    assert ally["team"] == "players"

    enemy = next(c for c in result["combat_state"]["combatants"] if "Goblin" in c["name"])
    assert enemy["team"] == "enemies"
