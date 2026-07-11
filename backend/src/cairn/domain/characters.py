"""Character-owned JSONB shapes and value types."""

from typing import Literal, NotRequired, Required, TypedDict

AbilityKey = Literal["str", "dex", "con", "int", "wis", "cha"]


class AbilityScores(TypedDict):
    str: int
    dex: int
    con: int
    int: int
    wis: int
    cha: int


class Currency(TypedDict):
    gp: int
    sp: int
    cp: int


class InventoryItem(TypedDict):
    name: Required[str]
    quantity: Required[int]
    srd_index: NotRequired[str]
    equipped: NotRequired[bool]
    weight: NotRequired[int]
    notes: NotRequired[str]
    description: NotRequired[str]


class FeatEntry(TypedDict):
    index: Required[str]
    name: Required[str]
    type: NotRequired[str]
    options: NotRequired[dict]


class FeatureEntry(TypedDict):
    index: NotRequired[str]
    name: Required[str]
    type: NotRequired[Literal["trait", "attack", "feature"]]
    description: NotRequired[str]
    bonus: NotRequired[int]
    damage: NotRequired[str]
    damage_type: NotRequired[str]
    range: NotRequired[str]


SpellSlots = dict[str, int]


class Resource(TypedDict):
    current: int
    max: int
    resets_on: Literal["short_rest", "long_rest"]
