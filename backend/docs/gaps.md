# Pre-slice product and engine gaps

This is the canonical register of unresolved behavior across Cairn's current backend, persistence,
HTTP/SSE contracts, agents, authored content, and Ember UI reference. It is intentionally broader
than frontend work: visualizing the product exposed contradictions that already exist in the engine.

Current implementation facts remain owned by [architecture.md](architecture.md). Planned work and
sequencing remain owned by [roadmap.md](roadmap.md). The Ember HTML files are a product reference,
not proof that a route or mechanic exists.

## Gate before the next development slice

Do not start Slice 11, or any other implementation slice, while an item in the open register below
is merely assumed away. Every item must first receive one explicit disposition:

1. **Fix or implement it** in the current contract, with the verification required by `AGENTS.md`.
2. **Remove or simplify it** in code, public transports, documentation, and Ember where the feature
   does not earn its complexity.
3. **Assign it to a named future slice** and make today's behavior honest and safe until then.

“The frontend can infer it,” “the LLM will probably do it,” and an unlabeled mock affordance are not
resolutions. A disposition can be small; it does not require building every ambitious option. The
purpose of the gate is to decide what Cairn actually is before adding another layer.

Labels used below:

- **FIX** — verified defect or isolation/integrity failure; the outcome is not a product preference.
- **DECIDE** — two or more coherent products are possible, and the current code does not choose one.
- **ALIGN** — code, transport, documentation, and/or Ember currently tell different stories.

The final section lists work that already has a named future owner. Those entries are retained here
to keep all discovered seams in one place, but they are not open blockers unless their existing
scope is changed.

## Campaign entry, world state, and lifecycle

### G1 — Recap has no authoritative source (**DECIDE**)

**Current evidence.** `Session.summary` is exposed by `SessionResponse`, but no workflow writes it.
Scene summaries and `scene_progress_summary` are internal narrator context. `DAY_SUMMARY` entries are
available through `/calendar`, but they are not a current-situation summary and cannot supply the
active scene, party condition, pending interruption, or unresolved campaign threads. No endpoint
assembles the Recap shown by Ember.

**Unknown.** Is Recap a persisted editorial artifact, a read model assembled on demand, or a mix of
both? What is its time boundary, and what should it show before the first completed turn, during a
pending check/reaction, after character death, and after campaign conclusion?

**Resolve by.** Choose one server-owned representation and refresh policy. If `Session.summary` is
not that representation, remove it from the intended contract. Lock first-entry, resumed, pending,
empty, and concluded cases with contract tests; the client must not reconstruct canon by scraping
rendered prose.

### G2 — “Session” and Continue do not form a usable lifecycle (**DECIDE**)

**Current evidence.** The domain glossary calls a Session a technical continuation record rather
than a play sitting. `Session.ended_at` is never written, yet `sessions.start` rejects a second active
session forever. Campaign responses do not include the active session id, there is no list or
get-active-session-by-campaign route, and `POST /campaigns/{id}/sessions` returns a conflict instead
of the existing record. A reloaded or second-device client therefore cannot discover what Continue
should open unless it retained the UUID locally.

**Unknown.** Is there exactly one permanent runtime record per campaign, or can a campaign contain
multiple technical sessions? If it is permanent, why do `started_at`, `ended_at`, and `summary`
describe a closeable sitting? If it is multiple, what closes one and carries state into the next?

**Resolve by.** Pick one lifecycle. The small option is idempotent get-or-create with the active
session discoverable from the campaign read model and removal of unused close-session semantics.
The other option needs explicit close/resume rules and history. Define refresh, reconnect, death,
completion, and deletion behavior either way.

### G3 — Current place, authored travel, and the map graph disagree (**FIX + DECIDE**)

**Current evidence.** `Location.connections` is stored but no player-safe location/scene read surface
exists. Seeded connections point to author slugs such as `tavern_back_room`, while `_seed_locations`
drops each `id_slug`. `scene_create` parses a transition target as a UUID, so the normal authored
route selected by Scene Director is discarded as invalid. Even when a scene transition succeeds,
it never updates `Session.current_location_id`; session reads and combat zone seeding can therefore
continue using the starting place while the open Scene points elsewhere. The starting location is
also selected with an unordered “first row” query rather than an authored start marker.

**Unknown.** What is a location's stable identity: author key, database UUID, or both? Is the Ember
map a read-only discovered route chart, or may clicking a known adjacent place initiate travel? What
distinguishes visited, discovered-but-unvisited, rumored, hidden, and currently reachable places?

**Resolve by.** First fix the single-source-of-truth defects: retain/resolve stable author keys,
scope targets to the campaign, update current location with the scene transition, and author an
explicit start. Then define a player-safe campaign-world projection with current scene/location,
visible descriptions, discovery state, adjacency, and travel eligibility. Keep drawing coordinates
client-owned unless accurate authored geography becomes a separate requirement.

### G13 — The Recap entry trigger is navigation policy, not persisted truth (**DECIDE**)

**Current evidence.** Ember currently enters Recap from Campaign Browser → Continue and offers a
small Review recap action in Play. The backend has no browser-visit or “last opened” boundary, and a
Session is not a user-visible sitting.

**Unknown.** Should every deliberate Continue pass through Recap while refresh/reconnect stays in
Play, or should a time/cross-device threshold decide it? Is Review recap available during pending
checks and combat?

**Resolve by.** Lock the exact navigation rule after G1/G2 choose the source and lifecycle. Keep it
frontend-owned unless cross-device “last opened” state is genuinely required. Test that reconnecting
an SSE stream does not accidentally become a recap visit.

### G16 — Campaign Browser cards cannot be populated from campaign responses (**ALIGN**)

**Current evidence.** `CampaignResponse` contains ids, name, raw template UUID, status,
`current_act_index`, settings, unused `member_ids`, and `created_at`. Ember cards also show scenario
title, current act title, day, current location, last played time, and completion information. The
active session id is absent as described in G2. There is no authoritative “last activity” timestamp
or completed timestamp/duration. Campaign creation also resolves any seeded template key without
requiring the template to be published, while the intended browser lists published templates. The
create request calls that string key `template_id`, but the response uses `template_id` for the row's
UUID, so one field name means two different identities across the same resource.

