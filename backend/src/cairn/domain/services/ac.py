"""
AC is recomputed from equipped inventory items + ability scores + feats whenever
any of those change (equip/unequip, ASI, feat grant). The result is written to
char.ac so reads are cheap.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from cairn.srd import get_armor
from cairn.types import AbilityScores, FeatEntry, InventoryItem

if TYPE_CHECKING:
    from cairn.db.models.character import Character
    from cairn.db.models.npc import NPC

log = structlog.get_logger()


@dataclass(frozen=True)
class AcInput:
    """The fields `derive_ac` reads, as a plain projection of an ORM row.

    SQLAlchemy `Mapped[...]` attributes don't structurally satisfy a Protocol
    under Pyright (it compares the raw `Mapped[T]`, not the descriptor result),
    so callers project the row into this rather than passing it directly. The
    `TYPE_CHECKING`-only import keeps `ac.py` free of any runtime ORM import.
    """

    id: object
    class_: str | None
    ability_scores: AbilityScores
    inventory: list[InventoryItem]
    feats: list[FeatEntry] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: Character | NPC) -> AcInput:
        # Character exposes class_name (derived from classes[0]); NPC keeps a class_ column.
        class_name = getattr(row, "class_name", None) or getattr(row, "class_", None)
        return cls(
            id=row.id,
            class_=class_name,
            ability_scores=row.ability_scores,
            inventory=row.inventory,
            feats=row.feats,
        )


def mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def _equipped_armor_and_shield(char: AcInput) -> tuple[dict | None, dict | None]:
    equipped_armor: dict | None = None
    equipped_shield: dict | None = None
    for item in char.inventory or []:
        if not item.get("equipped"):
            continue
        srd_index = item.get("srd_index") or item.get("name", "").lower().replace(" ", "-")
        armor_data = get_armor(srd_index)
        if armor_data is None:
            continue
        category = armor_data.get("armor_category", "")
        if category == "Shield":
            if equipped_shield is None:
                equipped_shield = armor_data
        elif equipped_armor is None:
            equipped_armor = armor_data
    return equipped_armor, equipped_shield


def _unarmored_base(char: AcInput, dex_mod: int) -> int:
    cls = (char.class_ or "").lower()
    if cls == "barbarian":
        return 10 + dex_mod + mod(char.ability_scores.get("con", 10))
    if cls == "monk":
        return 10 + dex_mod + mod(char.ability_scores.get("wis", 10))
    return 10 + dex_mod


def _feat_ac_bonus(char: AcInput, equipped_armor: dict | None) -> int:
    feat_indices = {f["index"] for f in (char.feats or [])}
    if "defense" in feat_indices and equipped_armor is not None:
        return 1
    return 0


def derive_ac(char: AcInput) -> int:
    """Compute and return AC from equipped items + ability scores + feats."""
    dex_mod = mod(char.ability_scores.get("dex", 10))
    equipped_armor, equipped_shield = _equipped_armor_and_shield(char)

    if equipped_armor is None:
        base = _unarmored_base(char, dex_mod)
    else:
        ac_data = equipped_armor["armor_class"]
        base_ac: int = ac_data["base"]
        if ac_data.get("dex_bonus"):
            max_bonus = ac_data.get("max_bonus")
            dex_contribution = min(dex_mod, max_bonus) if max_bonus is not None else dex_mod
            base = base_ac + dex_contribution
        else:
            base = base_ac

    shield_bonus = equipped_shield["armor_class"]["base"] if equipped_shield else 0
    feat_bonus = _feat_ac_bonus(char, equipped_armor)

    ac = base + shield_bonus + feat_bonus
    log.debug(
        "ac_derived",
        character_id=str(char.id),
        ac=ac,
        armor=equipped_armor.get("index") if equipped_armor else None,
        shield=equipped_shield.get("index") if equipped_shield else None,
    )
    return ac
