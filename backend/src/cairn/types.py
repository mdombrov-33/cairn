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


class LootIntent(TypedDict):
    npc_id: str
    item_name: str


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
    loot_intent: NotRequired[LootIntent]  # set when input is a pickpocket attempt


# Concentration
# JSONB shape on Character.concentration / NPC.concentration, and on monster
# entries inside combat_state. `source_effect_id` links to the CombatEffect this
# spell created, so a broken concentration save can remove the right effect.


class ConcentrationData(TypedDict):
    spell_name: str
    level: int
    source_effect_id: NotRequired[str | None]


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
    concentration: NotRequired[ConcentrationData | None]  # ephemeral — dies with combat_state


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


# Scene Director — meta-routing outputs and session handoff state


class CombatTrigger(TypedDict):
    hostile_npc_ids: list[str]


class SceneTransition(TypedDict):
    to_location_id: str
    reason: str


class ScenePreOutput(TypedDict):
    combat_trigger: CombatTrigger | None
    scene_transition_pull: SceneTransition | None
    pacing_nudge: str | None  # deterministic soft guidance for the narrator; None when fine


class ScenePostOutput(TypedDict):
    combat_ended: bool  # safety-net; combat_resolver is the primary authority
    scene_transition_push: SceneTransition | None
    time_advance_hours: int  # 0 unless scene_transition_push is also set
    act_progress: bool  # true if the DM narrated a core_event resolution
    # Scene-depth deltas (Slice 8). All default-empty — most turns change nothing.
    tension_delta: int  # signed; clamped into 0-10 by the writer
    mood: SceneMood | None  # None = unchanged
    discovered: list[str]  # free-form facts noticed without a roll
    threads_added: list[str]
    threads_resolved: list[str]
    npc_updates: list[NpcPresence]  # merged by npc_id onto existing presence (agenda/doing shifts)
    npc_departures: list[str]  # npc_ids that left the scene


# Session.pending_transition — scene-boundary detection-to-application handoff.
# Same shape as SceneTransition; named distinctly for the column's intent.
PendingTransition = SceneTransition


# Scene depth — a scene is a layered situation, not a description. Authored content
# is parsed into `Scene.authored` (JSONB, read-mostly); discovery/pacing state lives
# in dedicated columns + JSONB lists. Hidden details need a check to surface; secrets
# need an unlock condition. The narrator is only ever handed what the party has earned.

SceneMood = Literal["quiet", "charged", "hostile", "intimate"]


class HiddenDetail(TypedDict):
    check: str  # skill name, e.g. "investigation"
    dc: int
    reveals: str  # full reveal text — withheld from the narrator until the check passes


class SceneSecret(TypedDict):
    unlocked_by: str | list[str]  # discovered_facts key(s) that must be present
    content: str  # withheld from the narrator until unlocked


class SceneHook(TypedDict, total=False):
    hook: Required[str]
    to: str  # where this hook leads (act/thread id)


class AuthoredScene(TypedDict, total=False):
    atmosphere: str
    surface_details: list[str]
    hidden: list[HiddenDetail]
    secrets: list[SceneSecret]
    threads_in_air: list[str]
    hooks_out: list[SceneHook]


class NpcPresence(TypedDict, total=False):
    npc_id: Required[str]
    doing: str
    attentive_to: list[str]
    agenda: str  # what this NPC is trying to do right now, in-scene


# Session.pending_recovery — narrative-mode death recovery handoff.


class NarrativeRecovery(TypedDict):
    reason: str
    prior_events_summary: str


# Narrative profile — the deep prose identity shared by NPCs and companions.
# Stored in `NPC.narrative_profile` / `Character.narrative_profile` (JSONB). Only
# prose-for-prompts fields live here; mutable/queried bits (disposition, tier,
# companion_meta) stay as columns. Required at write time: name, personality, voice.
# Background NPCs may otherwise be sparse; authored/recurring should be full.

NpcTier = Literal["major", "recurring", "background"]


class NarrativeVoice(TypedDict, total=False):
    accent: str
    pace: str
    vocabulary: str
    speech_quirks: list[str]


class NarrativeGoals(TypedDict, total=False):
    immediate: str
    midterm: str
    life: str


class NarrativeRelationship(TypedDict, total=False):
    name: str
    relation: str
    status: str
    notes: str


class NarrativeProfile(TypedDict, total=False):
    name: Required[str]
    personality: Required[str]
    voice: Required[NarrativeVoice]
    race: str
    age: int
    profession: str
    physical: str
    backstory: str
    goals: NarrativeGoals
    prejudices: list[str]
    relationships: list[NarrativeRelationship]
    private_facts: list[str]


# Companion approval — lives in `Character.companion_meta` (JSONB, is_companion=True).
# Approval/mood mutate frequently and gate behavior, so they stay a column rather than
# nesting in the profile blob. mood is derived (see companions.derive_mood).


class ApprovalLogEntry(TypedDict):
    turn_id: str
    delta: int
    reason: str
    total: int


class CompanionMeta(TypedDict, total=False):
    approval: int
    mood: str
    personal_goal: str
    secret: str | None
    approval_log: list[ApprovalLogEntry]


# companion_reflector structured output — one entry per companion whose standing moved.


class ApprovalDelta(TypedDict):
    companion_id: str
    delta: int
    reason: str


# Dialogue — the entity view the dialogue agent roleplays from. Carries the full
# narrative profile; companions additionally carry current approval/mood.


class DialogueEntity(TypedDict):
    name: str
    profile: NarrativeProfile
    disposition: str
    approval_band: NotRequired[str]
    mood: NotRequired[str]
