from cairn.domain.services.ac import AcInput, derive_ac


def test_derive_ac_applies_typed_medium_armor_dexterity_cap() -> None:
    char = AcInput(
        id="character",
        class_=None,
        ability_scores={"str": 10, "dex": 18, "con": 10, "int": 10, "wis": 10, "cha": 10},
        inventory=[{"name": "Hide Armor", "quantity": 1, "srd_index": "hide-armor", "equipped": True}],
    )

    assert derive_ac(char) == 14
