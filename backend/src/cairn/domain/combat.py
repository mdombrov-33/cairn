"""Combat-owned JSONB shapes and value types."""

from typing import Any, Literal, NotRequired, Required, TypedDict


class ConcentrationData(TypedDict):
    spell_name: str
    level: int
    source_effect_id: NotRequired[str | None]


CombatantType = Literal["character", "npc", "monster"]
CombatantTeam = Literal["players", "enemies"]
ZoneDistance = Literal["close", "far"]


class CombatZone(TypedDict):
    id: str
    name: str
    description: str
    cover: str
    cover_ac_bonus: int
    cover_save_bonus: int
    difficult_terrain: bool
    hazard: str | None
    distances: dict[str, ZoneDistance]


class ZoneSeed(TypedDict):
    zones: list[CombatZone]
    player_start: str
    enemy_start: str


class _CombatantBase(TypedDict):
    id: str
    team: CombatantTeam
    name: str
    initiative_roll: int
    initiative_modifier: int
    zone: str | None
    speed: int
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
    actions: NotRequired[list[dict]]
    special_abilities: NotRequired[list[dict]]
    concentration: NotRequired[ConcentrationData | None]


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
    spell_id: NotRequired[str]


class TurnEconomy(TypedDict):
    action_used: bool
    bonus_action_used: bool
    reaction_used: bool
    movement_remaining: int


ReactionDecision = Literal["take", "decline"]
ReactionName = Literal[
    "opportunity_attack",
    "shield",
    "absorb_elements",
    "counterspell",
    "readied_action",
    "sentinel",
]


class ReactionOption(TypedDict):
    name: ReactionName
    label: str


class ReactionRecommendation(TypedDict):
    decision: ReactionDecision
    chosen_reaction: str | None


class PendingReaction(TypedDict):
    checkpoint_id: str
    trigger: str
    description: str
    options: list[ReactionOption]
    recommendation: ReactionRecommendation
    plan_queue: list[dict[str, Any]]
    execution_cursor: int
    reaction_stack: list[dict[str, Any]]
    depth: int
    facts: list[str]
    frame: dict[str, Any]


class ReadiedAction(TypedDict):
    reactor_id: str
    trigger: dict[str, Any]
    operation: dict[str, Any]
    expires_round: int


class CombatState(TypedDict, total=False):
    round: Required[int]
    turn_index: Required[int]
    combatants: Required[list[Combatant]]
    effects: Required[list[CombatEffect]]
    zones: Required[list[CombatZone]]
    turn_economy: dict[str, TurnEconomy]
    pending_reaction: PendingReaction
    readied_actions: list[ReadiedAction]


TurnEvent = dict[str, Any]