**Unknown.** Which card facts are product-essential, and what event updates “last played”: turn
creation, completed narration, rest, settings edit, or opening the campaign? Does duration mean real
time or in-world time?

**Resolve by.** Define one compact campaign-summary read model instead of issuing a web of per-card
requests or fabricating values. Include only chosen facts and their sources; remove the rest from
Ember. Published template/world labels should be player-facing while internal namespaces and raw
ownership machinery should stay internal.

### G17 — Party membership and the active player character have no enforced invariant (**DECIDE**)

**Current evidence.** A session can start with no character. The public character-create body allows
`is_companion=true`, so clients can bypass recruitment and the four-companion cap. It also permits
multiple non-companion PCs. Skill checks and several services silently select the first
non-companion row as “active,” with database order deciding ties. `get_party_for_session` includes
dead and abandoned rows; `Campaign.member_ids` is exposed but never drives membership; and the
`abandoned` character status is never written because dismissal converts/deletes companions.

**Unknown.** Is v1 exactly one active PC plus recruited companions, or is a player-owned party
supported? When may the active PC be deleted or replaced? What remains on the roster after death or
dismissal?

**Resolve by.** State and enforce the v1 invariant at campaign/session/character boundaries. If it is
one PC, internalize companion creation, reject a second active PC, require a PC before play, and
remove `member_ids`/`abandoned` if they have no job. If party play is intended, add an explicit active
subject/ownership model instead of “first row wins.”

### G32 — Act progress and campaign conclusion have two conflicting writers (**FIX + DECIDE**)

**Current evidence.** `campaigns.advance_act` knows the template length, marks the campaign
`completed`, and writes a generic `CAMPAIGN_CONCLUDED` entry. Normal play does not call it.
`PostTurnEpilogue._run_scene_director_post` increments `current_act_index` directly whenever the LLM
says one core event resolved; it records no completed core-event identity, has no idempotence, and
can increment beyond the final act without completing the campaign. The post-output field
`combat_ended` is described as a safety net but `_post_has_effect` ignores it and no writer applies
it. Ember's rich final epilogue has no persisted prose, completion time, or duration source.

**Unknown.** Does one core event advance an act, must all required events resolve, or is progression
an authored/DM judgment? Is the final narration itself the epilogue, or should Cairn generate and
persist a separate record?

**Resolve by.** Establish one authoritative, idempotent transition function and a trackable act
completion criterion. Route normal play through it, clamp/finalize the last act, and either implement
or remove `combat_ended`. Define the minimum persisted conclusion artifact that Ember can honestly
render.

### G33 — Campaign statuses do not define mutation or deletion policy (**FIX + DECIDE**)

**Current evidence.** Middleware freezes mutations only for `ended_dead`; a `completed` campaign can
still accept turns, rests, settings changes, characters, and sessions despite Ember calling it a
read-only record. The same middleware blocks DELETE for `ended_dead`, so a dead campaign cannot be
removed even if deletion should be allowed. Hard deletion simply deletes the Campaign row, while
Session and Character foreign keys lack cascade behavior, so deleting a played campaign can fail on
referential integrity.

**Unknown.** Which operations are legal for `active`, `completed`, and `ended_dead`? Is deletion a
hard cascade, soft archive, or unsupported once play starts? Does “the record stays” mean readable,
undeletable, or only immutable?

**Resolve by.** Publish and enforce a status/operation matrix, including owner deletion. Align the
foreign-key strategy and HTTP behavior with the chosen lifecycle and add integration coverage for
used campaigns, not only empty ones.

### G39 — NPC presence has competing sources and the shipped cast is often nowhere (**FIX + DECIDE**)

**Current evidence.** Current-scene narration reads `Scene.npcs_present`; Scene Director pre-pass and
thin-scene fallback read living `NPC.location_id` rows; dialogue/recruitment use campaign-wide fuzzy
name lookup with location only as a tie-breaker. Seeded scenario NPC YAML does not assign a location,
and `blueprint_kwargs` performs no placement resolution. The opening thin scene can therefore have
no cast, while a player can still address a campaign-wide NPC by name. `npc_departures` removes only
Scene presence, generated dialogue NPCs are assigned a location but not added to Scene presence,
and combat initiation can see a different roster from narration.

**Unknown.** Is presence scene-owned, location-owned, or derived? How does an NPC enter, leave, move,
get generated, get recruited, or become addressable without allowing conversations and theft across
the map?

**Resolve by.** Choose one authoritative presence model and make all dialogue, recruitment, combat,
loot, context, and player reads use it. Normalize authored placement at seed time and define updates
for every transition listed above. Add an end-to-end test proving the opening scenario cast is
visible, addressable, and combat-eligible only where it is actually present.

### G45 — Scene discoveries use prose while secrets and hooks expect opaque keys (**FIX + DECIDE**)

**Current evidence.** A hidden detail has only `check`, `dc`, and display prose in `reveals`; a
successful check copies that prose into `Scene.discovered_facts`. Secrets instead declare
`unlocked_by` keys. The shipped back-room secret waits for `false_drawer_found`, but the related
Investigation check records “The writing desk has a false drawer…” and no normal workflow writes the
key. Tests unlock the secret only by manually inserting the key. Authored `hooks_out` similarly carry
hook/target keys but no runtime reader or transition uses them. Scene Director can also add arbitrary
prose discoveries, so reference integrity cannot be validated.

**Unknown.** Are discoveries stable authored facts with ids and display text, or are they an
append-only bag of prose? What exact event unlocks a secret or outbound hook, and should hooks affect
act/scene progression at all?

**Resolve by.** Give authored discoveries stable ids and validate every secret/hook reference, or
make unlock conditions deliberately match canonical reveal text. Persist id, player-facing text,
source turn, and visibility separately if history needs them. Wire `hooks_out` to an explicit owner
or remove the dead authoring concept.

