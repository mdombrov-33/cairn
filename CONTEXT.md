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

**Campaign**:
One player's isolated, persistent playthrough of a campaign template. Its events, relationships,
settings, and memory diverge from every other campaign.
_Avoid_: Game, session, campaign template

**Act**:
A major authored phase of a campaign template, organized around a central conflict and core events.

**Location**:
A persistent place in the campaign world. A location can host many different scenes over time.
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

## Play

**Session**:
The technical continuation record for a campaign run, carrying the current location, time, scene,
party, and combat state. It is not a user-visible sitting at the table.
_Avoid_: Campaign, play session

**Turn**:
One player input and its resulting mechanical events and Dungeon Master narration. A turn may pause
for player input before it is complete.

**Turn Suspension**:
A pending decision that stops a turn before narration can finish, while preserving enough state to
resume the same turn later.
_Avoid_: New turn, failed turn

**Skill Check**:
A player-facing resolution of an uncertain non-combat action: the system establishes the check,
the player supplies the roll, and narration describes the outcome.

**Campaign Epilogue**:
The concluding story after a campaign reaches its ending.
_Avoid_: Post-turn background work

## Actors

**Character**:
A full player-style character sheet belonging to a campaign. A character is either the player's
character or a recruited companion.

**Player Character**:
The character directly controlled by the player and used as the default subject of their actions.
_Avoid_: Companion, NPC

**Companion**:
A recruited character who travels with the player character. Campaign settings decide how much of
the companion's combat and non-combat agency belongs to the player or the AI.
_Avoid_: NPC, combat ally

**NPC**:
A non-player world entity such as an enemy, merchant, quest giver, or unrecruited potential
companion. Recruitment converts an eligible NPC into a companion character.
_Avoid_: Character

**Party**:
The player character together with all recruited companions in the campaign.

**Combatant**:
Any character, NPC, or temporary monster currently participating in combat. Combatant is a role in
an encounter, not a persistent actor category.

## Control and mechanics

**Agency Preset**:
A named bundle of campaign settings that assigns mechanical and narrative decisions between the
player and AI. Individual controls can override the preset.

**Campaign Settings**:
The campaign-owned choices governing agency, death, checks, narration, and content boundaries.
They change how one campaign plays without changing world canon.

**Reaction**:
An out-of-turn combat action triggered by another combatant's event and limited by the reactor's
reaction economy.

**Narration**:
The Dungeon Master's prose rendering of facts and outcomes established by the game state and rules.
Narration may interpret facts but does not replace them.
