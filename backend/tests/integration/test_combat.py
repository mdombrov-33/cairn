import json
import uuid
from unittest.mock import MagicMock, patch

from httpx import AsyncClient

from cairn.db import client as db_client
from cairn.db.queries import npcs as npc_queries
from cairn.mcp.tools.combat import advance_turn, apply_damage, apply_effect, start_combat

FIGHTER: dict = {
    "name": "Ser Aldric",
    "race": "Human",
    "character_class": "Fighter",
    "background": "Soldier",
    "level": 3,
    "stats": {"str": 16, "dex": 12, "con": 14, "int": 8, "wis": 10, "cha": 13},
    "hp": 28,
    "max_hp": 28,
    "ac": 16,
    "speed": 30,
    "saving_throw_proficiencies": ["str", "con"],
    "skill_proficiencies": ["athletics", "perception"],
    "features": ["Action Surge", "Second Wind"],
    "inventory": [{"name": "Longsword", "quantity": 1, "weight": 3, "notes": "", "equipped": True}],
    "currency": {"gp": 10, "sp": 0, "cp": 0},
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


def _parse_sse(text: str) -> list[dict]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.strip().splitlines()
        event, data = None, None
        for line in lines:
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                raw = line[len("data:") :].strip()
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = raw
        if event:
            events.append({"event": event, "data": data})
    return events


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
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

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


async def test_apply_damage_reduces_hp(client: AsyncClient) -> None:
    """apply_damage reduces monster HP tracked in combat_state."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])

    started = await start_combat.ainvoke(
        {"session_id": sess["id"], "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
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
    assert result["hp"] == goblin["hp"] - 5


async def test_advance_turn_ticks_and_expires_effects(client: AsyncClient) -> None:
    """advance_turn at end of goblin's turn triggers and expires a 1-round effect."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    started = await start_combat.ainvoke(
        {"session_id": session_id, "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
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

    # Navigate to goblin's turn then advance past it to trigger end-of-turn tick
    state = started["combat_state"]
    result = None
    for _ in range(len(state["combatants"]) + 1):
        result = await advance_turn.ainvoke({"session_id": session_id})
        # If the outgoing combatant was the goblin, end_of_turn_ticks fired for it
        if result.get("end_of_turn_ticks") or result.get("expired_effects"):
            break

    assert result is not None
    assert "Bane" in result.get("expired_effects", [])


async def test_full_combat_turn_emits_sse_events(client: AsyncClient) -> None:
    """Submit a combat turn: verify SSE turn_start, token, and turn_end are emitted."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    await start_combat.ainvoke(
        {"session_id": session_id, "enemies_json": '[{"type": "monster", "name": "goblin"}]'}
    )

    call_count = {"n": 0}

    async def _fake_acompletion(model: str, messages: list, stream: bool = False, **kwargs):  # type: ignore[return]
        call_count["n"] += 1
        if stream:
            return _fake_stream()
        if call_count["n"] % 2 == 1:
            return _tool_call_response("advance_turn", {"session_id": session_id})
        return _content_response(
            json.dumps({"resolved": True, "summary": "Fighter swings, goblin takes damage."})
        )

    with patch("litellm.acompletion", side_effect=_fake_acompletion):
        r = await client.post(
            f"/v1/sessions/{session_id}/turns",
            headers={"X-User-Id": "user_a"},
            json={"player_input": "I attack the goblin with my longsword!"},
        )

    assert r.status_code == 201
    events = _parse_sse(r.text)
    event_types = [e["event"] for e in events]

    assert "turn_start" in event_types
    assert "turn_end" in event_types
    assert any(e["event"] == "token" for e in events)

    turn_start = next(e for e in events if e["event"] == "turn_start")
    assert turn_start["data"]["intent"] == "combat_action"


async def test_ally_npc_enrolled_with_players_team(client: AsyncClient) -> None:
    """An NPC enrolled with team='players' gets the correct team in combat state."""
    camp = await _campaign(client)
    await _character(client, camp["id"])
    sess = await _session(client, camp["id"])
    session_id = sess["id"]

    async with db_client.get_session() as db:
        npc = await npc_queries.create_npc(
            db,
            campaign_id=uuid.UUID(camp["id"]),
            name="Hired Guard",
            race="Human",
            bio="A reliable sellsword.",
            personality="Quiet and professional.",
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