### G46 — Lore scoping stores selectors that current reads ignore (**FIX + DECIDE**)

**Current evidence.** A CampaignTemplate stores `always_on_lore_keys` so a scenario can opt additional
world chunks into every prompt, but no runtime reader uses the field; narrative context includes only
chunks whose world-level `always_on` boolean is true. Separately, Campaign creates a
`world_bible_namespace` and every WBE stores it, but reads, uniqueness, and isolation all use
`campaign_id`; no query filters by namespace. Both unused selectors are exposed or propagated as if
they own behavior.

**Unknown.** Is always-on selection world-global or scenario-specific? Is namespace future lineage/
cross-campaign memory, or redundant with Campaign id?

**Resolve by.** Before Slice 13 designs retrieval keys and indexes, choose one scoping model. Wire and
validate template-selected lore or remove the field. Give namespace a concrete isolation/lineage job
or remove it from public and persistence contracts rather than carrying two identifiers forever.

### G47 — Published content is half snapshot and half live, with no version policy (**DECIDE**)

**Current evidence.** Campaign creation clones scenario/world-cast NPCs and Locations, so those rows
diverge per playthrough. The campaign keeps foreign keys to mutable CampaignTemplate and World rows,
and narrator/director context reads current acts, calendars, and shared world lore every turn.
`make seed` upserts those rows in place and does not reconcile authored files that were removed.
Reseeding can therefore change an active campaign's act/canon while leaving its cloned locations and
cast on the old content, and can leave ghost lore/premades in the database. Publication status does
not make a template immutable.

**Unknown.** Does a campaign pin a published content version, snapshot all scenario inputs, or accept
live author updates? If updates are allowed, who migrates already-diverged campaign state and how are
removed facts handled?

**Resolve by.** Define immutable publication/versioning before persistent real campaigns exist.
Options are versioned World/Template rows pinned by Campaign, a complete creation snapshot, or a
deliberate migration system for live content. Make seed reconciliation and draft/published mutation
rules match that choice.

## Character creation and progression

### G4 — Gallery and uploaded portraits cannot be persisted (**ALIGN**)

**Current evidence.** `Character.portrait_url` is returned, but neither `CharacterCreate` nor
`CharacterPatch` can set it. No gallery manifest, upload/storage service, file validation, crop
metadata, or authorized portrait mutation exists. Ember presents gallery selection, local upload,
crop/reposition, skip, and a separate disabled generation affordance.

**Unknown.** Is the stored reference an immutable asset id, a URL, or an original plus crop? Are
gallery assets global, world-specific, or campaign-specific?

**Resolve by.** Either implement the chosen Phase-A gallery/upload lifecycle with file type/size,
ownership, crop, replacement, and deletion rules, or remove those choices from the Phase-A
reference. A local preview that disappears after creation is not acceptable. AI generation remains
separate under G14.

### G5 — Player identity is loose JSON and the Weave plan uses drifting names (**DECIDE**)

**Current evidence.** Manual `narrative_profile` editing exists as an unrestricted dictionary. The
domain vocabulary uses fields such as `physical`, `backstory`, `personality`, structured `voice`,
and `goals`; older frontend planning mentions separate `bio` and `voice_traits`. Ember correctly
makes manual editing primary and Weave an optional draft, but there is no typed player request/
response schema or Weave endpoint.

**Unknown.** Which identity fields are editable/optional for a PC, and which are private or
agent-owned for an NPC/companion? Can a player clear individual fields? Does Weave return a draft or
mutate the character?

**Resolve by.** Lock one typed player identity schema and use it for create, patch, read, and future
Weave output. Keep Weave mechanical-free and draft-only unless deliberately changed. Do not create a
second lossy identity vocabulary for the frontend.

### G7 — Descriptive character sheets lack a complete rules lookup contract (**ALIGN**)

**Current evidence.** Character responses mostly contain rule names/indices and current values.
Several SRD catalogs are exposed, but there is no audited lookup path for every skill, save, feature,
feat, condition, spell, weapon, armor, resource, and proficiency Ember explains. JSONB feature shapes
also vary between created, leveled, and authored characters.

**Unknown.** Which descriptions are SRD-owned, which are character-specific computed explanations,
and which current fields have no trustworthy definition? Should the client cache normalized
catalogs or request individual records?

**Resolve by.** Inventory every sheet row against current SRD routes and JSON shapes. Add only narrow
missing reads and a stable normalization strategy; do not duplicate the full rules catalog into
`CharacterResponse`. Remove sheet claims for mechanics Cairn does not actually support.

### G8 — Alignment is a closed UI choice but an unvalidated free string (**ALIGN**)

**Current evidence.** Alignment data ships in SRD files and Ember uses a defined 3×3 compass, but no
alignment catalog route exists and character creation accepts any string.

**Resolve by.** Use the already planned alignment catalog/validation contract, or explicitly make a
closed frontend list authoritative and validate it on write. The current hybrid is neither flexible
freeform alignment nor a reliable nine-choice system.

### G9 — Spell state is not valid at character creation (**FIX + DECIDE**)

**Current evidence.** `spell_choices` is not validated for class, spell level, count, duplicates, or
caster type and is copied wholesale into `spells_known`. Prepared casters start with an empty
`prepared_spells` list. Subrace spells, subclass/domain always-prepared spells, and subclass spell
features are not applied. Ember's cleric example distinguishes cantrips, available spells, selected
preparations, and always-prepared domain spells, but the persisted character cannot round-trip that
meaning.

**Unknown.** At level 1, what does the player choose for each caster family: cantrips, known spells,
spellbook spells, or daily preparations? Are legal defaults acceptable, or must creation collect all
choices?

**Resolve by.** Define the day-one state per caster type and validate every submitted spell against
the same SRD source. Apply racial/subclass grants without consuming ordinary picks. Test creation →
character read → first combat/long rest for representative known, prepared, spellbook, and pact
casters.

### G18 — Premades can be stored and listed internally but cannot be selected (**FIX + DECIDE**)

