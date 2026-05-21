"""Shared TypedDicts for JSONB column shapes.

These describe what's *actually* stored in JSONB fields today, inferred by
reading every place those fields are written. Pure static typing - no
runtime validation. Postgres still stores arbitrary JSON.

"""

from typing import Annotated, Any, Literal, NotRequired, Required, TypedDict

type ToolUUID = Annotated[str, "UUID as string — converted at the tool boundary"]

# Ability score key — the 6 D&D abilities. Used everywhere we index AbilityScores
# with a runtime variable; declaring this as Literal lets mypy verify the access.
AbilityKey = Literal["str", "dex", "con", "int", "wis", "cha"]

# Ability scores


class AbilityScores(TypedDict):
    str: int
    dex: int
    con: int
    int: int
    wis: int
    cha: int


# Currency
# Every character/NPC has this exact shape; defaults are 0/0/0.


class Currency(TypedDict):
    gp: int
    sp: int
    cp: int


# Inventory items


class InventoryItem(TypedDict):
    name: Required[str]
    quantity: Required[int]
    srd_index: NotRequired[str]
    equipped: NotRequired[bool]
    weight: NotRequired[int]
    notes: NotRequired[str]
    description: NotRequired[str]


# Feats and features


class FeatEntry(TypedDict):
    index: Required[str]
    name: Required[str]
    type: NotRequired[str]  # general | attack | trait — informational only
    options: NotRequired[dict]  # per-feat options (e.g., ability for Resilient)


class FeatureEntry(TypedDict):
    index: NotRequired[str]  # SRD-indexed features have this; NPC traits often don't
    name: Required[str]
    type: NotRequired[Literal["trait", "attack", "feature"]]
    description: NotRequired[str]
    # Attack-shaped features (NPC seed data)
    bonus: NotRequired[int]
    damage: NotRequired[str]
    damage_type: NotRequired[str]
    range: NotRequired[str]


# Spell slots
# Keys are spell levels as strings ("1" through "9"), values are slot counts.

SpellSlots = dict[str, int]


# Class resources
# `Character.resources` is `dict[str, Resource]`
# keyed by resource name ("rage", "ki_points", "channel_divinity", ...).


class Resource(TypedDict):
    current: int
    max: int
    resets_on: Literal["short_rest", "long_rest"]


# Skill check data on Turn
# The resolve route reads `modifier`, `dc`, `helper`. Status flows pending → resolved.


class HelperRef(TypedDict):
    character_id: str
    name: str


class CheckData(TypedDict):
    skill: Required[str]
    dc: Required[int]
    modifier: Required[int]
    roll_type: Required[Literal["d20", "advantage", "disadvantage"]]
    status: Required[Literal["pending", "resolved"]]
    helper: NotRequired[HelperRef]
    setup_prose: NotRequired[str]  # set after pre-roll narration
    roll: NotRequired[int]  # set on resolve
    total: NotRequired[int]  # set on resolve
    success: NotRequired[bool]  # set on resolve


# Combat state
# `Combatant` is a tagged union discriminated on `type`. Characters/npcs only
# reference the DB row (hp/ac live there); monsters carry their stats inline
# (no DB row). Modelling this as one wide TypedDict forced unguarded
# NotRequired access everywhere — the union lets the checker narrow on `type`.

CombatantType = Literal["character", "npc", "monster"]
CombatantTeam = Literal["players", "enemies"]


class _CombatantBase(TypedDict):
    id: str
    team: CombatantTeam
    name: str
    initiative_roll: int
    initiative_modifier: int
    zone: str | None
    conditions: list[str]
    is_alive: bool
    is_conscious: bool


class CharacterCombatant(_CombatantBase):
    type: Literal["character"]
    ai_controlled: NotRequired[bool]


class NpcCombatant(_CombatantBase):
    type: Literal["npc"]


class MonsterCombatant(_CombatantBase):
    type: Literal["monster"]
    srd_index: str
    hp: int
    max_hp: int
    ac: int
    temp_hp: NotRequired[int]
    speed: NotRequired[int]
    actions: NotRequired[list[dict]]  # SRD action list
    special_abilities: NotRequired[list[dict]]


Combatant = CharacterCombatant | NpcCombatant | MonsterCombatant


class EffectSave(TypedDict):
    ability: str
    dc: int


class CombatEffect(TypedDict):
    id: Required[str]
    name: Required[str]
    target_id: Required[str]
    remaining_rounds: Required[int]
    tick: NotRequired[Literal["start_of_target_turn", "end_of_target_turn", ""]]
    save: NotRequired[EffectSave]
    condition: NotRequired[str]
    damage: NotRequired[str]
    damage_type: NotRequired[str]
    mechanical_notes: NotRequired[str]
    source_id: NotRequired[str]
    spell_id: NotRequired[str]  # for concentration-linked effects


class TurnEconomy(TypedDict):
    action_used: bool
    bonus_action_used: bool
    reaction_used: bool
    movement_remaining: int


class CombatState(TypedDict, total=False):
    round: Required[int]
    turn_index: Required[int]
    combatants: Required[list[Combatant]]
    effects: Required[list[CombatEffect]]
    turn_economy: dict[str, TurnEconomy]  # keyed by combatant id


# Turn events
# Every combat mutation appends an event to Turn.events. There are ~15
# event types today (damage_applied, healing_applied, condition_applied,
# combatant_removed, death_save_rolled, etc), each a `type` discriminator
# plus an arbitrary `**result` payload. The shapes are too heterogeneous
# and dynamically spread to model as a closed TypedDict without forcing a
# cast at every emit site, so this stays an honest open mapping.

TurnEvent = dict[str, Any]


# Rest results


class CharacterRestResult(TypedDict):
    character_id: str
    name: str
    hp_restored: int
    hp_new: int
    resources_reset: list[str]
    spell_slots_restored: bool
    prepared_spells_cleared: bool  # True for prepared casters on long rest


class HitDieResult(TypedDict):
    character_id: str
    die_size: int
    roll: int
    con_modifier: int
    hp_gained: int
    hp_new: int
    hit_dice_remaining: int
