from cairn import srd
from cairn.srd.catalog import catalog
from cairn.srd.models import ClassRecord, MonsterRecord


def test_catalog_returns_typed_validated_records() -> None:
    fighter = catalog.class_("fighter")
    goblin = catalog.monster("goblin")

    assert isinstance(fighter, ClassRecord)
    assert fighter.hit_die == 10
    assert isinstance(goblin, MonsterRecord)
    assert goblin.hit_points == 7


def test_compatibility_adapter_preserves_srd_json_shape() -> None:
    subclass = srd.get_subclass("champion")

    assert subclass is not None
    assert subclass["class"]["index"] == "fighter"
    assert srd.get_class_levels("cleric")[4]["class_specific"]["destroy_undead_cr"] == 0.5