**Current evidence.** Premade rows and a query exist, and `Character.created_from_premade_id` is meant
to distinguish onboarding. No public route exposes selection/cloning, `CharacterCreate` carries no
premade id, and no writer sets `created_from_premade_id`. Reposting a premade sheet through custom
create would misclassify it and trigger custom-character intro behavior.

**Unknown.** Does the player clone an immutable template snapshot, create from a premade key with
allowed identity edits, or import the sheet into the custom forge? What happens when seeded premade
content changes after campaigns already exist?

**Resolve by.** Define and implement one atomic premade-selection contract, including template
membership, publication, validation, editable fields, and provenance, or remove special premade
onboarding/provenance entirely.

### G19 — Character creation advertises 5e outputs that the builder does not create (**FIX + DECIDE**)

**Current evidence.** A submitted subrace need not belong to the race and required subraces are not
enforced. A later-level subclass may be chosen at level 1. Background-overlapping class skills are
accepted even though Ember says they will not be wasted. `_build_inventory` reads only fixed class
equipment and ignores `starting_equipment_options`; classes such as Fighter can start empty.
Background equipment, starting gold, background features, language grants/choices, and subclass
features/proficiencies are omitted. Character has no language field at all, and class feature choices
such as a Fighter's fighting style have no creation input/state. Equipment legality also does not
enforce armor proficiency or the documented shield/off-hand constraint.

**Unknown.** Is Cairn implementing full level-1 choices, curated deterministic starter kits, or an
intentionally simplified rules subset? If simplified, which choices and benefits are deliberately
collapsed?

**Resolve by.** Pick the v1 creation floor and make Ember, validation, and the resulting sheet agree.
Do not silently discard benefits the UI uses to sell a race/class/background. Cover representative
classes whose SRD equipment is entirely option-based and a race/background with language choices.

### G20 — XP and level-up have no trustworthy foreground lifecycle (**FIX + DECIDE**)

**Current evidence.** Normal structured combat does not award encounter XP; XP changes only through
an unrestricted player HTTP `grant-xp` route or the local MCP tool. No `level_up_pending` event is
emitted. Level-up checks only the number of `new_spells`, not spell existence, class list, maximum
level, cantrip/leveled split, duplicates, or already-known state; the preview provides a count rather
than legal candidates. Feat prerequisites and epic-boon eligibility are not enforced. Raising
Constitution does not retroactively adjust prior-level HP, and taking Tough computes its initial
retroactive bonus from the old level because `char.level` is incremented later. Replacing spell-slot
state with the new level table can also refill spent slots. Companion auto-leveling exists, but only
after an XP source happens to call it.

**Unknown.** Is progression encounter XP, milestone advancement, or an explicit DM/admin grant?
When does the player see and enter the level-up flow, and may play continue while it is pending?

**Resolve by.** Choose the advancement source and remove the player self-award route unless that is
deliberately the product. Emit/derive an authoritative pending state, validate every level-up choice,
and prove preview/apply parity. If Cairn uses milestones, remove unused XP promises rather than
leaving a cheat endpoint as the only path.

### G40 — Authored character/NPC JSON bypasses canonical shape validation (**FIX**)

**Current evidence.** Seeded premade sheets, NPC profiles, companion sheets, features, resources,
and inventory are stored as raw JSONB. Recruitment copies authored companion JSON directly into a
Character. The shipped Bram sheet, for example, stores `recharge: short_rest` plus an extra `name`
inside a resource, while the current `Resource` contract requires `resets_on`; rest logic therefore
will not reset it. Authored feature and inventory objects also differ from builder/leveling shapes.
API schemas expose many of these collections as `Any`, so drift survives to clients.

**Resolve by.** Validate and normalize authored content at seed/import/conversion boundaries against
the same domain shapes used by runtime characters, failing loudly on stale keys. Add a seeded-content
contract test. If authored full sheets are too expensive to keep aligned, reduce them to inputs for
one canonical builder instead of maintaining a second character constructor.

## Player-safe reads, memory, and access

### G6 — Public transports expose private and engine-only state (**FIX**)

**Current evidence.** `CharacterResponse` returns complete companion `narrative_profile` and
`companion_meta`, including possible `private_facts`, `secret`, raw approval totals, and numeric
approval-log deltas. NPC list/get returns every seeded NPC with full stats, inventory, spells,
disposition/tier, and private narrative profile whether met or not. `SessionResponse` and
`CombatResponse` return raw `combat_state`; monster exact HP/AC/actions and pending reaction frames
include pre-rolled outcomes, internal plan queues, cursor, settings snapshot, and facts.

**Unknown.** Which discovered NPC facts, companion goals/reasons, enemy condition bands, initiative
facts, and tactical data should a player know? Is the raw NPC API intended only for trusted agents?

**Resolve by.** Define separate internal/agent and player-facing projections. Derive vague approval
bands/mood server-side, filter cast by earned presence/discovery, and expose a combat DTO containing
only usable player information plus an opaque checkpoint. Enforce secrecy in serialization, not in
React, and lock exact JSON with contract tests.

### G34 — Lore storage cannot support the current Codex promise (**FIX + DECIDE**)

**Current evidence.** `WorldBibleEntry.revealed_at_turn_id` claims to gate player visibility, but no
writer sets it. `/campaigns/{id}/lore` returns every entry and the response omits the reveal marker.
Entries are one mutable fact per `(campaign, type, key)` and upsert overwrites content. Ember instead
shows only revealed knowledge grouped into people/places/threads, with first-met context, dated
append-only history, open questions, and “nothing deleted.”

**Unknown.** Is Codex a flat view of current canonical facts, an append-only player journal, or an
entity read model synthesized from world bible + scenes + turns? Are WBE entries themselves all
player-visible, making `revealed_at_turn_id` misleading?

**Resolve by.** Choose the product. Either simplify Codex to the current fact store and remove false
history/reveal claims, or add an explicit player-memory projection/history and populate/filter reveal
state server-side. Never return hidden lore and hope the client omits it.

