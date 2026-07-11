"""The single validation and lookup seam for bundled SRD data."""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

from cairn.srd.models import (
    BackgroundRecord,
    ClassLevelRecord,
    ClassRecord,
    EquipmentRecord,
    FeatRecord,
    FeatureRecord,
    MonsterRecord,
    NamedRecord,
    ProficiencyRecord,
    RaceRecord,
    SpellRecord,
    SubclassRecord,
    SubraceRecord,
)

_DIR = Path(__file__).parent


def _key(value: str, *, strip_apostrophe: bool = False) -> str:
    normalized = value.lower().replace(" ", "-")
    return normalized.replace("'", "") if strip_apostrophe else normalized


@lru_cache
def _read(name: str) -> object:
    return json.loads((_DIR / f"{name}.json").read_text())


@lru_cache
def _records[Record: BaseModel](name: str, record_type: type[Record]) -> tuple[Record, ...]:
    return tuple(TypeAdapter(list[record_type]).validate_python(_read(name)))  # type: ignore[valid-type]


@lru_cache
def _index[Record: BaseModel](name: str, record_type: type[Record]) -> dict[str, Record]:
    return {record.index: record for record in _records(name, record_type)}  # type: ignore[attr-defined]


class Catalog:
    """Validated SRD records with normalization hidden from callers."""

    @property
    def classes(self) -> tuple[ClassRecord, ...]:
        return _records("classes", ClassRecord)

    def class_(self, name: str) -> ClassRecord | None:
        return _index("classes", ClassRecord).get(_key(name))

    def class_levels(self, name: str) -> tuple[ClassLevelRecord, ...]:
        data = _read("class_levels")
        assert isinstance(data, dict)
        return tuple(TypeAdapter(list[ClassLevelRecord]).validate_python(data.get(_key(name), [])))

    @property
    def races(self) -> tuple[RaceRecord, ...]:
        return _records("races", RaceRecord)

    def race(self, name: str) -> RaceRecord | None:
        return _index("races", RaceRecord).get(_key(name))

    @property
    def subraces(self) -> tuple[SubraceRecord, ...]:
        return _records("subraces", SubraceRecord)

    def subrace(self, name: str) -> SubraceRecord | None:
        return _index("subraces", SubraceRecord).get(_key(name))

    @property
    def backgrounds(self) -> tuple[BackgroundRecord, ...]:
        return _records("backgrounds", BackgroundRecord)

    def background(self, name: str) -> BackgroundRecord | None:
        return _index("backgrounds", BackgroundRecord).get(_key(name))

    @property
    def equipment(self) -> tuple[EquipmentRecord, ...]:
        return _records("equipment", EquipmentRecord)

    def equipment_item(self, name: str) -> EquipmentRecord | None:
        return _index("equipment", EquipmentRecord).get(_key(name))

    def weapon(self, name: str) -> EquipmentRecord | None:
        item = self.equipment_item(name)
        return item if item and item.equipment_category.index == "weapon" else None

    def armor(self, name: str) -> EquipmentRecord | None:
        item = self.equipment_item(name)
        return item if item and item.equipment_category.index == "armor" else None

    @property
    def monsters(self) -> tuple[MonsterRecord, ...]:
        return _records("monsters", MonsterRecord)

    def monster(self, name: str) -> MonsterRecord | None:
        return _index("monsters", MonsterRecord).get(_key(name))

    @property
    def spells(self) -> tuple[SpellRecord, ...]:
        return _records("spells", SpellRecord)

    def spell(self, name: str) -> SpellRecord | None:
        return _index("spells", SpellRecord).get(_key(name, strip_apostrophe=True))

    @property
    def feats(self) -> tuple[FeatRecord, ...]:
        return tuple(
            {
                record.index: record for record in (*_records("feats", FeatRecord), *_records("feats_phb", FeatRecord))
            }.values()
        )

    def feat(self, name: str) -> FeatRecord | None:
        return {record.index: record for record in self.feats}.get(_key(name, strip_apostrophe=True))

    def named(self, file_name: str, name: str) -> NamedRecord | None:
        return _index(file_name, NamedRecord).get(_key(name))

    def named_records(self, file_name: str) -> tuple[NamedRecord, ...]:
        return _records(file_name, NamedRecord)

    def feature(self, name: str) -> FeatureRecord | None:
        key = _key(name).replace("(", "").replace(")", "").replace(",", "").strip("-")
        return _index("features", FeatureRecord).get(key)

    def subclass_features_at_level(self, subclass_index: str, level: int) -> tuple[FeatureRecord, ...]:
        return tuple(
            record
            for record in _records("features", FeatureRecord)
            if record.subclass and record.subclass.index == subclass_index and record.level == level
        )

    def subclasses(self) -> tuple[SubclassRecord, ...]:
        return _records("subclasses", SubclassRecord)

    def subclass(self, name: str) -> SubclassRecord | None:
        return _index("subclasses", SubclassRecord).get(_key(name))

    def proficiencies_for_race(
        self, race_index: str, subrace_index: str | None = None
    ) -> tuple[ProficiencyRecord, ...]:
        indices = {race_index, subrace_index}
        return tuple(
            record
            for record in _records("proficiencies", ProficiencyRecord)
            if indices & {race.index for race in record.races}
        )


catalog = Catalog()
