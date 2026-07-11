import pytest

from cairn.agents import combat_resolver
from cairn.agents.combat_ai import CompanionProposal
from cairn.application.combat.executor import ExecutionComplete
from cairn.application.combat.plan import CombatPlan
from cairn.context import using_campaign_settings
from cairn.domain.services.settings import resolve_settings


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
    async def fake_plan(*args, **kwargs) -> CombatPlan:
        return CombatPlan(operations=())

    async def fake_execute(*args, **kwargs) -> ExecutionComplete:
        return ExecutionComplete(facts=("Aldric strikes and advances the turn.",))

    async def fake_context(session_id: str) -> tuple[dict, list[dict]]:
        return companion_turn

    async def fake_proposal(session_id: str) -> CompanionProposal:
        return CompanionProposal(action="shoot the warden", narration="Say the word and I loose.")

    monkeypatch.setattr(combat_resolver, "_plan", fake_plan)
    monkeypatch.setattr(combat_resolver, "_execute_plan", fake_execute)
    monkeypatch.setattr(combat_resolver, "fetch_combat_context", fake_context)
    monkeypatch.setattr(combat_resolver.combat_ai, "propose", fake_proposal)

    with using_campaign_settings(resolve_settings({"overrides": {"companion": {"combat": "suggest"}}})):
        resolution = await combat_resolver.resolve("strike the warden", "session-1")

    assert resolution.context == "[PLAYER ACTION]\nAldric strikes and advances the turn."
    assert resolution.proposal == {
        "combatant_id": "companion-1",
        "combatant_name": "Wrenna",
        "action": "shoot the warden",
        "narration": "Say the word and I loose.",
    }


async def test_player_mode_stops_on_companion_turn(
    monkeypatch: pytest.MonkeyPatch,
    companion_turn: tuple[dict, list[dict]],
) -> None:
    async def fake_plan(*args, **kwargs) -> CombatPlan:
        return CombatPlan(operations=())

    async def fake_execute(*args, **kwargs) -> ExecutionComplete:
        return ExecutionComplete(facts=("Aldric strikes and advances the turn.",))

    async def fake_context(session_id: str) -> tuple[dict, list[dict]]:
        return companion_turn

    monkeypatch.setattr(combat_resolver, "_plan", fake_plan)
    monkeypatch.setattr(combat_resolver, "_execute_plan", fake_execute)
    monkeypatch.setattr(combat_resolver, "fetch_combat_context", fake_context)

    with using_campaign_settings(resolve_settings({"overrides": {"companion": {"combat": "player"}}})):
        resolution = await combat_resolver.resolve("strike the warden", "session-1")

    assert resolution.context == "[PLAYER ACTION]\nAldric strikes and advances the turn."
    assert resolution.proposal is None