### G35 — Day summaries and the exposed clock are not reliable chronology (**FIX + DECIDE**)

**Current evidence.** When one or more days elapse, `maybe_roll_days` gathers every completed DM
response in the Session and writes that same concatenation for each newly crossed day. Turns carry
no in-game timestamp or day boundary, so multiple days can receive identical campaign-to-date text.
Standalone rest time emits no Turn event. The player receives only raw
`in_game_hours_elapsed`; world calendar length and the server's Day/time-of-day label remain
internal.

**Unknown.** Is the calendar an accurate per-day journal, a periodic recap, or decorative elapsed
time? What anchors a turn/rest/travel event to an in-world time, especially when several days pass at
once?

**Resolve by.** Define chronological anchors and write genuinely bounded summaries, or relabel and
simplify the feature. Include derived player-facing day/time in the campaign state read model if the
UI must show it; do not make clients reproduce world-calendar rules from a raw hour counter.

### G36 — Turn history exposes dead fields and no coherent pending-interaction view (**DECIDE**)

**Current evidence.** `Turn.dice_rolls` is reserved and never written. `Turn.checkpoint_id` is only
set by `update_turn_response`'s optional argument, but current callers leave it null. Skill and
companion suspensions live in loose `check_data`; reaction suspension instead lives inside raw
`combat_state` and stores its owning turn in an internal frame. `events` and pause settings are loose
engine JSON exposed directly by `TurnResponse`.

**Unknown.** Is turn history an audit/debug record, the player transcript, or both? What single read
tells a reconnecting client which interaction is pending and how to resume it without seeing the
engine continuation?

**Resolve by.** Remove unused public fields or give them a real lifecycle. Define a typed,
player-facing turn/transcript and pending-moment projection with opaque resume ids. Internal event,
settings, and plan state can remain persisted without becoming the browser contract.

### G44 — Mechanical “events” are persisted but not streamed as SSE (**FIX + DECIDE**)

**Current evidence.** `application.combat.emitter.emit` only appends a dictionary to the current
`Turn.events`; it has no connection to the route's async generator. Turn SSE currently yields
`turn_start`, prose tokens, `turn_end`, check/roll events, companion proposals, and reaction prompts.
Events such as `combat_started`, `turn_advanced`, movement, damage, healing, conditions, effects,
concentration, death, inspiration, and time changes are not sent live even though the archived
frontend contract and Ember interactions treat that vocabulary as SSE input. `turn_start` itself is
yielded only after non-streaming preparation has already run Scene Director/intent resolution and may
have applied travel, combat entry, or rest, so it is not the causal beginning of the operation.

**Unknown.** Should structured mechanics be delivered causally during the stream, or should the
client refetch authoritative state after narration and derive a non-causal presentation diff? Which
events are transcript history versus transient animation instructions?

**Resolve by.** Choose and type one delivery contract. If live events are kept, collect/forward them
in mutation order without making database append code pretend to be a transport bus, and define
reconnect/idempotence with Slice 11. If refetch is the contract, update Ember/archive labels and
identify the state/version that makes each animation safe. Persisted loose dictionaries alone are
not a live SSE API.

### G42 — Fire-and-forget epilogues have no ordering or freshness contract (**FIX + DECIDE**)

**Current evidence.** `_narrate` emits `turn_end` and only then independently schedules LoreKeeper,
Scene Director post-pass, companion reflection, and scene summarization. The browser receives no
completion/version event for those derived writes; failures are logged but not reflected in player
state. A fast next turn can begin before the previous turn's scene deltas, act progress, lore, or
approval land, and epilogues from successive turns can complete out of order.

**Unknown.** Which state is guaranteed current at `turn_end`, and which is explicitly eventual? Must
the next turn wait for prior scene/act bookkeeping even if the previous response did not? How should
the frontend know when to invalidate Codex, Party, map, and campaign-summary reads?

**Resolve by.** Define per-session ordering and visibility. Options include a serialized epilogue
queue plus a next-turn barrier, moving correctness-critical scene/act writes before `turn_end`, or an
explicit derived-state version/status the client can observe. Slice 11 is a natural implementation
owner if assigned, but retry logic alone does not answer the product freshness question.

### G43 — Pending moments and live streams do not exclude new mutations (**FIX + DECIDE**)

**Current evidence.** `turns.prepare` does not reject a new turn when an earlier Turn has a pending
skill check or companion proposal, or when `combat_state.pending_reaction` exists. A new combat turn
can therefore bypass or overwrite a suspended reaction; multiple unresolved check turns can coexist.
Settings, rests, equipment, spell preparation, leveling, loot, and character mutations also have no
shared policy for an in-flight SSE turn. G11 separately notes that spell preparation is not a
checkpoint at all.

**Unknown.** Is there exactly one foreground moment per Session? Which side-panel mutations are safe
between turns, during a stream, during combat, and while a checkpoint waits? Is cancellation allowed,
and what does reconnect do with an abandoned moment?

**Resolve by.** Establish one authoritative pending/in-flight state and operation matrix. Reject,
queue, or explicitly allow each mutation; make resumes/cancellation idempotent; and expose the state
through the player-safe projection from G36. The focused modal in Ember cannot be the only lock.

### G37 — Several campaign-scoped operations authorize one id and act on another (**FIX**)

**Current evidence.** Character deletion verifies ownership of the path campaign, then deletes by
global `character_id` without verifying membership, allowing a known id from another campaign to be
deleted. NPC get verifies the path campaign and then fetches a global `npc_id`, allowing a foreign
NPC to be read. Scene transition fetches a global location id without checking it belongs to the
campaign before opening a new scene. Death-save and several lower-level helpers also accept unrelated
session/entity ids, though their current MCP exposure is explicitly local/trusted.

**Resolve by.** Fix all player HTTP/workflow paths to fetch through campaign/session-scoped queries
and add negative cross-owner and same-owner-cross-campaign tests. Audit paired identifiers
systematically. Keep the unauthenticated MCP exception documented as local development only; do not
use it to justify weak scoping in public services.

