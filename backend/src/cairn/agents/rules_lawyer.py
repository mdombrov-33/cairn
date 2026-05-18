from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel

from cairn.llm.client import complete_to_model
from cairn.llm.router import agent_setup
from cairn.types import AbilityKey, AbilityScores, FeatEntry, FeatureEntry

if TYPE_CHECKING:
    from cairn.db.models.character import Character

log = structlog.get_logger()


@dataclass(frozen=True)
class CharacterView:
    """The character fields the RulesLawyer prompt needs, as a plain projection.

    SQLAlchemy `Mapped[...]` attributes don't structurally satisfy a Protocol
    under Pyright (it compares the raw `Mapped[T]`, not the descriptor result),
    so callers project the ORM row into this via `from_character`. Defaults
    exist so unit tests can build partial instances."""

    id: object = ""
    name: str = ""
    class_: str | None = None
    level: int = 1
    background: str | None = None
    hp: int = 0
    max_hp: int = 0
    ac: int = 10
    ability_scores: AbilityScores = field(
        default_factory=lambda: AbilityScores({"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10})
    )
    proficiency_bonus: int = 2
    skill_proficiencies: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    feats: list[FeatEntry] = field(default_factory=list)
    features: list[FeatureEntry] = field(default_factory=list)
    is_companion: bool = False

    @classmethod
    def from_character(cls, char: Character) -> CharacterView:
        return cls(
            id=char.id,
            name=char.name,
            class_=char.class_,
            level=char.level,
            background=char.background,
            hp=char.hp,
            max_hp=char.max_hp,
            ac=char.ac,
            ability_scores=char.ability_scores,
            proficiency_bonus=char.proficiency_bonus,
            skill_proficiencies=char.skill_proficiencies,
            conditions=char.conditions,
            feats=char.feats,
            features=char.features,
            is_companion=char.is_companion,
        )


_SKILL_TO_ABILITY: dict[str, AbilityKey] = {
    "acrobatics": "dex",
    "animal handling": "wis",
    "arcana": "int",
    "athletics": "str",
    "deception": "cha",
    "history": "int",
    "insight": "wis",
    "intimidation": "cha",
    "investigation": "int",
    "medicine": "wis",
    "nature": "int",
    "perception": "wis",
    "performance": "cha",
    "persuasion": "cha",
    "religion": "int",
    "sleight of hand": "dex",
    "stealth": "dex",
    "survival": "wis",
}


def _mod(score: int) -> int:
    return math.floor((score - 10) / 2)


def build_character_context(char: CharacterView) -> str:
    """Serialize a Character into a compact text block for the RulesLawyer prompt."""
    scores = char.ability_scores
    mods = {
        "str": _mod(scores["str"]),
        "dex": _mod(scores["dex"]),
        "con": _mod(scores["con"]),
        "int": _mod(scores["int"]),
        "wis": _mod(scores["wis"]),
        "cha": _mod(scores["cha"]),
    }
    prof = char.proficiency_bonus or 2
    profs_lower = [s.lower() for s in (char.skill_proficiencies or [])]

    skill_lines = []
    for skill, ability in _SKILL_TO_ABILITY.items():
        base = mods[ability]
        total = base + prof if skill in profs_lower else base
        proficient = " (proficient)" if skill in profs_lower else ""
        skill_lines.append(f"  {skill}: {total:+d}{proficient}")

    conditions = ", ".join(char.conditions or []) or "none"
    feats = ", ".join(f.get("name", "") for f in (char.feats or [])) or "none"
    features = ", ".join(f.get("name", "") for f in (char.features or [])) or "none"

    lines = [
        f"Name: {char.name}",
        f"Class: {char.class_}  Level: {char.level}  Background: {char.background}",
        f"HP: {char.hp}/{char.max_hp}  AC: {char.ac}",
        f"Ability scores: STR {scores['str']} DEX {scores['dex']} "
        f"CON {scores['con']} INT {scores['int']} "
        f"WIS {scores['wis']} CHA {scores['cha']}",
        f"Proficiency bonus: +{prof}",
        "Skill modifiers:",
        *skill_lines,
        f"Conditions: {conditions}",
        f"Feats: {feats}",
        f"Features: {features}",
    ]
    return "\n".join(lines)


def build_party_manifest(party: Sequence[CharacterView], active_id: object) -> str:
    """Build a thin manifest of party members other than the active character."""
    others = [c for c in party if str(c.id) != str(active_id)]
    if not others:
        return "No other party members."

    lines = []
    for c in others:
        scores = c.ability_scores
        prof = c.proficiency_bonus or 2
        profs_lower = [s.lower() for s in (c.skill_proficiencies or [])]
        proficient_mods = {
            skill: _mod(scores[ability]) + prof for skill, ability in _SKILL_TO_ABILITY.items() if skill in profs_lower
        }
        skills_str = ", ".join(f"{s}: {v:+d}" for s, v in proficient_mods.items()) or "none"
        role = "companion (AI)" if c.is_companion else "player character"
        lines.append(f"- {c.name} [id:{c.id}] ({c.class_} {c.level}, {role}) | proficient skills: {skills_str}")
    return "\n".join(lines)


class HelperInfo(BaseModel):
    character_id: str
    name: str


class CheckDecision(BaseModel):
    skill: str
    dc: int
    modifier: int
    roll_type: Literal["d20", "advantage", "disadvantage"]
    helper: HelperInfo | None = None


async def run(
    player_input: str,
    character_context: str = "",
    party_manifest: str = "",
) -> CheckDecision:
    prompt, model, fallbacks = agent_setup("rules_lawyer")

    return await complete_to_model(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt.render(
                    player_input=player_input,
                    character_context=character_context or "No character data available.",
                    party_manifest=party_manifest or "No other party members.",
                ),
            }
        ],
        model_cls=CheckDecision,
        agent="rules_lawyer",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )
