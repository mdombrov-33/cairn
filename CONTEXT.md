# Cairn

Cairn is a persistent AI-guided tabletop role-playing game. Its language separates authored
world canon, one player's evolving campaign, the actors inside that campaign, and the mechanical
events that shape play.

## World and campaign

**World**:
The shared authored canon in which multiple campaigns can take place. A world contains enduring
lore and one or more campaign templates.

**Campaign Template**:
An authored starting scenario within a world, including its premise, cast, locations, acts, and
premade characters. Each campaign begins from one template.
_Avoid_: Scenario, adventure, module

**Published Content Version**:
An immutable published snapshot of a Campaign Template and its required World inputs. A Campaign
pins one version at creation; later authoring edits create a version for new Campaigns and never
silently change an existing playthrough.

**Campaign**:
One player's isolated, persistent playthrough of a campaign template. Its events, relationships,
settings, and memory diverge from every other campaign.
_Avoid_: Game, session, campaign template

**Campaign Status**:
The lifecycle state of a Campaign. `active` may be played and changed; `completed` and
`ended_dead` are readable immutable records. The player may explicitly delete any status, removing
only campaign-owned state.

**Act**:
A major authored phase of a campaign template, organized around a central conflict and core events.

**Core Event**:
An explicitly keyed, authored milestone required to complete an Act. The engine records its
resolution idempotently; narration may propose a resolution but cannot advance an Act by itself.

**Location**:
A persistent place in the campaign world. A location can host many different scenes over time. It
has a campaign-scoped persistence UUID and an immutable authored key; authored content and
player-facing map/travel references use the key, while persistence and ownership use the UUID.
_Avoid_: Scene

**Scene**:
The current dramatic situation at a location, including who is present, what is happening, and what
has been discovered or left unresolved.
_Avoid_: Location, room

**Authored Scene**:
A scene whose atmosphere, visible and hidden details, people, tensions, and exits were deliberately
written into the campaign template rather than generated to fill a gap.

**World Lore**:
Authored facts shared by every campaign in a world.
_Avoid_: Campaign memory

**World Bible Entry**:
A fact learned or created during one campaign, such as an event, relationship, quest, person, or
place. It is campaign memory, not shared world canon.
_Avoid_: World lore

**Campaign Journal**:
The append-only player-facing record of discoveries. Each entry has a source Turn/time and topic
links; Codex pages group the entries but never overwrite or delete their history.

**Player Projection**:
An intentionally player-safe read model. It contains only facts the player is entitled to see;
persistence models, private NPC material, and agent context are never public transports.

**Observation**:
A player-visible, time-stamped cue grounded in current authoritative state—such as a health band or
observable behavior. It is not a leak of private values or motives. A durable fact learned from an
Observation is a Discovery, not an Observation itself.

**Passive Check**:
A server-resolved Perception or Insight check triggered by the current situation rather than an
active player request. Campaign settings control when its result is disclosed, never whether eligible
characters are evaluated.

**Adjudication Dossier**:
The bounded, authoritative fact view used to evaluate one player action. It contains the immediate
moment and only relevant facts; it is not campaign memory or a player-visible projection.

**Combat Posture**:
An NPC or enemy's authoritative current stance in combat: fight, defend, flee, surrender, or parley.
It is informed by commitments and current pressure facts, but is not inherently player-visible.

**Tactical Sketch**:
The compact published zone topology and stable visual layout for one combat Scene. It is stylized for
play, but its zones, paths, terrain, cover, and typed hazards are authoritative. Every depicted
mechanical feature corresponds to published state; purely descriptive scene details are not tactical
mechanics.

**Hazard Template**:
A published, server-owned combat hazard contract. It defines a named trigger, legal resolution,
player-safe presentation, and rules-baseline-validated mechanical values; scene prose and LLM output
cannot create or alter one during play.

**Creative Affordance Card**:
The bounded fiction-facing capabilities and limits of an exposed spell, feature, or item. It supports
creative adjudication but never grants an effect beyond that capability's executable rules contract.

**Atomic Creative Resolution**:
One player intent that combines a creative objective with real capabilities or environment state and
spends all applicable costs once. Any check or contest belongs to that same resolution.

**Tactical Fact**:
A sourced, scoped, and expiring authoritative fact that affects a current situation without being a
permanent D&D condition, such as temporary cover loss or a created distraction.

**Affordance Inventory**:
The hidden, structured list of a Scene's usable objects, terrain features, exits, hazards, and allowed
state changes. It may contain unrevealed details but is fixed before player use.

**Environment Palette**:
The constrained categories of plausible mundane details a Scene may introduce and record during play.
It prevents convenient retroactive invention while allowing a setting to feel lived-in.

## Play

**Session**:
The one persistent runtime record for a campaign, carrying the current location, time, scene,
party, and combat state. It is not a user-visible sitting at the table; Continue, refresh, and a
second device resume this same record.
_Avoid_: Campaign, play session

**Turn**:
One player input and its resulting mechanical events and Dungeon Master narration. A turn may pause
for player input before it is complete.

**Turn Suspension**:
A pending decision that stops a turn before narration can finish, while preserving enough state to
resume the same turn later. A combat level-up suspension is the deliberate exception that lets a
PC with a previously earned pending level-up resolve it at the start of that PC's own combat turn.
_Avoid_: New turn, failed turn

**Death Mode**:
The Campaign rule governing a Player Character's terminal-down state: Pacifist provides safe
non-lethal recovery, Narrative turns confirmed death into recorded story fallout, and Hardcore ends
the Campaign on confirmed death.

**Recovery Outcome**:
A published, typed and prerequisite-validated aftermath of a Narrative-mode confirmed death. It
records a recovery/Scene transition and any declared fallout before narration; it is not a freeform
Dungeon Master invention.

**Camp Scene**:
A dedicated Scene entered by a long-rest request. It supports camp-specific play and preparation;
long-rest recovery and time advance only when the Party explicitly settles for the night.

**Camp Event**:
An authored, eligible, optional moment that may occur in a Camp Scene. Its stable identity and typed
outcome are recorded before it is narrated.

**Skill Check**:
A player-facing resolution of an uncertain non-combat action: the system establishes the check,
the server rolls it, and narration describes the outcome.

**Spell State**:
The distinct authoritative categories that determine a Character's legal magic: known cantrips,
known spells, Wizard spellbook spells, currently prepared spells, and always-prepared grants. A
derived available-spell list is not character state.

**Campaign Epilogue**:
The authoritative narration of the final completed Turn, rendered with stable campaign facts after
the campaign reaches its ending. It is not a separate best-effort generation job in v1.
_Avoid_: Post-turn background work

**Recap**:
A server-owned, on-demand read model of a campaign's current state. In v1 it combines current
state, recorded unresolved goals, and recent completed-turn narration excerpts; it is not a
persisted or newly generated “story so far” artifact.

## Actors

**Character**:
A full player-style character sheet belonging to a campaign. A character is either the player's
character or a recruited companion.

**Player Character**:
The one character directly controlled by the player in a campaign and used as the default subject
of their actions. A campaign cannot begin play without its Player Character.
_Avoid_: Companion, NPC

**Premade**:
A version-pinned authored Player Character that a player may select to create one campaign-owned
clone. It is not a live link to authoring content or a partially custom mechanical build.

**Player Identity**:
The player-owned, editable non-mechanical description of their Player Character: physical
description, personality, voice, backstory, and goals. It excludes NPC/Companion private facts and
relationship state.

**Player Identity Draft**:
A non-persisted suggested Player Identity, such as one returned by Weave, which the player may edit,
partially apply, or discard.

**Portrait Selection**:
An optional Character-owned presentation choice that references either a global curated gallery asset
or a user-owned uploaded asset with its crop metadata. It is not an arbitrary URL or a generated
image request.