## Settings and agency

### G21 — Settings overrides can be added but not cleared (**FIX + DECIDE**)

**Current evidence.** Sparse override models reject nulls and `update_settings` deep-merges patches.
Changing a preset retains all prior overrides, `{}` removes nothing, and there is no field-level or
whole-preset reset operation. Once a value becomes custom, the public contract cannot restore
inheritance from a preset.

**Unknown.** Does selecting a preset clear all overrides, preserve them, or ask? Can one control be
reset to “use preset” independently?

**Resolve by.** Define reset semantics and encode them explicitly: replacement writes, a dedicated
reset list/action, or permitted deletion markers validated before persistence. Ember must show
effective value versus custom override and offer every supported reset path.

### G41 — The “one settings snapshot per turn” boundary is porous (**FIX + DECIDE**)

**Current evidence.** Turn preparation resolves a settings snapshot and persists it with skill-check
and companion-action pauses; reaction frames also carry a copy. The UI says changes apply from the
next turn. However, combat execution and reaction resumption re-read `reaction_control` from the live
Campaign, and damage re-reads the live death mode. Settings PATCH remains available while a turn or
reaction is pending. A mid-turn edit can therefore change resolution semantics even though narration
or another part of the same continuation uses the captured snapshot.

**Unknown.** Is a turn's full rules policy immutable from `turn_start` through every nested resume,
or do selected settings take effect immediately? What is the boundary for standalone rests and
other non-Turn commands?

**Resolve by.** Make the snapshot authoritative through all continuations, or explicitly prohibit/
version settings edits while a moment is in flight. Pass resolved settings into mechanics instead of
performing hidden live reads. Document separate request-time semantics for commands that do not
belong to a Turn.

### G22 — Companion Dialogue AI/Suggest/Player is not three behavior modes (**FIX + DECIDE**)

**Current evidence.** The setting accepts `ai | suggest | player`, but `resolve_dialogue` treats both
non-AI modes identically and returns only a meta note that dialogue is player-controlled. There is no
draft, approval checkpoint, selected speaking subject, companion-text request, or resume route.
Meanwhile every narrator context still includes companions and the SceneNarrator prompt explicitly
tells the model to voice occasional companion lines regardless of the dialogue setting.

**Unknown.** In Player mode, does the player type a line while temporarily speaking as the
companion, choose from responses, or merely prevent unsolicited speech? In Suggest mode, what draft
is shown, who edits/approves it, and what happens on reconnect? May the narrator still describe body
language?

**Resolve by.** Either build an explicit dialogue suspension with subject, draft/manual response,
confirm/edit/skip, and narrator constraints; simplify to a clearly defined AI/Player switch; or
remove the control. Update narrator context so the chosen mode is actually enforced. The current
copy “Player waits for you to supply the companion's response” does not specify an interaction.

### G23 — Companion Checks and Equipment controls are dead; Leveling controls unrelated spells (**FIX + DECIDE**)

**Current evidence.** `companion.checks` is persisted and included in Tactical but no production
code reads it; every active skill check selects the first PC. Equipment mode `ai` only rejects player
equip/unequip requests—no agent or deterministic manager equips companion gear—so “AI manages legal
equipment” currently means locked. Companion auto-leveling is real, but the same leveling flag also
decides whether long-rest spell preparation is automatic, a separate responsibility. Equipment
legality itself omits proficiency and off-hand/shield rules.

**Unknown.** Are companion-originated active checks supported? Who chooses their actor and dice? Is
equipment meant to auto-optimize, be player-owned, or simply immutable? Should daily spell
preparation have its own agency rule?

**Resolve by.** Implement each advertised control with a real trigger and suspension/automation path,
rename it to its actual effect, or delete it. Do not keep configuration whose only behavior is to
block an endpoint. Separate spell preparation from leveling unless one broader “character
management” control is deliberately chosen and explained.

### G24 — Passive Perception/Insight settings are narration hints, not checks (**ALIGN + DECIDE**)

**Current evidence.** The settings are passed only into the SceneNarrator prompt. There is no passive
Insight statistic, deterministic passive-check evaluation, recorded result, or visibility event.
Authored hidden details move into `discovered_facts` only after an active rolled check. Ember says
Silent records a result, Surfaced creates a visible field note, and On demand withholds it until
asked—none of those artifacts exist.

**Unknown.** Are these true mechanics controlling automatic discoveries/social reads, or tone policy
for how the narrator hints at things? Who is eligible when multiple party members have different
passives?

**Resolve by.** Implement a deterministic party passive-check/reveal event with visibility policy,
or rename/simplify the controls as narration behavior and remove claims about recorded results. If
passive Insight is kept, define how it is derived and what authored data it tests.

### G26 — The reaction prompt advertises a serverless 20-second deadline (**FIX + DECIDE**)

**Current evidence.** The executor includes `countdown_seconds=20` in the prompt but persists no
deadline and never auto-resolves. A pending reaction remains indefinitely until `/reactions` receives
a decision. A client-only timer can race reconnects, background tabs, or two devices and cannot
authoritatively apply the engine recommendation.

**Unknown.** Should play wait forever, should the browser submit a decision after a decorative timer,
or should the server own an expiry and deterministic default? Does silence take the recommendation
or decline?

**Resolve by.** Remove the countdown, explicitly make it a non-authoritative client convenience, or
persist a server deadline/default and make resumption idempotent. Align Ember copy and test reconnect
before and after expiry.

## Play mechanics

### G10 — Dying, death saves, combat state, and death modes do not form a state machine (**FIX + DECIDE**)

**Current evidence.** Character/NPC damage writes database HP but, unlike monster damage, does not
update the combatant's `is_alive`/`is_conscious` flags. A 0-HP character can remain eligible in
initiative and act. Death saves exist only as a local tool, do not verify the character belongs to
the session or is a PC, and three failures return `outcome=dead` without setting Character status or
combat-state flags. Attacks on a 0-HP character do not add failures. Companion death is not resolved
at combat end. Long rests include all character rows and can heal dead/abandoned members. Narrative
and Hardcore consequences run only when combat ends.

