"""Map SRD ranges onto Cairn's coarse tactical-zone categories."""

import re
from typing import Literal

from cairn.domain.services.combat.helpers import find_combatant
from cairn.types import CombatState

type RangeCategory = Literal["self", "touch", "close", "far", "out_of_range"]


def range_feet_to_category(feet: int) -> RangeCategory:
    if feet <= 5:
        return "touch"
    if feet <= 30:
        return "close"
    return "far"


def srd_range_to_category(srd_range: str) -> RangeCategory:
    normalized = srd_range.strip().lower()
    if normalized == "self":
        return "self"
    if normalized == "touch":
        return "touch"
    match = re.search(r"\d+", normalized)
    if match is None:
        return "out_of_range"
    return range_feet_to_category(int(match.group()))


def target_in_range(state: CombatState, *, source_id: str, target_id: str, range_category: RangeCategory) -> bool:
    source = find_combatant(state, source_id)
    target = find_combatant(state, target_id)
    if source is None or target is None or target["zone"] is None:
        return False
    if range_category == "self":
        return source_id == target_id
    return zone_in_range(
        state,
        source_id=source_id,
        target_zone_id=target["zone"],
        range_category=range_category,
    )


def zone_in_range(state: CombatState, *, source_id: str, target_zone_id: str, range_category: RangeCategory) -> bool:
    source = find_combatant(state, source_id)
    if source is None or source["zone"] is None:
        return False
    if source["zone"] == target_zone_id:
        return range_category in {"touch", "close", "far"}
    if range_category in {"touch", "out_of_range"}:
        return False
    source_zone = next((zone for zone in state["zones"] if zone["id"] == source["zone"]), None)
    if source_zone is None:
        return False
    distance = source_zone["distances"].get(target_zone_id)
    if range_category == "close":
        return distance == "close"
    return distance in {"close", "far"}
