"""Pure reaction policy used only by the deterministic combat executor."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from cairn.domain.combat import ReactionDecision, ReactionName

MAX_REACTION_DEPTH = 4
MEANINGFUL_HP_FRACTION = 0.20
REACTION_REGISTRY: tuple[ReactionName, ...] = (
    "opportunity_attack",
    "shield",
    "absorb_elements",
    "counterspell",
    "readied_action",
    "sentinel",
)

TriggerKind = Literal["movement", "attack", "typed_damage", "spell_cast", "readied"]


@dataclass(frozen=True)
class ReactionOpportunity:
    name: ReactionName
    reactor_id: str
    trigger: TriggerKind
    changes_outcome: bool = True
    prevented_damage: int = 0
    current_hp: int = 1
    prevents_incapacitation: bool = False
    spell_level: int = 0
    is_area_or_control: bool = False


def should_react(opportunity: ReactionOpportunity) -> bool:
    """Deterministic recommendation shared by AI and suggest control."""
    if opportunity.name in {"opportunity_attack", "readied_action", "sentinel"}:
        return True
    if opportunity.name == "shield":
        return opportunity.changes_outcome and (
            opportunity.prevents_incapacitation
            or opportunity.prevented_damage >= max(1, round(opportunity.current_hp * MEANINGFUL_HP_FRACTION))
        )
    if opportunity.name == "absorb_elements":
        return opportunity.prevents_incapacitation or opportunity.prevented_damage >= max(
            1, round(opportunity.current_hp * MEANINGFUL_HP_FRACTION)
        )
    if opportunity.name == "counterspell":
        return opportunity.spell_level >= 3 and opportunity.is_area_or_control
    return False


def recommendation(opportunity: ReactionOpportunity) -> tuple[ReactionDecision, str | None]:
    return ("take", opportunity.name) if should_react(opportunity) else ("decline", None)


def matches_readied(trigger: Mapping[str, object], event: Mapping[str, object]) -> bool:
    """Match a parse-once readied trigger against one executor event."""
    if trigger.get("event") != event.get("event"):
        return False
    creature = str(trigger.get("creature", "any")).casefold()
    event_creatures = {
        str(event.get("creature_id", "")).casefold(),
        str(event.get("creature_name", "")).casefold(),
    }
    if creature not in {"any", "*"} and creature not in event_creatures:
        return False
    for field in ("zone", "target"):
        expected = trigger.get(field)
        if expected is not None and str(expected).casefold() != str(event.get(field, "")).casefold():
            return False
    return True