Ember copy also conflicts: the campaign-creation screen says Pacifist reaches 0 HP and becomes
capture/loss, while code clamps the PC to 1; it says Hardcore has no death saves, while current code
uses ordinary saves until death is established. The Settings screen describes current code more
closely.

**Unknown.** Define every transition for conscious → downed → stable/revived/dead, including natural
1/20, damage at zero, healing, stabilization, combat end, companion handling, and each death mode.
Decide whether Hardcore uses death saves and whether Pacifist has a concrete consequence system or
simply cannot drop below 1.

**Resolve by.** Implement one authoritative state machine shared by damage, healing, initiative,
rests, death saves, campaign status, and player projections. Then decide automatic versus the already
planned player-rolled suspension. Update all three Ember surfaces to one exact death-mode contract.

### G11 — Rest mixes missing mechanics, ephemeral prose, and a non-blocking spell-prep request (**FIX + DECIDE**)

**Current evidence.** A short rest restores resources and Warlock slots but always reports zero HP;
`roll_hit_die` has no player HTTP/rest checkpoint and its local tool can be called without proving a
short rest is in progress. Ember currently implies automatic hit-die healing.
Standalone rest endpoints stream narrated prose without creating a Turn, so the narration and time
event disappear from history after reload; blocked and confirmation-required rests are narrated too.
The natural-language rest intent does create a Turn, but has no `confirm_risky` input and therefore
cannot complete the same risky-rest confirmation flow. A long rest clears a PC prepared list and
returns `spell_prep_required`, but play is not suspended and `prepare-spells` may be called at any
time. Rest applies to every campaign Character regardless of status.

**Unknown.** Does short rest auto-spend dice, open a hit-die chooser, or restore no HP? Is rest a
transcript turn, a mechanical event with fixed copy, or intentionally ephemeral? Must preparation
complete before the next turn?

**Resolve by.** Choose one flow and persist only what the player is meant to revisit. Enforce party
eligibility and any spell-prep checkpoint. If rest stays outside Turn history, do not generate prose
that looks canonical and then discard it.

### G12 — Tactical zones mix authoritative numbers with LLM prose and illustrative geometry (**FIX + DECIDE**)

**Current evidence.** Combat zones contain topology, categorical close/far distances, cover category,
numeric cover bonuses, difficult terrain, and free-text hazards. The ZoneSeeder LLM supplies both
cover category and raw bonuses; normalization checks ids but does not derive or cross-check the
numbers. Hazards have no mechanics. Edges are not required to be symmetric. Ember draws irregular
rooms/paths and labels them as a tactical plate even though no coordinates or polygons exist.

**Unknown.** Which zone fields are mechanics versus narration? Are connections directional? Are
hazards informational until explicitly resolved, or should they carry triggers/DC/damage? Is the
visual a route diagram or a floor plan?

**Resolve by.** Derive rules numbers from validated categories server-side and validate topology.
Either make hazards explicitly descriptive or give them typed mechanics. Keep node silhouettes,
contours, and paths illustrative; accurate floor plans require a future authored-geometry contract,
not inference from prose.

### G25 — Active skill-check authority and submitted dice are internally inconsistent (**FIX + DECIDE**)

**Current evidence.** RulesLawyer receives deterministic character modifiers but returns `modifier`
as LLM output, which the server trusts rather than recomputing. It always acts for the first PC, so
companion checks and multiple-PC intent are impossible. It can return advantage/disadvantage and Help,
but `ResolveRequest` accepts only one ordinary d20 plus an optional second roll specifically for
inspiration; runtime ignores the check's `roll_type` entirely. Spending inspiration without a second
roll is allowed and consumes it for no added chance. Authored hidden details are evaluated again
against their own DC, which RulesLawyer never sees, so `roll_result.success` can be true while the
specific discovery the action targeted remains hidden.

**Unknown.** Who chooses the acting character? Which parts are DM judgment (need, skill, DC,
circumstance) and which must be deterministic (modifier, proficiency, advantage dice)? Does the
player submit both physical dice, or does the server roll additional dice?

**Resolve by.** Make actor identity explicit, recompute modifiers from authoritative state, and define
one dice-submission contract for straight/advantage/disadvantage/Help/inspiration interactions.
Choose one authoritative outcome/DC relationship for authored discoveries. Require every necessary
die or roll it server-side, and test all combinations.

### G27 — Loot transfer proves ownership but not fictional eligibility (**FIX + DECIDE**)

**Current evidence.** `/loot` will move any named item or currency from any NPC in the campaign to any
campaign character. It does not require the source to be dead, present, discovered, surrendered, or
issued as available loot. The full NPC response leaks inventory. Pickpocket intent resolves a name
campaign-wide without current-presence scoping. The helper `list_dead_in_scene` exists but the public
route does not use it.

**Unknown.** Is loot source-authorized by a pending “spoils available” record, inferred from a dead
current-scene NPC, or allowed after any narrated permission? How are containers and shared party
currency represented?

**Resolve by.** Define an authoritative available-loot source and make transfer consume only it, or
limit v1 to dead/present NPCs with explicit rules. Keep pickpocket as a check-owned transaction
scoped to current presence. The UI must render server-issued availability, not inspect private NPC
inventory.

### G28 — Inspiration can be stored and spent only on one check path, but cannot be earned normally (**FIX + DECIDE**)

**Current evidence.** SceneNarrator's prompt tells a streaming text model to call
`grant_inspiration`, but that narrator has no tool loop. The only grant path is the local MCP tool.
Skill-check resumption can spend inspiration, subject to the dice flaw in G25. Structured combat has
no inspiration input or operation, while Ember exposes inspiration as an available character
resource.

**Unknown.** Who awards inspiration in normal play—structured post-pass, narrator output, deterministic
rule, or human control? Can it be spent on combat attacks/saves as well as active checks?

