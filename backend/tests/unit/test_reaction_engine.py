import random

from pydantic import ValidationError

from cairn.api.v1.schemas.turns import ReactionResolutionRequest
from cairn.application.combat.plan import CombatPlan
from cairn.application.combat.reactions import REACTION_REGISTRY, ReactionOpportunity, matches_readied, should_react
from cairn.application.combat.rolls import roll_attack
from cairn.domain.services.settings import resolve_settings


def test_reaction_control_preset_defaults_and_override() -> None:
    assert resolve_settings({}).reaction_control == "ai"
    assert resolve_settings({"preset": "balanced"}).reaction_control == "suggest"
    assert resolve_settings({"preset": "tactical"}).reaction_control == "suggest"
    assert resolve_settings({"overrides": {"reaction_control": "player"}}).reaction_control == "player"


def test_roll_attack_enforces_cover_and_natural_rules() -> None:
    covered = roll_attack(to_hit_bonus=4, target_ac=15, cover_ac_bonus=2, rng=random.Random(0))
    assert covered.natural == 13
    assert covered.total == 17
    assert covered.target_ac == 17
    assert covered.hit is True

    natural_one = roll_attack(to_hit_bonus=99, target_ac=10, rng=random.Random(31))
    assert natural_one.natural == 1
    assert natural_one.hit is False


def test_advantage_and_disadvantage_cancel() -> None:
    result = roll_attack(
        to_hit_bonus=0,
        target_ac=10,
        advantage=True,
        disadvantage=True,
        rng=random.Random(0),
    )
    assert len(result.rolls) == 1


def test_outcome_based_reaction_thresholds() -> None:
    assert set(REACTION_REGISTRY) == {
        "opportunity_attack",
        "shield",
        "absorb_elements",
        "counterspell",
        "readied_action",
        "sentinel",
    }
    trivial = ReactionOpportunity(
        name="shield",
        reactor_id="pc",
        trigger="attack",
        prevented_damage=3,
        current_hp=20,
    )
    meaningful = ReactionOpportunity(
        name="shield",
        reactor_id="pc",
        trigger="attack",
        prevented_damage=4,
        current_hp=20,
    )
    lethal = ReactionOpportunity(
        name="absorb_elements",
        reactor_id="pc",
        trigger="typed_damage",
        prevented_damage=1,
        current_hp=20,
        prevents_incapacitation=True,
    )
    assert should_react(trivial) is False
    assert should_react(meaningful) is True
    assert should_react(lethal) is True


def test_combat_plan_is_strict_and_discriminated() -> None:
    plan = CombatPlan.model_validate(
        {
            "operations": [
                {"kind": "attack", "actor_id": "a", "target_id": "b", "attack_name": None},
                {"kind": "apply_condition", "actor_id": "a", "target_id": "b", "condition": "prone"},
                {"kind": "advance_turn", "actor_id": "a"},
            ]
        }
    )
    assert [operation.kind for operation in plan.operations] == ["attack", "apply_condition", "advance_turn"]

    try:
        CombatPlan.model_validate({"operations": [{"kind": "attack", "actor_id": "a"}]})
    except ValidationError:
        pass
    else:
        raise AssertionError("invalid operation was accepted")


def test_reaction_request_requires_explicit_consistent_choice() -> None:
    accepted = ReactionResolutionRequest(
        checkpoint_id="checkpoint",
        decision="take",
        chosen_reaction="shield",
    )
    assert accepted.chosen_reaction == "shield"

    for payload in (
        {"checkpoint_id": "checkpoint", "decision": "take"},
        {"checkpoint_id": "checkpoint", "decision": "decline", "chosen_reaction": "shield"},
    ):
        try:
            ReactionResolutionRequest.model_validate(payload)
        except ValidationError:
            pass
        else:
            raise AssertionError("inconsistent reaction request was accepted")


def test_readied_trigger_matches_only_structured_event_fields() -> None:
    trigger = {"creature": "goblin", "event": "enters-zone", "zone": "doorway", "target": None}
    assert matches_readied(
        trigger,
        {"creature_name": "Goblin", "creature_id": "monster-1", "event": "enters-zone", "zone": "doorway"},
    )
    assert not matches_readied(
        trigger,
        {"creature_name": "Goblin", "creature_id": "monster-1", "event": "enters-zone", "zone": "stairs"},
    )
