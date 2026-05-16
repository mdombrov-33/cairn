import json
import math
from collections.abc import Sequence
from typing import Any, Literal, Protocol

import structlog
from pydantic import BaseModel, ValidationError

from cairn.domain.exceptions import AgentError
from cairn.llm.client import complete
from cairn.llm.router import agent_setup

log = structlog.get_logger()


class CharacterLike(Protocol):
    """Structural type for the fields rules_lawyer reads off a character.
    Satisfied by the SQLAlchemy Character model in production and by test fakes.
    Properties (read-only) so covariance works on fields like `class_`."""

    @property
    def id(self) -> Any: ...
    @property
    def name(self) -> str: ...
    @property
    def class_(self) -> str | None: ...
    @property
    def level(self) -> int: ...
    @property
    def background(self) -> str | None: ...
    @property
    def hp(self) -> int: ...
    @property
    def max_hp(self) -> int: ...
    @property
    def ac(self) -> int: ...
    @property
    def ability_scores(self) -> dict[str, Any]: ...
    @property
    def proficiency_bonus(self) -> int: ...
    @property
    def skill_proficiencies(self) -> list[Any]: ...
    @property
    def conditions(self) -> list[Any]: ...
    @property
    def feats(self) -> list[Any]: ...
    @property
    def features(self) -> list[Any]: ...
    @property
    def is_companion(self) -> bool: ...


_SKILL_TO_ABILITY = {
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


def build_character_context(char: CharacterLike) -> str:
    """Serialize a Character into a compact text block for the RulesLawyer prompt."""
    scores = char.ability_scores or {}
    mods = {ab: _mod(scores.get(ab, 10)) for ab in ("str", "dex", "con", "int", "wis", "cha")}
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
        f"Ability scores: STR {scores.get('str', 10)} DEX {scores.get('dex', 10)} "
        f"CON {scores.get('con', 10)} INT {scores.get('int', 10)} "
        f"WIS {scores.get('wis', 10)} CHA {scores.get('cha', 10)}",
        f"Proficiency bonus: +{prof}",
        "Skill modifiers:",
        *skill_lines,
        f"Conditions: {conditions}",
        f"Feats: {feats}",
        f"Features: {features}",
    ]
    return "\n".join(lines)


def build_party_manifest(party: Sequence[CharacterLike], active_id: object) -> str:
    """Build a thin manifest of party members other than the active character."""
    others = [c for c in party if str(c.id) != str(active_id)]
    if not others:
        return "No other party members."

    lines = []
    for c in others:
        scores = c.ability_scores or {}
        prof = c.proficiency_bonus or 2
        profs_lower = [s.lower() for s in (c.skill_proficiencies or [])]
        proficient_mods = {
            skill: _mod(scores.get(ability, 10)) + prof
            for skill, ability in _SKILL_TO_ABILITY.items()
            if skill in profs_lower
        }
        skills_str = ", ".join(f"{s}: {v:+d}" for s, v in proficient_mods.items()) or "none"
        role = "companion (AI)" if c.is_companion else "player character"
        lines.append(
            f"- {c.name} [id:{c.id}] ({c.class_} {c.level}, {role})"
            f" | proficient skills: {skills_str}"
        )
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

    raw = await complete(
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
        agent="rules_lawyer",
        fallbacks=fallbacks,
        temperature=prompt.temperature,
    )

    try:
        data = json.loads(raw.strip())
        return CheckDecision.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.error("rules_lawyer_bad_output", raw=raw, error=str(exc))
        raise AgentError(f"RulesLawyer returned invalid JSON: {raw!r}") from exc
