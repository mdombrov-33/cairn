import uuid
from dataclasses import dataclass, field
from typing import Any

from cairn.agents.rules_lawyer import build_character_context, build_party_manifest


@dataclass
class FakeCharacter:
    """Test double that satisfies the `CharacterLike` protocol."""

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = "Aldric"
    class_: str | None = "fighter"
    level: int = 3
    background: str | None = "soldier"
    hp: int = 24
    max_hp: int = 28
    ac: int = 16
    ability_scores: dict[str, Any] = field(
        default_factory=lambda: {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}
    )
    proficiency_bonus: int = 2
    skill_proficiencies: list[Any] = field(default_factory=lambda: ["athletics", "perception"])
    conditions: list[Any] = field(default_factory=list)
    feats: list[Any] = field(default_factory=list)
    features: list[Any] = field(default_factory=list)
    is_companion: bool = False


# build_character_context


def test_build_character_context_contains_name() -> None:
    ctx = build_character_context(FakeCharacter(name="Ser Aldric"))
    assert "Ser Aldric" in ctx


def test_build_character_context_proficient_skill_adds_bonus() -> None:
    # STR 15 → mod +2, proficiency +2, athletics proficient → +4
    ctx = build_character_context(
        FakeCharacter(
            ability_scores={"str": 15, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=["athletics"],
        )
    )
    assert "athletics: +4 (proficient)" in ctx


def test_build_character_context_non_proficient_skill_no_prof() -> None:
    # DEX 14 → mod +2, stealth not proficient → +2 (no bonus)
    ctx = build_character_context(
        FakeCharacter(
            ability_scores={"str": 10, "dex": 14, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=[],
        )
    )
    assert "stealth: +2" in ctx
    assert "stealth: +2 (proficient)" not in ctx


def test_build_character_context_includes_conditions() -> None:
    ctx = build_character_context(FakeCharacter(conditions=["poisoned", "prone"]))
    assert "poisoned" in ctx
    assert "prone" in ctx


# build_party_manifest


def test_build_party_manifest_excludes_active() -> None:
    active = FakeCharacter(name="Aldric")
    companion = FakeCharacter(name="Mira", is_companion=True)
    manifest = build_party_manifest([active, companion], active.id)
    assert "Mira" in manifest
    assert "Aldric" not in manifest


def test_build_party_manifest_no_others() -> None:
    active = FakeCharacter()
    manifest = build_party_manifest([active], active.id)
    assert "No other party members" in manifest


def test_build_party_manifest_shows_companion_role() -> None:
    active = FakeCharacter()
    companion = FakeCharacter(name="Zara", is_companion=True)
    manifest = build_party_manifest([active, companion], active.id)
    assert "companion (AI)" in manifest


def test_build_party_manifest_shows_skill_proficiency() -> None:
    active = FakeCharacter()
    # WIS 16 → mod +3, prof +2 → perception +5
    companion = FakeCharacter(
        name="Bria",
        ability_scores={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 16, "cha": 10},
        skill_proficiencies=["perception"],
    )
    manifest = build_party_manifest([active, companion], active.id)
    assert "perception: +5" in manifest