**Conversation Portrait**:
The non-combat Play presentation of the one NPC currently speaking with or directly facing the
Party. It appears only after that NPC is visibly revealed and is not the combat turn queue.

**Visual Brief**:
The player-safe, versioned appearance facts and art direction used to request one generated NPC
portrait. It excludes private narrative profile facts and raw agent context.

**Character Sheet Projection**:
The player-safe, server-derived explanatory view of one Character's current mechanics, legal
capabilities, and rule references. It is distinct from the mutable Character record.

**Canonical Runtime Sheet**:
The one validated typed mechanical shape used by live Characters and compatible NPC/Companion data.
Player creation, authored import, level-up, Premade cloning, and recruitment may have different
inputs, but must normalize into this shape before runtime play or player projection.

**Rule Detail**:
Version-pinned normalized reference material retrieved by stable rule key for a sheet card. It is not
the character-specific calculation or an invitation for the client to derive mechanics.

**Rules Compendium**:
The global, version-pinned player reference library for licensed rules and clearly labelled Cairn
implementation notes. It is reachable from the authenticated Campaign Browser hub and in-play
navigation, separate from Campaign Journal discoveries, and not personalized to a Character's build.

**Cairn Rules Profile**:
The version-pinned compatible rules selection a Campaign runs: the 2014 SRD 5.1 chassis plus each
explicitly audited 2024 SRD addition and Cairn implementation note. It names its source and
divergences; it is neither an accidental data mixture nor a claim to be unmodified 2014 or 2024 D&D.

**Alignment**:
A Player Character's explicit nine-position roleplay orientation. It is chosen by the player and
does not mechanically constrain actions or authorize an agent to choose on the player's behalf.

**Companion**:
A recruited character who travels with the player character. Campaign settings decide how much of
the companion's combat and non-combat agency belongs to the player or the AI. Companions arise only
through recruitment of an NPC in the authored Companion Roster, not player character creation.
_Avoid_: NPC, combat ally

**Companion Definition**:
The version-pinned authored record that makes one NPC permanently recruitable as a Companion. It
connects that NPC to its sheet, recruitment policy, personal arc, Camp Events, and deterministic
advancement/preparation priorities.

**Recruitment Gate**:
An authored condition that must be satisfied before an NPC in the Companion Roster can join the Party.
Its identity and resolution are authoritative; it is not free-form recruiter prose.

**NPC**:
A non-player world entity such as an enemy, merchant, quest giver, or unrecruited potential
companion. Its location is its persistent current whereabouts; a Scene's present cast determines
whether it is currently available for interaction. Recruitment converts an eligible NPC into a
companion character; a non-roster NPC can be a temporary ally but not a permanent Companion.
_Avoid_: Character

**Party**:
The player character together with all recruited companions in the campaign.

**Combatant**:
Any character, NPC, or temporary monster currently participating in combat. Combatant is a role in
an encounter, not a persistent actor category.

**Combat Turn**:
The current conscious Combatant's exclusive opportunity to use its legal action economy. Reactions
are separate, trigger-bound interruptions; a planner never selects a different combatant's turn.
_Avoid_: Planner turn, actor-selected advance

## Control and mechanics

**Campaign Settings**:
The complete campaign-owned choices governing agency, death, checks, narration, and content
boundaries. They are explicit values with server-owned defaults, not a preset plus hidden overrides;
they change how one campaign plays without changing world canon.

**Reaction**:
An out-of-turn combat action triggered by another combatant's event and limited by the reactor's
reaction economy.

**Companion Dialogue Control**:
The Campaign Setting that assigns a Companion's spoken dialogue to AI, a player-approved suggestion,
or a deliberate player-authored Speak-as line. It does not assign mechanical authority.

**Narration**:
The Dungeon Master's prose rendering of facts and outcomes established by the game state and rules.
Narration may interpret facts but does not replace them.

## Dispatch

The global, authenticated, read-only product-news tab in the Campaign Browser hub. It communicates
Cairn updates and clearly labelled future work; it is not a Campaign event log, a Codex source, or
a public Landing surface.
