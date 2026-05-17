from cairn.agents.rules_lawyer import (
    CharacterView,
    build_character_context,
    build_party_manifest,
)

# build_character_context


def test_build_character_context_contains_name() -> None:
    ctx = build_character_context(CharacterView(name="Ser Aldric"))
    assert "Ser Aldric" in ctx


def test_build_character_context_proficient_skill_adds_bonus() -> None:
    # STR 15 → mod +2, proficiency +2, athletics proficient → +4
    ctx = build_character_context(
        CharacterView(
            ability_scores={"str": 15, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=["athletics"],
        )
    )
    assert "athletics: +4 (proficient)" in ctx


def test_build_character_context_non_proficient_skill_no_prof() -> None:
    # DEX 14 → mod +2, stealth not proficient → +2 (no bonus)
    ctx = build_character_context(
        CharacterView(
            ability_scores={"str": 10, "dex": 14, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=[],
        )
    )
    assert "stealth: +2" in ctx
    assert "stealth: +2 (proficient)" not in ctx


def test_build_character_context_includes_conditions() -> None:
    ctx = build_character_context(CharacterView(conditions=["poisoned", "prone"]))
    assert "poisoned" in ctx
    assert "prone" in ctx


# build_party_manifest


def test_build_party_manifest_excludes_active() -> None:
    active = CharacterView(id="a", name="Aldric")
    companion = CharacterView(id="b", name="Mira", is_companion=True)
    manifest = build_party_manifest([active, companion], active.id)
    assert "Mira" in manifest
    assert "Aldric" not in manifest


def test_build_party_manifest_no_others() -> None:
    active = CharacterView(id="a")
    manifest = build_party_manifest([active], active.id)
    assert "No other party members" in manifest


def test_build_party_manifest_shows_companion_role() -> None:
    active = CharacterView(id="a")
    companion = CharacterView(id="b", name="Zara", is_companion=True)
    manifest = build_party_manifest([active, companion], active.id)
    assert "companion (AI)" in manifest


def test_build_party_manifest_shows_skill_proficiency() -> None:
    active = CharacterView(id="a")
    # WIS 16 → mod +3, prof +2 → perception +5
    companion = CharacterView(
        id="b",
        name="Bria",
        ability_scores={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 16, "cha": 10},
        skill_proficiencies=["perception"],
    )
    manifest = build_party_manifest([active, companion], active.id)
    assert "perception: +5" in manifest
