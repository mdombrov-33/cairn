import pytest

from cairn.agents import combat_resolver
from cairn.agents.combat_ai import CompanionProposal
from cairn.context import using_campaign_settings


@pytest.fixture
def companion_turn() -> tuple[dict, list[dict]]:
    combat_state = {
        "turn_index": 0,
        "combatants": [
            {
                "id": "companion-1",
                "name": "Wrenna",
                "type": "character",
                "team": "players",
                "is_alive": True,
                "ai_controlled": True,
            }
        ],
    }
    party = [{"id": "companion-1", "name": "Wrenna", "is_companion": True}]
    return combat_state, party


async def test_suggest_mode_pauses_before_companion_tools(
    monkeypatch: pytest.MonkeyPatch,
    companion_turn: tuple[dict, list[dict]],
) -> None:
    async def fake_mechanics(*args, **kwargs) -> str:
        return "Aldric strikes and advances the turn."

    async def fake_context(session_id: str) -> tuple[dict, list[dict]]:
        return companion_turn

    async def fake_proposal(session_id: str) -> CompanionProposal:
        return CompanionProposal(action="shoot the warden", narration="Say the word and I loose.")

    monkeypatch.setattr(combat_resolver, "_resolve_mechanics", fake_mechanics)
    monkeypatch.setattr(combat_resolver, "fetch_combat_context", fake_context)
    monkeypatch.setattr(combat_resolver.combat_ai, "propose", fake_proposal)

    with using_campaign_settings({"companion": {"combat": "suggest"}}):
        context, proposal = await combat_resolver.resolve("strike the warden", "session-1")

    assert context == "[PLAYER ACTION]\nAldric strikes and advances the turn."
    assert proposal == {
        "combatant_id": "companion-1",
        "combatant_name": "Wrenna",
        "action": "shoot the warden",
        "narration": "Say the word and I loose.",
    }


async def test_player_mode_stops_on_companion_turn(
    monkeypatch: pytest.MonkeyPatch,
    companion_turn: tuple[dict, list[dict]],
) -> None:
    async def fake_mechanics(*args, **kwargs) -> str:
        return "Aldric strikes and advances the turn."

    async def fake_context(session_id: str) -> tuple[dict, list[dict]]:
        return companion_turn

    monkeypatch.setattr(combat_resolver, "_resolve_mechanics", fake_mechanics)
    monkeypatch.setattr(combat_resolver, "fetch_combat_context", fake_context)

    with using_campaign_settings({"companion": {"combat": "player"}}):
        context, proposal = await combat_resolver.resolve("strike the warden", "session-1")

    assert context == "[PLAYER ACTION]\nAldric strikes and advances the turn."
    assert proposal is None