**Resolve by.** Add a real foreground/post-turn award event and the intended spend surfaces, or remove
the prompt instruction and visible affordance until the mechanic exists. Keep award idempotence and
player-visible reason text explicit.

### G29 — The main combat executor cannot deliver the character-sheet actions it presents (**FIX + DECIDE**)

**Current evidence.** Combat plans support move, weapon attack, cast, ready, apply condition, advance,
and end. Non-damage spells spend/validate resources but only append “effect was recorded”; they do not
heal, buff, impose an effect, or establish concentration. Cure Wounds and Bless therefore do not work
through the normal turn path despite appearing in Ember. Class features, bonus actions, item use,
Dodge, Dash, Help, Disengage-as-an-action, Grapple/Shove, stabilization, and inspiration are not
represented. Conditional feat behavior is mostly left for an LLM to “read” even though the typed
executor has no operation that can apply many of those rules; even Heavy Armor Master's stored
damage-reduction option has no damage-path reader. Lower-level tools implement some mechanics, but
the structured foreground planner cannot call them.

**Unknown.** What is the honest v1 playable action floor? Does natural-language freedom promise
general 5e adjudication, or a deliberately narrow combat subset?

**Resolve by.** Publish and enforce a supported-action matrix. Implement the minimum actions needed
by shipped classes/premades and current UI, or narrow/remove unsupported sheet affordances and return
honest errors. Do not narrate a no-op spell as though its mechanics happened.

### G30 — Combat plans are typed but not turn-authoritative (**FIX**)

**Current evidence.** `execute_plan` does not verify that an operation's `actor_id` is the current
living/conscious combatant. `advance_turn.actor_id` is ignored. Apply-condition trusts the planner to
apply any SRD condition without action economy, source, save, spell, or feature; EndCombat trusts any
actor/outcome without checking encounter state. Ready/attack/move/cast validate different fragments,
but there is no common actor/turn gate. Character/NPC HP-state synchronization is separately broken
as described in G10. Scene Director's `combat_ended` safety field is dead as described in G32.

**Resolve by.** Add one executor precondition layer for current actor, alive/conscious status, team/
control, action economy, and operation-specific authority. Reject impossible plans atomically or with
a deliberately defined partial-plan policy. Test hostile actor spoofing, downed actors, early end,
free conditions, and actor-less turn advance.

### G31 — Session RNG repeats the same rolls (**FIX**)

**Current evidence.** `session_rng(session)` constructs a new `random.Random` from the unchanged seed
on every call. Repeated attacks, saves, damage rolls, and death saves therefore restart the same
sequence; separate helpers also use module-global randomness, so randomness is both predictable and
inconsistent. The model comment acknowledges that no runtime RNG state is persisted.

**Resolve by.** Choose a production randomness contract: persist an RNG cursor/state for deterministic
replay, or use a non-replay secure/system source while recording authoritative outcomes. Keep tests
deterministic through injection rather than reseeding every live roll. Add a regression test proving
consecutive rolls advance.

### G38 — Only a player can start combat, and only against already-instantiated NPC ids (**DECIDE**)

**Current evidence.** Scene Director pre-pass may create `combat_trigger` only when the player's input
clearly starts a fight, and only with ids from its present-NPC list. The normal graph has no path for
an enemy ambush/world-initiated attack or a generic SRD monster encounter. Monster creation exists
only through the local `start_combat` MCP tool. The presence divergence in G39 can leave even authored
NPC enemies unavailable to the trigger.

**Unknown.** May the DM/world initiate danger, or is v1 intentionally player-initiated? How does an
authored encounter introduce SRD monsters without pre-creating NPC rows, and what tells the UI that
combat entry is authoritative?

**Resolve by.** Define encounter-initiation authority and the allowed enemy sources. Implement the
smallest typed trigger that covers shipped scenarios, or constrain scenario authoring/product copy
to present NPC conflicts. Do not rely on an unauthenticated local developer tool for ordinary play.

## Already owned future work — recorded, not open blockers

These items were part of the earlier Ember gap file or were encountered during this audit, but the
roadmap already gives them a future owner. They satisfy the pre-slice gate only while current code and
reference copy label them honestly; changing their scope reopens the relevant decision.

### G14 — AI portrait generation remains Phase B

No provider, generation agent, moderation policy, storage lifecycle, entitlement, or cost control
exists. Keep generation disabled and visibly Phase B. This does not resolve the independent Phase-A
gallery/upload contract in G4.

### G15 — Authentication, accounts, billing, plans, and admin remain Phase B

Slices 14/14.5 own real identity, access control, inference cost tracking, and entitlements. Ember may
show visual direction only; it must not invent pricing, usage, checkout, or admin authorization. The
development `X-User-Id` and local-only MCP boundaries remain explicit until then.

### Scheduled work that should not be rediscovered as a new gap

- **Slice 11:** timeouts, failed/incomplete turns, SSE event durability, atomicity, retries, fallbacks,
  shutdown, and related operational recovery.
- **Slice 12:** prompt/agent evaluation and CI gates.
- **Slice 13:** world-bible retrieval, embeddings, search, reranking, and retrieval degradation.
- **Slices 14/14.5:** production authentication, cost/rate controls, plans, and entitlements.
- **Slices 15/15.5:** the frontend package and its chosen stack; published template browsing;
  alignment catalog work; subrace spell grants; the optional Weave draft assistant; and the planned
  player-rolled death-save resumption. G5, G9, and G10 remain open where the underlying current
  domain contract is broader than those scheduled endpoints.
- **Phase B after frontend:** generated portraits and any real billing/admin flows.
- **Deferred:** multiplayer, additional game systems, accurate authored floor-plan/geographic
  geometry, and advanced combat mechanics beyond the explicitly chosen v1 action floor.

## Closure record

When grilling this register, record each disposition in the documentation that owns the resulting
fact: current behavior in `architecture.md`, future ownership in `roadmap.md`, durable rationale in a
sparing ADR, and visual behavior in Ember. Then remove the resolved entry from this file rather than
turning it into completed-slice history. The final empty open register is the observable signal that
the next development slice may begin.
