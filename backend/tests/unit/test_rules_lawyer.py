import uuid
from types import SimpleNamespace

from cairn.agents.rules_lawyer import build_character_context, build_party_manifest


def _char(
    name="Aldric",
    class_="fighter",
    level=3,
    background="soldier",
    hp=24,
    max_hp=28,
    ac=16,
    proficiency_bonus=2,
    ability_scores=None,
    skill_proficiencies=None,
    saving_throw_proficiencies=None,
    conditions=None,
    feats=None,
    features=None,
    is_companion=False,
    id=None,
):
    return SimpleNamespace(
        id=id or uuid.uuid4(),
        name=name,
        class_=class_,
        level=level,
        background=background,
        hp=hp,
        max_hp=max_hp,
        ac=ac,
        proficiency_bonus=proficiency_bonus,
        ability_scores=ability_scores
        or {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8},
        skill_proficiencies=skill_proficiencies or ["athletics", "perception"],
        saving_throw_proficiencies=saving_throw_proficiencies or ["str", "con"],
        conditions=conditions or [],
        feats=feats or [],
        features=features or [],
        is_companion=is_companion,
    )


def test_build_character_context_contains_name():
    ctx = build_character_context(_char(name="Ser Aldric"))
    assert "Ser Aldric" in ctx


def test_build_character_context_proficient_skill_adds_bonus():
    # STR 15 → mod +2, proficiency bonus +2, athletics proficient → total +4
    ctx = build_character_context(
        _char(
            ability_scores={"str": 15, "dex": 10, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=["athletics"],
            proficiency_bonus=2,
        )
    )
    # athletics should show +4
    assert "athletics: +4 (proficient)" in ctx


def test_build_character_context_non_proficient_skill_no_prof():
    # DEX 14 → mod +2, stealth NOT proficient → total +2
    ctx = build_character_context(
        _char(
            ability_scores={"str": 10, "dex": 14, "con": 10, "int": 10, "wis": 10, "cha": 10},
            skill_proficiencies=[],
            proficiency_bonus=2,
        )
    )
    assert "stealth: +2" in ctx
    assert "stealth: +2 (proficient)" not in ctx


def test_build_character_context_includes_conditions():
    ctx = build_character_context(_char(conditions=["poisoned", "prone"]))
    assert "poisoned" in ctx
    assert "prone" in ctx


def test_build_party_manifest_excludes_active():
    active_id = uuid.uuid4()
    companion_id = uuid.uuid4()
    active = _char(name="Aldric", id=active_id)
    companion = _char(name="Mira", is_companion=True, id=companion_id)

    manifest = build_party_manifest([active, companion], active_id)
    assert "Mira" in manifest
    assert "Aldric" not in manifest


def test_build_party_manifest_no_others():
    active_id = uuid.uuid4()
    active = _char(id=active_id)
    manifest = build_party_manifest([active], active_id)
    assert "No other party members" in manifest


def test_build_party_manifest_shows_companion_role():
    active_id = uuid.uuid4()
    companion_id = uuid.uuid4()
    active = _char(id=active_id)
    companion = _char(name="Zara", is_companion=True, id=companion_id)
    manifest = build_party_manifest([active, companion], active_id)
    assert "companion (AI)" in manifest


def test_build_party_manifest_shows_skill_proficiency():
    active_id = uuid.uuid4()
    companion_id = uuid.uuid4()
    active = _char(id=active_id)
    companion = _char(
        name="Bria",
        is_companion=False,
        id=companion_id,
        ability_scores={"str": 10, "dex": 10, "con": 10, "int": 10, "wis": 16, "cha": 10},
        skill_proficiencies=["perception"],
        proficiency_bonus=2,
    )
    # WIS 16 → mod +3, proficiency +2 → perception total +5
    manifest = build_party_manifest([active, companion], active_id)
    assert "perception: +5" in manifest
