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

**Decision (2026-07-13).** V1 Recap is an on-demand, server-owned read model, not an
LLM-generated or persisted `Session.summary`. It must contain the current location/scene, active
Party condition, in-world time, any pending Turn Suspension, explicitly recorded unresolved goals,
and excerpts from recent *completed* Turn narrations. It must not invent a “story so far,” derive
canon by scraping prose on the client, or show stale state as current.

**Implementation consequence.** Add one Recap endpoint/read service that composes its named sources
and defines an explicit bounded window for narration excerpts. Do not write `Session.summary` for
this purpose; remove it from the public intended contract if no other owner needs it. Recap must
render coherently before the first completed turn, during a suspension, after PC death, and after
campaign conclusion without concealing those statuses.

**Current evidence.** `Session.summary` is exposed by `SessionResponse`, but no workflow writes it.
Scene summaries and `scene_progress_summary` are internal narrator context. `DAY_SUMMARY` entries are
available through `/calendar`, but they are not a current-situation summary and cannot supply the
active scene, party condition, pending interruption, or unresolved campaign threads. No endpoint
assembles the Recap shown by Ember.

**Unknown.** Is Recap a persisted editorial artifact, a read model assembled on demand, or a mix of
both? What is its time boundary, and what should it show before the first completed turn, during a
pending check/reaction, after character death, and after campaign conclusion?

**Resolve by.** Implement the read model and contract-test first-entry, resumed, pending, empty,
dead, and concluded cases. The client must not reconstruct canon by scraping rendered prose.

### G2 — “Session” and Continue do not form a usable lifecycle (**DECIDE**)

**Decision (2026-07-13).** V1 has exactly one persistent Session per Campaign for the campaign's
entire lifetime. It is a runtime record, not a real-world sitting: Continue, refresh, and another
device resume the same Session. There is no close-and-create-next-session flow or session history
in v1.

**Current evidence.** The domain glossary calls a Session a technical continuation record rather
than a play sitting. `Session.ended_at` is never written, yet `sessions.start` rejects a second active
session forever. Campaign responses do not include the active session id, there is no list or
get-active-session-by-campaign route, and `POST /campaigns/{id}/sessions` returns a conflict instead
of the existing record. A reloaded or second-device client therefore cannot discover what Continue
should open unless it retained the UUID locally.

**Unknown.** Is there exactly one permanent runtime record per campaign, or can a campaign contain
multiple technical sessions? If it is permanent, why do `started_at`, `ended_at`, and `summary`
describe a closeable sitting? If it is multiple, what closes one and carries state into the next?

**Resolve by.** Implement idempotent get-or-create and make the Session discoverable from the
campaign read model. Remove `ended_at` and other unused close-session semantics. Define refresh,
reconnect, death, completion, and deletion behavior consistent with the decision.

### G3 — Current place, authored travel, and the map graph disagree (**FIX + DECIDE**)

**Decision (2026-07-13).** A Location has two identities with distinct jobs: a campaign-scoped
persistence UUID for storage and ownership, and an immutable authored key (for example
`tavern_back_room`) for authored exits, template links, and player-facing map/travel references.
The public client does not receive raw persistence UUIDs as travel targets; the server resolves an
authored key only within the current campaign and applies reachability/discovery rules there.

**Implementation consequence.** Preserve the authored key while seeding campaign locations; make
connections and authored-scene transitions refer to it; resolve it to the campaign's UUID inside
the transition service; and update `Session.current_location_id` atomically with the new open
Scene. Add an authored starting-location marker/key rather than selecting an unordered row. The
campaign-world read model should expose the key plus only player-safe discovery/adjacency state;
the UI never guesses a UUID or fabricates the graph.

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

**Resolve by.** Implement the decision above. Then define a player-safe campaign-world projection
with current scene/location, visible descriptions, discovery state, adjacency, and travel
eligibility. Keep drawing coordinates client-owned unless accurate authored geography becomes a
separate requirement.

### G13 — The Recap entry trigger is navigation policy, not persisted truth (**DECIDE**)

**Decision (2026-07-13).** Campaign Browser → Continue opens Recap only after the Campaign has at
least one completed Turn. Recap provides one explicit Enter Play action. A new Campaign goes
directly to first play; refresh, SSE reconnect, and a direct Play deep link return directly to
Play. Review Recap is available from Play at any time, including while a Turn Suspension is pending,
because it is read-only.

**Implementation consequence.** Keep this navigation policy in the client. It requires no
“last-opened” persistence and must not create or replace a Session. The Recap endpoint still
represents the live server state when reached by either path.

**Current evidence.** Ember currently enters Recap from Campaign Browser → Continue and offers a
small Review recap action in Play. The backend has no browser-visit or “last opened” boundary, and a
Session is not a user-visible sitting.

**Unknown.** Should every deliberate Continue pass through Recap while refresh/reconnect stays in
Play, or should a time/cross-device threshold decide it? Is Review recap available during pending
checks and combat?

**Resolve by.** Implement the client routing rule after the Recap read endpoint exists. Test that
first play, Browser Continue, refresh, SSE reconnect, direct Play, and Review Recap follow the
decision and that reconnecting does not accidentally become a recap visit.

### G16 — Campaign Browser cards cannot be populated from campaign responses (**ALIGN**)

**Decision (2026-07-13).** The Browser receives one purpose-built `CampaignSummary` per Campaign:
campaign id, player-chosen name, scenario title, status, current act title, current Location name,
in-world day, `last_played_at`, and the persistent runtime Session id used by Continue. V1 exposes
no fabricated duration, raw template/world ids, or values inferred by the client. Optional scenario
cover treatment is a later presentation concern, not an API placeholder.

**`last_played_at` definition.** Update it only when fiction or mechanics advance: a completed
Turn, resolved Rest, recruitment, or level-up. Do not update it for settings changes, card opens,
Recap reads, reconnects, or other passive reads.

**Naming consequence.** A campaign-create request selects an authored `template_key`. `template_id`
is reserved for an actual persistence UUID where it must be exposed internally; public player flows
should receive labels/keys rather than raw ownership identifiers.

**Implementation consequence.** Add a summary read service rather than a per-card request fan-out.
It must use the Session and Location decisions from G2/G3, honor published-template eligibility,
and provide stable empty/new/terminal-state values.

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

**Resolve by.** Implement and contract-test summary values for a new campaign, one with completed
play, a suspended turn, and each terminal status. Update Ember to use only the chosen fields.

### G53 — There is no curated product-news surface in the authenticated player hub (**DECIDE**)

**Product opportunity.** Cairn needs a deliberate, visually rich read-only Dispatch/News surface in
the authenticated Campaign Browser: the player hub used before selecting or creating a Campaign.
It can carry product updates, shipped features, development notes, and clearly labelled planned
work, so the browser feels like a living play hub rather than a bare campaign picker. It is not a
social feed, campaign event log, or a way to expose internal roadmap documents. Landing remains
lean and does not host Dispatch.

**Current evidence.** There is no frontend runtime, content-post model, publishing workflow,
authenticated browser-hub route, or user-notification/read-state model. The repository's roadmap
and archive are internal planning documents and cannot become customer copy by accident.

**Decision (2026-07-13).** Dispatch is an authenticated tab of the Campaign Browser only. Landing
must remain intentionally lean; a person reaches Dispatch only after sign-in, alongside campaign
selection/creation and later account/billing hub functions. Phase A shows a featured latest post and
a reverse-chronological archive. Posts may be explicitly labelled **Shipped**, **In development**, or
**Planned**; the latter two are product communication, not delivery promises. There is no CMS,
commenting, reactions, subscriptions, unread state, personalization, or per-account read tracking.

Phase-A posts are version-controlled, deliberately authored Markdown/frontmatter with stable slug,
title, summary, publication date, status, tags, optional cover asset, and body. The player receives
a read-only projection. Product copy must be written for players and must never directly render
roadmap/archive/internal planning text. Dispatch is global product content: it has no Campaign
foreign key, cannot change gameplay state, and does not appear in a Campaign's Codex or transcript.

**Implementation consequence.** Define the post schema, publication/review owner, authenticated
read projection, planned-work wording, and link policy. A later real admin surface may replace the
authoring workflow only after Phase B account/admin work. Add an Ember Campaign Browser hub
reference with Dispatch after the content contract is selected.

### G17 — Party membership and the active player character have no enforced invariant (**DECIDE**)

**Decision (2026-07-13).** V1 has exactly one Player Character per Campaign. A Campaign cannot
start play without that character. Companions are created only by recruiting eligible NPCs; the
public character-create route cannot create companions, and a second Player Character is rejected.
There is no PC replacement feature in v1.

**Curated companion roster decision (2026-07-13).** “Eligible NPC” means an NPC referenced by a
version-pinned, authored Companion Definition—not any NPC that happens to be recurring or has been
LLM-generated/promoted. The curated roster should be substantial (target: 10+ authored candidates
across published world/scenario content), each with a stable key, NPC identity, authored playable
sheet, recruitment policy/conditions, personal arc, Camp Event references, and deterministic
advancement/preparation priorities. The existing
Recruiter remains the story-facing accept/refuse/conditional adjudicator for one such candidate; it
does not create a new companion identity or make a non-roster NPC permanently recruitable. Non-roster
NPCs may act as temporary allies but cannot convert into full Party Companions in v1.

**Recruitment-gate decision (2026-07-13).** A Companion Definition declares its typed recruitment
gates, referencing authored discoveries, core events, relationship state, or declared quest outcomes.
The Recruiter may select an eligible gate and voice an accept/refuse/conditional response, but cannot
invent an unresolvable free-text obligation. Gate resolution is recorded by the same authoritative
discovery/event/relationship service that owns its referenced fact; a later recruitment request sees
the resolved gate rather than relying on model memory.

**Lifecycle consequence.** A dead PC remains the campaign's historical Player Character but cannot
act. A dismissed companion leaves the active Party and returns to an appropriate NPC/world state;
it is not silently deleted. Define the retained history and re-recruitment rule with the dismissal
workflow rather than leaving an unused `abandoned` status as implicit behavior.

**Implementation consequence.** Enforce the invariant in creation, session start, recruitment,
query helpers, and database constraints where practical. Give every caller an explicit active PC
query; remove `first non-companion row wins`, public `is_companion`, and unused membership fields
unless a real ownership role remains. Party read models must distinguish active members from
historical/dead/dismissed records. Replace the `tier == recurring` recruitment fallback with
Companion Definition lookup and validate every referenced NPC/sheet/arc/Camp Event at published
content-version time. Validate recruitment-gate references at the same point and replace the current
free-text `recruitment_condition` writer with recorded typed gate identity/state.

**Current evidence.** A session can start with no character. The public character-create body allows
`is_companion=true`, so clients can bypass recruitment and the four-companion cap. It also permits
multiple non-companion PCs. Skill checks and several services silently select the first
non-companion row as “active,” with database order deciding ties. `get_party_for_session` includes
dead and abandoned rows; `Campaign.member_ids` is exposed but never drives membership; and the
`abandoned` character status is never written because dismissal converts/deletes companions.
Recruitment currently allows every `recurring` NPC, including dynamically promoted NPCs, to derive a
permanent companion sheet from its NPC fields; only an optional `companion_sheet` distinguishes a
handcrafted candidate.

**Unknown.** Is v1 exactly one active PC plus recruited companions, or is a player-owned party
supported? When may the active PC be deleted or replaced? What remains on the roster after death or
dismissal?

**Resolve by.** Implement the decision above and cover no-PC start, duplicate-PC create,
recruitment, PC death, companion dismissal, and reload/read-model behavior with integration tests.

### G32 — Act progress and campaign conclusion have two conflicting writers (**FIX + DECIDE**)

**Decision (2026-07-13).** Each Act declares explicit required `core_event_keys`. Scene Director
may propose resolution of a named authored key, but one server-owned transition validates that the
key belongs to the active Act, records it idempotently, and advances only when every required key
for that Act is resolved. Narration and post-turn code never write `current_act_index` directly.
Resolving the final Act atomically marks the Campaign `completed`.

**Implementation consequence.** Persist resolved core-event identity, not just a changed numeric
index. Route all normal-play and administrative progression through the same transition, reject or
ignore duplicate/unknown/out-of-act proposals deterministically, and retain an auditable event for
the final status change. The Campaign Epilogue is the final completed Turn's authoritative
narration, not an untracked best-effort generation job; persist its Turn identity and
`completed_at` with the conclusion.

**Finale consequence.** The final screen renders that narration plus stable campaign facts: Player
Character, companions, final Act, in-world day, and resolved milestones. An optional editorial
post-campaign retrospective may be designed later as a distinct feature, but completion never waits
for or depends on it.

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

**Resolve by.** Implement the transition and integration-test valid, duplicate, unknown, and
out-of-act proposals; multi-event acts; final-act completion; and every post-completion mutation
guard. Either implement `combat_ended` through a similarly authoritative route or remove it from
the Scene Director contract.

### G33 — Done

### G39 — NPC presence has competing sources and the shipped cast is often nowhere (**FIX + DECIDE**)

**Decision (2026-07-13).** An NPC's `location_id` is its persistent current whereabouts. A Scene
has an explicit present cast: the actors currently available for interaction in that dramatic
situation. When a Scene opens, its cast is built from the authored scene and eligible NPCs at that
Location. Dialogue, recruitment, combat targeting, and scene narration use the present cast, never
a campaign-wide fuzzy NPC search.

**Consistency consequence.** Moving, departing, recruiting, or dismissing an NPC must pass through
one application service that keeps persistent whereabouts and the open Scene cast coherent. A
present NPC's whereabouts must agree with the Scene's Location. Seeded canonical NPCs receive an
authored starting Location or an explicit offstage state; “no location by accident” is invalid.

**Implementation consequence.** Make cast construction and interaction authorization explicit in
the Scene service. Ensure recruitment converts/removes the NPC according to the Party decision in
G17 and prevent an offstage or merely name-matched NPC from being selectable.

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

**Resolve by.** Implement the decision and integration-test scene opening, authored/existing cast,
offstage NPC rejection, departure, recruitment, dismissal, and a subsequent scene at the same
Location.

### G45 — Scene discoveries use prose while secrets and hooks expect opaque keys (**FIX + DECIDE**)

**Decision (2026-07-13).** Every authored discovery declares a stable key, player-facing text, and
optional Campaign Journal topic links. A successful check records that key once in Scene/Campaign
state and appends the player-facing Journal entry. Secrets and authored hooks depend only on those
recorded keys; prose is the presentation of a discovery, never its identity.

**Authority consequence.** Scene Director may propose a declared discovery key, but the server
validates that it exists in the authored Scene before recording it. Dynamically generated
discoveries may be journaled, but cannot accidentally unlock authored secrets, transitions, or
hooks. An authored hook must declare its typed outcome and be applied by the same server-owned
transition/state service, not by unstructured narration.

**Implementation consequence.** Extend authored reveal data with stable identities, validate
references at content seed/validation time, and use one idempotent discovery writer for checks,
Scene Director proposals, and any direct authored trigger. Test the shipped false-drawer path,
duplicate discovery, invalid proposed key, dynamic discovery isolation, secret unlock, and hook
application.

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

**Resolve by.** Implement the decision and seed-time reference validation. Remove or explicitly
defer every authored hook whose typed outcome is not supported by the transition service.

### G46 — Lore scoping stores selectors that current reads ignore (**FIX + DECIDE**)

**Decision (2026-07-13).** A Campaign Template explicitly selects the World Lore keys that are
always available to its internal narration context. These selectors are validated at publish/seed
time and are the only always-on lore for that Template. `world_bible_namespace` is internal
authoring metadata, not a runtime player/API selector.

**Visibility consequence.** This scope does not disclose lore to the player. Player Codex visibility
continues to require the explicit Campaign Journal discovery rule in G34.

**Implementation consequence.** Resolve selected keys against the World when a template is
published/seeded, reject missing or cross-world entries, and have narration context read that
resolved set rather than every campaign-scoped lore row. Remove `world_bible_namespace` from
player-facing transports unless a distinct internal authoring workflow uses it.

**Current evidence.** A CampaignTemplate stores `always_on_lore_keys` so a scenario can opt additional
world chunks into every prompt, but no runtime reader uses the field; narrative context includes only
chunks whose world-level `always_on` boolean is true. Separately, Campaign creates a
`world_bible_namespace` and every WBE stores it, but reads, uniqueness, and isolation all use
`campaign_id`; no query filters by namespace. Both unused selectors are exposed or propagated as if
they own behavior.

**Unknown.** Is always-on selection world-global or scenario-specific? Is namespace future lineage/
cross-campaign memory, or redundant with Campaign id?

**Resolve by.** Implement the selector validation/read path and test a template with no selected
lore, selected lore, missing keys, and a different World's key. Keep player-facing Campaign Journal
reads separate from narrator World Lore reads.

### G47 — Published content is half snapshot and half live, with no version policy (**DECIDE**)

**Decision (2026-07-13).** Creating a Campaign pins one immutable Published Content Version. The
snapshot inputs include the Template, selected World Lore, Acts, authored Scenes, Locations, cast,
calendar, and every rules-relevant authored datum. Later author edits/reseeds create a new published
version for new Campaigns only; they never mutate existing playthroughs.

**Scope consequence.** A Campaign retains source-version provenance for debugging and display, but
gameplay reads its pinned content. “Upgrade this Campaign to a newer scenario version” is explicitly
unsupported in v1 rather than a hidden reseed/migration side effect. Existing campaign-owned state
may still evolve through play under the normal engine rules.

**Implementation consequence.** Publish/version content immutably, make campaign creation bind and
copy/reference that version consistently, and prevent seed/upsert routines from changing published
rows in place. Define publication validation before a version is selectable, and remove ghost
content through authoring-version lifecycle rather than mutating live campaign data.

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

**Resolve by.** Implement the pinned version boundary and integration-test that a later publish or
reseed cannot rewrite an existing Campaign while a newly created Campaign receives the new version.

## Character creation and progression

### G4 — Gallery and uploaded portraits cannot be persisted (**ALIGN**)

**Decision (2026-07-13).** Phase A supports two real, optional portrait sources in character
creation and later Player Character editing: a global curated Portrait Gallery selected by stable
asset key, and a private user upload. A Character stores one typed Portrait Selection—either a
gallery key or an owned upload asset with crop/reposition metadata—or deliberately has no portrait
and renders the product's unpictured fallback. It never stores or trusts an arbitrary remote URL.

**Asset and ownership consequence.** Gallery assets are application-owned and globally selectable;
they are referenced, not copied. An uploaded original belongs to the uploading user, is accepted
only after file type, byte size, and image-dimension validation, and produces a safe rendered asset
reference plus the selected crop. A Character may select only its owner's upload. Replacing or
clearing a Portrait Selection changes only that Character's reference; cleanup of unreferenced upload
assets must be safe and must never remove an asset still selected elsewhere by its owner.

**Implementation consequence.** Replace the loose `portrait_url` intended contract with typed
gallery-manifest, upload, portrait-read, and selection commands. The Player Projection exposes only
the safe display rendition and presentation metadata needed to render it. Both create and patch
flows use the same selection validation; a local-only browser preview is not a successful save.
Document error states for rejected files, unavailable asset, unauthorized asset, replacement, clear,
and skipped portrait.

**Phase boundary.** AI portrait generation is not a Phase-A fallback or disabled hidden endpoint. It
remains separately deferred under G14/Phase B, where paid-plan eligibility, generation inputs,
ownership, safety, and storage will receive their own product contract.

**Current evidence.** `Character.portrait_url` is returned, but neither `CharacterCreate` nor
`CharacterPatch` can set it. No gallery manifest, upload/storage service, file validation, crop
metadata, or authorized portrait mutation exists. Ember presents gallery selection, local upload,
crop/reposition, skip, and a separate disabled generation affordance.

**Verification.** Contract-test gallery selection, valid/invalid upload, crop update, asset
ownership rejection, replacement, clear, skipped portrait, and a player-safe read after reconnect.
Verify that authoring a new gallery asset or replacing a user's source file cannot silently change an
existing Character's chosen display result.

### G52 — NPC conversation portraits have no authored or generated visual lifecycle (**DECIDE**)

**Product opportunity.** A focused portrait of the NPC currently speaking with or clearly facing the
Party can make non-combat Play feel materially more present than prose alone. It belongs in the Play
scene as a restrained conversation treatment—not as a permanent card for every person in the cast.
Combat remains the Tactical Sketch/turn-queue mode; it need not carry a large conversation portrait.

**Decision (2026-07-13).** Use an authored-first, lazy-generated-fallback approach. Important
authored NPCs and Companions receive curated, version-pinned portrait selections as content. A
background/generated NPC may receive one generated portrait only at its first meaningful conversation
reveal. The request is asynchronous and cached to that campaign NPC; it never blocks a Turn. Until
ready, Play shows a deliberate placeholder rather than a broken or repeatedly changing image. The
non-combat Play view features only the current conversational subject (speaker or directly addressed
NPC), not a grid of the whole cast. Combat drops this large portrait treatment in favor of Tactical
Sketch, turn queue, conditions, and health bands.

**Generation boundary.** The image request uses a server-built, player-safe Visual Brief from
observable identity/appearance and a versioned art direction. It may not contain private profile
facts, secrets, raw agent context, or player input outside the visible situation. The persisted
result records the source/profile revision, job status/error, provider/model/style version, and asset
identity; it is not regenerated on every turn. Provider choice, cost budget, rate limits, retries,
and safety handling remain explicit implementation decisions, not an unbounded call embedded in the
turn loop.

**Current evidence.** `NPC` already has nullable `portrait_url`, and authored NPC YAML accepts it,
but every shipped NPC value is `null`. No NPC asset manifest, selection/read projection, upload,
generation provider, job, image prompt contract, cache, cost/rate policy, or Player Projection
exists. G4 defines only Player Character gallery/upload portraits; G14 defers player-requested AI
portrait generation to Phase B.

**Decision needed.** Decide whether v1 uses authored portraits only, or also a generated fallback
for background/generated NPCs; when generation is triggered; and what failure/cost boundary keeps an
image request from delaying a turn. A likely staged direction is authored, version-pinned portraits
for important roster NPCs first, then one asynchronous generated portrait at a background NPC's first
conversation reveal, cached to that campaign NPC and never regenerated per turn. The UI would show a
deliberate placeholder until it is ready and switch only the featured conversational subject, not a
crowd of portraits.

**Safety and consistency questions.** A generated image must use a server-built, player-safe Visual
Brief derived only from observable identity/appearance and a versioned art direction—never private
goals, secrets, or raw agent prompt context. It must persist the source/profile revision, generation
status/error, provider/model/style version, and resulting asset so a Campaign remains visually
consistent. Provider choice (for example a hosted image model), cost budget/rate limits, safety
handling, retry policy, and ownership/storage require an explicit decision; no live turn may block on
an external generation call.

**Resolve by.** Define an NPC Portrait Selection compatible with G4's asset model, an authored
content-publish validation path, a player-safe conversation-subject projection, and—if generation is
adopted—a non-blocking queued job with persistent deduplication/failure states. Prototype the
non-combat Play treatment in Ember only after the delivery contract is selected. Do not expose a
portrait before the NPC itself is visibly revealed.

### G5 — Player identity is loose JSON and the Weave plan uses drifting names (**DECIDE**)

**Decision (2026-07-13).** A Player Character has a typed, player-owned **Player Identity** with
optional editable `physical`, `personality`, structured `voice`, `backstory`, and structured `goals`
fields. `Character.name` remains the one canonical name and is not duplicated inside identity. Each
identity field may be independently set, replaced, or cleared, so a player may start with a minimal
concept and deepen it over play without replacing a whole JSON document.

**Audience boundary.** Player Identity is not the NPC/Companion deep-profile container. V1 does not
give a PC the NPC-only `private_facts`, prejudices, or relationship-state fields: a player-secret or
selective-disclosure feature needs explicit audience and reveal semantics before agents may reason
over it. The player can still express ordinary history and motivation in the editable fields above.

**Weave decision.** Weave accepts a freeform character concept and returns one typed, editable
`PlayerIdentityDraft` in the same field vocabulary. It never writes a Character, changes mechanics,
or chooses race, class, abilities, skills, spells, equipment, portrait, or campaign state. Ember
shows that draft for review; the player may accept, edit, partially apply, or discard it, and a
normal Player Identity patch is the only persistence writer.

**Naming and implementation consequence.** `bio` and `voice_traits` are obsolete names and are
removed outright; there is no old persisted data requiring a compatibility migration. Add explicit
typed create/patch/read contracts with field-clear semantics, update the character/profile formatter
and Player Projection to use them, and keep NPC/Companion `NarrativeProfile` ownership separate even
where the voice/goals nested shapes are shared. Do not accept unrestricted JSONB from a player route.

**Current evidence.** Manual `narrative_profile` editing exists as an unrestricted dictionary. The
domain vocabulary uses fields such as `physical`, `backstory`, `personality`, structured `voice`,
and `goals`; older frontend planning mentions separate `bio` and `voice_traits`. Ember correctly
makes manual editing primary and Weave an optional draft, but there is no typed player request/
response schema or Weave endpoint.

**Verification.** Contract-test minimal identity, each field replacement/clear, malformed nested
voice/goals rejection, player-safe reads, and rejected NPC-only fields. Test that Weave returns an
editable draft with no database mutation, that a partial acceptance persists only the selected
fields, and that neither a Weave request nor an identity patch changes mechanical character state.

### G7 — Descriptive character sheets lack a complete rules lookup contract (**ALIGN**)

**Decision (2026-07-13).** Keep the compact Character read model for current state and mutations,
but add a separate player-safe **Character Sheet Projection** for the sheet UI. It returns only
character-specific, server-derived facts in explanatory rows: ability scores/modifiers and their
relevant uses; skill and save totals with proficiency/source; AC, speed, initiative, and passive
scores with their derivation; health/resources/conditions; equipped inventory; legal spell state;
and feature/action cards. The client lays out those rows; it does not calculate bonuses, combine raw
SRD documents, or invent explanatory text.

**Rule-detail split.** Each sheet card has a stable rule key, source, compact player-facing
explanation, and truthful current availability. A separate normalized **Rule Detail** read supplies
full description and reference material on demand. The client may cache that immutable detail only
by its Published Content Version and key. Do not pack the full rules catalog into every Character
response, and do not leave the client to crawl inconsistent raw catalog documents to explain a
sheet.

**Truthfulness boundary.** A feature, spell, item, or action whose Mechanical Effect Contract is not
implemented (G29) cannot be presented as a usable command. It may appear as a clearly labelled
reference/deferred capability only if that distinction helps the player understand their sheet; it
must not look actionable. Conditions and temporary effects likewise use only the player-visible
information permitted by G6.

**Implementation consequence.** Inventory every sheet row, map it to a canonical typed rule record
or a server-derived computation, and fill only narrowly missing normalized reads. Normalize the
created, leveled, and authored Character feature/resource/inventory shapes at their existing
boundaries (G40), then build the Projection from that one canonical sheet. Ember should consume the
Projection and stable Rule Detail keys, not undocumented JSONB shapes or display-name matching.

**Current evidence.** Character responses mostly contain rule names/indices and current values.
Several SRD catalogs are exposed, but there is no audited lookup path for every skill, save, feature,
feat, condition, spell, weapon, armor, resource, and proficiency Ember explains. JSONB feature shapes
also vary between created, leveled, and authored characters.

**Verification.** Contract-test a martial and each caster spell-state family for Projection accuracy,
including an equipped armor/shield, a condition, an expended resource, and a content item with no
implemented action. Verify player-safe omissions, a stable Rule Detail lookup, and that a client can
render every shipped sheet row without raw-catalog joins or locally calculated bonuses.

### G54 — New players need a Rules Compendium, but Codex and raw SRD routes are the wrong product (**AUDIT GATE**)

**Product opportunity.** Add a read-only **Rules Compendium** tab beside Codex, Sheets, and Map: a
stylized book-like reference for the game rules—fundamentals, abilities/skills, conditions,
equipment/weapons/armor, spells, classes/subclasses, races/subraces, backgrounds, feats, and other
supported rules. It gives non-D&D-native players one searchable, filterable place to learn without
turning the Character Sheet into an endless help manual. Sheet cards may retain a compact one-line
explanation and link directly to the relevant Compendium entry.

**Scope direction (2026-07-13).** The Rules Compendium is a global library available to every player,
not a collection limited to the Player Character's class, spells, or inventory. Character Sheet links
are merely contextual shortcuts into the same global entry; they do not filter or personalize the
library's corpus. It is reachable from both the authenticated Campaign Browser hub and a Campaign's
in-play navigation, backed by the same version-pinned catalog and deep links. It is not public
Landing content and has no Campaign-specific copy.

**Decision (2026-07-13): initial global scope.** The first Compendium shelves are Getting Started
(dice, checks, advantage/disadvantage, proficiency, actions); Abilities & Skills (ability scores,
saves, every skill, and passive checks); Combat (turns, action economy, zone movement, reactions,
damage, concentration, death modes, and conditions); Magic (spellcasting basics and the full bundled
spell catalog); Equipment (weapons, armor, shields, adventuring gear, and tools); Character Options
(all bundled classes/subclasses, races/subraces, backgrounds, and feats); and Rest & Travel (short
rest, long rest, Camp, time, and supported travel rules). Each entry clearly distinguishes the
licensed standard-rule reference from how Cairn implements or deliberately limits it.

**Deferred scope.** Monsters, magic items, and exotic/unsupported systems are a second pass. They
add substantial volume, can create spoiler expectations, and require their own truthful support and
disclosure policy before joining the global library.

**Compendium support-status decision (2026-07-13).** The Compendium may contain licensed global
reference material that Cairn does not yet execute, because it is a learning library rather than only
a command menu. Every entry and search result therefore carries one clear player-facing status:
**Play-ready in Cairn**, **supported through Creative Adjudication**, or **Reference only / not yet
executable**. Reference-only material may explain a rule but never appears as an actionable command
on a Character Sheet or in combat. Status comes from the version-pinned Rules Profile/engine-fit
audit, not client inference or a writer's prose. This preserves useful D&D context for newcomers
without misleading experienced players about engine support.

**Compendium browse decision (2026-07-13).** V1 provides global full-text search, shelf/category
navigation, filters for support status and Rules Profile/source package, and stable deep links from
Character Sheet cards. It has no Character-specific collection, personalized recommendation,
progress/read state, or advanced faceted catalog in the first release. The book-like presentation is
the UI treatment over this one global index, not a separate content system.

**Compendium authorship decision (2026-07-13).** Player-facing licensed reference text, Cairn
plain-language explanations, and “how Cairn implements this” notes are reviewed, versioned published
content tied to a source record, Rules Profile version, and support status. They are not generated at
read time or personalized per player. An LLM may assist an internal authoring draft, but a reviewer
must verify source accuracy, mechanical claim, status, tone, and attribution before publication.
Corrections create a new published content/profile version; they do not silently rewrite an existing
Campaign's reference. This makes deep links stable and prevents different players from receiving
contradictory on-demand rule explanations.

**Corpus audit gate (2026-07-13).** Do not select a Compendium or gameplay rules baseline yet. The
current repository is a mechanically dangerous mixture: the bulk catalog was fetched from
dnd5eapi.co's /api/2014 endpoints, while the later supplement script replaced feats.json and
traits.json with /api/2024 data because that endpoint was more complete for those records.
feats_phb.json also supplies hand-curated 2014-style feats, and the catalog merges it with the
2024 feat file. Character creation, class levels, spells, equipment, monsters, and much of the
executor still operate from the 2014-shaped records. A player can therefore read or select a 2024
trait/feat alongside a 2014 character/rules engine with no declared compatibility policy. The
upstream-fetch scripts preserve neither a source commit/checksum nor the precise published SRD
edition. “SRD” is not enough provenance for a shipped rules product.

**Source-audit finding (2026-07-13).** The local fetch script explicitly says it replaced only feats
and traits with `/api/2024` because that endpoint had more records, while intentionally leaving
spells, monsters, and equipment on 2014 data. Local source URLs confirm those two 2024 files and
twenty-two 2014 catalog files. The official SRD publisher distinguishes SRD 5.1 / 2014 5e from SRD
5.2.1 / 2024 5.5e. It permits using material from both under CC-BY 4.0, but explicitly makes the
publisher responsible for compatibility; permission to combine sources is not evidence that the
combined rules engine is coherent. Preserve the official source URL, document version, retrieval
date, and attribution text in the future source manifest; this register is not legal advice.

**Cairn Rules Profile decision (2026-07-13).** V1 is not required to be a pure 2014 or pure 2024
game. It uses a version-pinned **Cairn Rules Profile**: a coherent 2014 SRD 5.1 mechanical chassis
plus deliberately curated 2024 SRD additions where they improve the intended game or fill a real
catalog gap (for example, selected feats, traits, backgrounds, or other character options). The
reason for an addition may include delivering familiar modern/BG3-like play options; that product
reason does not waive compatibility work. Existing 2024 records are staging evidence, not
automatically selectable content and not a blanket quarantine.

Each selected addition must declare its exact source/version, stable key, whether it supplements or
replaces a 2014 rule, dependencies and terminology, affected creation/progression/rest/combat paths,
executable support classification, player-facing source/implementation note, and regression fixtures.
An addition enters the selectable catalog and Compendium only after that entry passes the profile
audit. The product must describe the resulting profile honestly as Cairn's declared 2014-core rules
with named curated additions, never as unqualified “2014 rules” or “2024 rules.” Public naming,
attribution, and marketing language remain subject to the source/legal review.

**Package-curation decision (2026-07-13).** Curate 2024 additions as rules-aware packages, never
as isolated JSON records. A package contains a coherent player-facing option family and every
required dependency, terminology change, builder/progression consequence, executor support,
Compendium entry, and acceptance fixture. A newer Background therefore brings all of its required
creation grants and linked option behavior; it is not merely an extra card in a selector. The first
audit candidate is a **Character Options** package covering the motivating additions—Backgrounds,
Feats, and Traits—followed by separately audited Species, Spells, Equipment, and combat-rule
packages. A package may be rejected, narrowed, or deferred as a whole when its dependencies are not
ready. This avoids attractive selectable content whose mechanical consequences are silently missing.

Before the next rules or Compendium slice, perform a dedicated **Rules Corpus Audit** with three
separate outcomes:

1. **Publication/provenance.** Make an inventory for every imported and hand-authored rule record:
   its exact official source document and version, upstream repository/API revision and retrieval
   date where applicable, checksum, license, required attribution, and whether Cairn is reproducing,
   adapting, or only naming it. Verify the result against the official published SRD/license rather
   than treating an unaudited third-party API as the legal source. Produce the required player-facing
   attribution/notice and obtain appropriate legal review before public release.
2. **Rules profile and player expectation.** Compare the 2014 SRD 5.1 chassis and each proposed
   2024 SRD 5.2.x addition using actual character creation, class progression, species/race, feats,
   spells, conditions, equipment, action economy, rests, monsters, and terminology. Publish one
   versioned Cairn Rules Profile for v1. Every divergence must be intentional, version-pinned,
   player-visible, and supported; it cannot arise from whichever upstream endpoint happened to be
   available.
3. **Engine fit.** For every rule exposed as playable, classify it as executable and tested,
   supported through bounded Creative Adjudication (G49), reference-only, or unavailable. Reconcile
   the chosen corpus against Character creation (G19), Spell State (G9), combat/action execution
   (G29/G30), rests, feats, conditions, and Player Projection. This is the test of whether a
   knowledgeable D&D player will receive the rule set we say Cairn runs—not merely whether a JSON
   record can render.

The audit must publish a versioned source manifest, a rules-delta matrix, an explicit product
statement such as “Cairn runs [chosen rules baseline] with these declared differences,” and
representative character/combat acceptance fixtures. It must replace or quarantine incompatible
records before the Compendium advertises them. Until then, the global Rules Compendium is not
publishable, its proposed full initial shelves are a target rather than a release claim, and new
mechanics must not add further unaudited rules data.

**Boundary.** The Compendium is global/version-pinned reference material, not the Campaign Journal:
Codex continues to contain only facts the player earned in that Campaign. It does not reveal
campaign secrets, enemy stat blocks, or unpublished content. Its entries must distinguish exact
rules text from clearly labelled Cairn-authored plain-language explanations; it must not scrape,
summarize, or serve arbitrary third-party web pages at runtime. The current bundled SRD corpus and
any additional content need a verified license/source and required attribution before publication.

**Current evidence.** Cairn bundles a validated SRD catalog and exposes several raw list/detail
routes, but no unified rule taxonomy, normalized entry contract, full individual equipment/feature
read, version-pinned search index, or Compendium projection. G7's Rule Detail contract provides the
character-sheet seam but is not a browse/search product. Archived Codex mockups are campaign
discovery-focused and therefore must not absorb general rules reference.

**Audit outcome required before a slice.** The Rules Corpus Audit proposes the initial compatible
packages and their exact contents, then verifies their category placement, support status,
attribution, and implementation boundary against the decisions above. It may narrow or defer a
package; it may not silently expand the Rules Profile. No further product interview is required
unless the evidence exposes a material incompatibility or a new player-facing choice.

**Resolve by.** Build one version-pinned Rule Compendium read/search service atop normalized Rule
Detail records, with deterministic category/filter/full-text search and stable deep links. Reuse it
from the Sheet Projection. Add content-source metadata/attribution and tests that reject unlicensed
or unversioned entries; do not make live web search a gameplay or reference dependency.

### G8 — Alignment is a closed UI choice but an unvalidated free string (**ALIGN**)

**Decision (2026-07-13).** Alignment is one canonical, server-validated value from the nine classic
positions, stored as a stable key plus player-facing display label and concise axis explanation. It
is a player-authored roleplay orientation, not a mechanical restriction, action whitelist, or
instruction for an agent to override the player's creative choices. Ember's compass is a faithful
selection and explanation surface, never the source of truth.

**Change policy.** Alignment is chosen at character creation. It may later change only through an
explicit Player Character edit while the Session is idle; no agent, narrator, or inferred behavior
silently changes it. A Premade begins with its authored alignment, but its player may make the same
explicit later change as their characterization develops. The change is ordinary Character state,
not an Act event, XP reward, or automated moral judgment.

**Implementation consequence.** Publish one normalized alignment catalog/read and validate the
stable key on create and allowed patch. The Character Sheet Projection receives the label and axis
explanation from that server-owned catalog. Remove free-text alignment writes and any duplicated
hard-coded client list; reject unknown values rather than attempting to normalize prose.

**Current evidence.** Alignment data ships in SRD files and Ember uses a defined 3×3 compass, but no
alignment catalog route exists and character creation accepts any string.

**Verification.** Contract-test all nine keys, unknown/free-text rejection, first creation, an
allowed idle edit, a rejected non-idle edit, Premade starting alignment, and sheet-projection labels.

### G9 — Spell state is not valid at character creation (**FIX + DECIDE**)

**Decision (2026-07-13): canonical spell state.** Do not overload one `spells_known` list to mean
every caster's magic. A Character has distinct canonical spell-state categories: `cantrips_known`;
`spells_known` for classes that learn a bounded list; `spellbook_spells` for a Wizard's recorded
spells; `prepared_spells` for a currently prepared subset; and `always_prepared_spells` for
race/subclass/feature grants that consume no preparation capacity. A class uses only the categories
the SRD rules give it. A player-visible “available spells” list is a derived legal catalog from
class, level, grants, and sheet state; it is never a second persisted character list.

**Creation and rest consequence.** Creation collects every legal initial player choice and the
server applies automatic racial, subclass, and feature grants. A known-caster's choices populate
only its known/cantrip categories; a prepared caster selects its legal cantrips and current
preparations according to its rules; a Wizard's initial spell choices enter its spellbook, then it
prepares a legal subset. Long rest may alter only a class's legal preparations; it cannot replace a
known list, erase a spellbook, consume an always-prepared grant, or make an illegal spell available.
The server validates source class, spell level, count, duplicate status, and grant source at every
write.

**Implementation consequence.** Replace the current blind `spell_choices → spells_known` copy with
typed creation and preparation inputs/outputs using this vocabulary. Migrate or normalize existing
rows deliberately, update Player Projections and Ember labels to distinguish known, spellbook,
prepared, and always-prepared states, and make combat execution consume only spells currently legal
to cast. Do not make the client reconstruct spell eligibility from raw catalog records.

**Decision (2026-07-13): level-1 spell flow.** The shipped 2014 SRD tables are the authoritative
source for initial counts. Character creation collects the following explicit choices, rejecting
any spell not on the relevant class list or not castable at the Character's current level:

- Bard: two cantrips and four first-level known spells.
- Cleric: three cantrips and a prepared list of `Wisdom modifier + 1` eligible spells (minimum one).
- Druid: two cantrips and a prepared list of `Wisdom modifier + 1` eligible spells (minimum one).
- Sorcerer: four cantrips and two first-level known spells.
- Warlock: two cantrips and two first-level known spells.
- Wizard: three cantrips, six first-level Wizard spells in the initial spellbook, then a prepared
  subset of that spellbook of `Intelligence modifier + 1` eligible spells (minimum one).
- Paladin and Ranger: no spell choices at level 1; their spellcasting begins at level 2, so Ember
  must not imply a spell-selection step for them.

Level-one race, subrace, subclass, or feature grants are server-applied with a recorded source. They
remain visibly distinct from player picks and do not consume a class choice or preparation capacity.
For example, a Life Cleric receives `bless` and `cure-wounds` as always-prepared level-one domain
spells; a High Elf makes its separate Wizard-cantrip and extra-language choices through the relevant
racial grant. The content-publish boundary must reject any selectable grant whose exact source,
spell list, or choice rule cannot be represented.

**Current evidence.** `spell_choices` is not validated for class, spell level, count, duplicates, or
caster type and is copied wholesale into `spells_known`. Prepared casters start with an empty
`prepared_spells` list. Subrace spells, subclass/domain always-prepared spells, and subclass spell
features are not applied. Ember's cleric example distinguishes cantrips, available spells, selected
preparations, and always-prepared domain spells, but the persisted character cannot round-trip that
meaning.

**Verification.** Contract- and integration-test create → read → first legal combat → long rest for
a known caster, a prepared caster, and a Wizard. Prove illegal class/level choices, duplicate picks,
over-cap preparation, missing required picks, and an attempted change to a permanent known/spellbook
list are rejected; prove an always-prepared grant is visible and castable without reducing capacity.

### G18 — Premades can be stored and listed internally but cannot be selected (**FIX + DECIDE**)

**Decision (2026-07-13).** A Premade is a complete, version-pinned authored level-one Player
Character for its Campaign Template—not a loose starter suggestion. Selecting one atomically creates
a campaign-owned Character clone through the same canonical validation and normalization boundary as
custom creation (G19/G9). It retains an immutable source premade key and Published Content Version
for provenance, but never a live link: later authoring changes cannot alter an existing Campaign's
clone.

**Player choice boundary.** Premade selection fixes mechanics: race, class/subclass, ability
scores, equipment, spells, features, inventory, and all other rules state. Before first play the
player may personalize only non-mechanical presentation/identity—name, portrait, and the typed
narrative profile defined by G5. A player who wants mechanical changes chooses Custom creation;
there is no confusing hybrid flow that silently changes an authored sheet while calling it a premade.
Normal later in-campaign level-up and inventory changes apply to the clone like every other Player
Character.

**Implementation consequence.** Add one template- and published-version-scoped selection command,
not a public raw-sheet import. It validates that the selected premade is published and belongs to the
chosen Template, passes its authored inputs through the canonical builder/normalizer, writes the
campaign Character plus immutable provenance in one transaction, and then accepts the permitted
presentation patch. Replace the current nullable live foreign-key-only provenance with a stable
source key/version snapshot sufficient for player/read-model history. Ember's Premade path must make
the fixed mechanical sheet and permitted personalization clear.

**Current evidence.** Premade rows and a query exist, and `Character.created_from_premade_id` is meant
to distinguish onboarding. No public route exposes selection/cloning, `CharacterCreate` carries no
premade id, and no writer sets `created_from_premade_id`. Reposting a premade sheet through custom
create would misclassify it and trigger custom-character intro behavior.

**Verification.** Contract-test template/version membership rejection, unpublished/missing premade
rejection, atomic clone creation, source-version provenance, permitted presentation edits, rejected
mechanical edits through the premade path, and isolation from later authoring changes. Test that the
resulting Character can enter first play without a second creation flow.

### G19 — Character creation advertises 5e outputs that the builder does not create (**FIX + DECIDE**)

**Decision (2026-07-13).** Cairn's v1 Character Creation Contract is a complete, legal level-1
sheet for every SRD race, subrace, class, subclass-at-level-1, background, and option that the
creation UI actually exposes. This is an extension of the existing canonical character builder,
not a second builder or a promise to implement every possible D&D sourcebook. A later curated
catalog may narrow what the UI offers, but it may never offer a choice whose mechanical benefit is
silently discarded or substituted with an undisclosed default.

**Required result.** The builder must validate dependencies and materialize all selected and
granted level-1 facts in the one Character sheet used everywhere else: race/subrace compatibility
and required choices; class/subclass timing; class/background skill overlap rules; fixed and chosen
starting equipment; starting currency; language and tool grants/choices; background and racial
features; class feature choices such as Fighting Style; proficiencies; and every caster's legal
initial cantrips, known spells, spellbook, preparations, and always-granted spells. A player-facing
choice remains a real explicit selection; the server may derive only a consequence that the rules
already determine. The sheet, inventory/equipment rules, rest preparation, level-up, and Ember
must all describe that same state.

**Scope boundary.** This does not require arbitrary third-party content or a generic rules engine
before the next slice. It requires correctness for the catalog presently made selectable. If a
content record or choice cannot be supported, remove it from both the API's selectable catalog and
Ember until it can be. Do not paper over an unsupported choice with a starter-kit default.

**Implementation consequence.** Evolve `CharacterCreate` into a typed collection of the missing
selection inputs; have the current creation service validate and apply them once; and keep
`Character` as the sole runtime sheet. Reuse the existing SRD catalog, derived-stat helpers,
inventory/AC service, and level-up tables. Do not clone creation logic into premade import,
recruitment, or the client. Premades must enter through the same validation/normalization boundary
or be generated by it.

**Current evidence.** A submitted subrace need not belong to the race and required subraces are not
enforced. A later-level subclass may be chosen at level 1. Background-overlapping class skills are
accepted even though Ember says they will not be wasted. `_build_inventory` reads only fixed class
equipment and ignores `starting_equipment_options`; classes such as Fighter can start empty.
Background equipment, starting gold, background features, language grants/choices, and subclass
features/proficiencies are omitted. Character has no language field at all, and class feature choices
such as a Fighter's fighting style have no creation input/state. Equipment legality also does not
enforce armor proficiency or the documented shield/off-hand constraint.

**Verification.** Contract- and integration-test representative paths including a Fighter whose
equipment is entirely option-based, a race/background with language choices, one known caster, one
prepared caster, and a spellbook caster. For each, prove create → player-safe sheet → first legal
combat/rest/level-up without an omitted grant, impossible selection, or client-side reconstruction.

### G20 — XP and level-up have no trustworthy foreground lifecycle (**FIX + DECIDE**)

**Decision (2026-07-13): advancement source.** V1 uses XP progression. XP is awarded only by
server-owned outcomes: completed eligible encounters and explicit authored/DM grants validated by
the engine. The player cannot call a generic self-award endpoint. Reaching a threshold creates
persistent `level_up_available` eligibility; it does not force an interruption and may be resolved
later under the timing contract above.

**Implementation consequence.** Replace the public self-award route with typed, auditable award
sources that record why XP was granted and cannot duplicate an encounter reward. Derive or persist
the pending eligibility from current XP and level, expose it in the player-safe Character/Session
projection, and let the foreground-state service start the level-up flow only when its timing rules
permit it.

**Decision (2026-07-13): immediate level-up effects.** Confirmation increases both maximum and
current HP by the gained HP amount and adds the new Hit Die as available. Existing resource pools
(including spell slots) preserve their spent amount: a higher maximum expands capacity but never
refills the pool. A genuinely new class-feature pool begins with its normal available uses because
it did not previously exist to be spent. Initiative, position, conditions, and already-spent turn
economy are unchanged, including when this happens in combat.

**Implementation consequence.** Apply Constitution-score increases retroactively to the HP gained
at every prior Character level, then apply the new-level HP calculation. Apply Tough from the
correct new Character level. Model resource changes as retained expenditure plus new maximum/new
pool, not by overwriting current state from a table. Preview must show every immediate delta and
apply exactly those deltas.

**Already decided: timing.** Per G43, a pending level-up remains available until chosen and may be
resolved in combat only through the explicit start-of-own-turn combat level-up suspension. The
remaining decision here is the exact immediate HP/new-resource behavior at confirmation; it must
not override the foreground-lock contract.

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

**Resolve by.** Implement typed awards and pending eligibility, then validate every level-up choice
and prove preview/apply parity. Define immediate HP/resource semantics below before enabling the
combat-level-up path.

### G40 — Authored character/NPC JSON bypasses canonical shape validation (**FIX**)

**Decision (2026-07-13).** Curated authored NPCs, Companions, and Premades may retain full
hand-authored mechanical sheets. They are not forced through Player Character creation, whose
standard-array and player-choice contract does not describe an authored roster. Instead, every
authored import passes through one strict authored-content schema and normalizer into the same
canonical runtime Character/NPC value shapes used after player creation, level-up, and recruitment.
There is no trusted raw JSONB path and no second runtime sheet dialect.

**Import boundary.** Publication/seed validates the complete authored record, rejects unknown or
stale fields, validates all rule references, and normalizes every nested feature, resource, inventory,
spell, currency, and narrative value before persistence. The normalizer may translate a documented
authoring alias only where it has an explicit, tested migration rule; otherwise it fails loudly (for
example, an obsolete `recharge` field cannot silently stand in for required `resets_on`). A published
Companion sheet is therefore already canonical when recruited; gameplay copies/references that
validated data and never interprets arbitrary YAML on the hot path.

**Shared-shape consequence.** Player creation, authored import, leveling, Premade cloning, and
recruitment may have different legal inputs, but they all emit the same typed runtime collections.
Player-facing projections consume those canonical collections, never raw authoring documents or
unbounded `Any` objects. A new field belongs first to the canonical shape and its validation rules,
then to only the authoring/input forms that genuinely need to set it.

**Current evidence.** Seeded premade sheets, NPC profiles, companion sheets, features, resources,
and inventory are stored as raw JSONB. Recruitment copies authored companion JSON directly into a
Character. The shipped Bram sheet, for example, stores `recharge: short_rest` plus an extra `name`
inside a resource, while the current `Resource` contract requires `resets_on`; rest logic therefore
will not reset it. Authored feature and inventory objects also differ from builder/leveling shapes.
API schemas expose many of these collections as `Any`, so drift survives to clients.

**Resolve by.** Define strict typed canonical value models and authored import schemas; route every
authoring/seed/publish path through them before rows are persisted. Remove raw `Any` transports at
runtime/player boundaries, make recruitment consume a validated canonical Companion sheet, and fail
publication with a field path and actionable message for unknown keys, stale aliases, malformed
collections, or missing rule references. Add seeded-content contract coverage for every shipped
authored character plus regression cases for Bram's stale resource key, invalid inventory/features,
and a normal authored Companion → recruitment → Player Projection path. Do not introduce a second
builder merely to make authored sheets pass.

## Player-safe reads, memory, and access

### G6 — Public transports expose private and engine-only state (**FIX**)

**Decision (2026-07-13).** Every player-facing endpoint returns a purpose-built Player Projection.
Persistence models and agent-context payloads are never serialized directly. The player receives a
complete sheet for their PC; a player-operable sheet and public identity for recruited Companions;
and only discovered, scene-present facts for NPCs. The server, never client inference, determines
what is discovered.

**Combat disclosure.** Player combat projections expose only legal visible state: presentation/name,
zone, visible conditions, turn/reaction prompts, and health bands. They do not expose raw stat
blocks, hidden modifiers, private profiles, undiscovered lore, or arbitrary persistence JSON.

**Decision (2026-07-13): detailed v1 visibility policy.** The Party receives full exact mechanics:
sheet, HP/resources/inventory, and all status necessary to operate its members. A visible NPC receives
only its scene-authorized presentation identity/description and facts the player has discovered;
private goals, secrets, relationship internals, unrevealed inventory, and deep profile material stay
private. A recruited Companion exposes its operable mechanics and player-appropriate public identity,
but not `private_facts`, hidden secret, raw approval total/log, or an undiscovered personal goal.

In combat the player sees each observable combatant's presentation/name, zone, turn order and current
turn, observable conditions, and a server-derived health band—not exact HP, AC, modifiers, saves,
private intent, hidden abilities, or a numeric morale value. Official dice and their outcome appear
when relevant to the player, without serializing the enemy sheet merely to explain a result. The DM
may add a specific supported Observation such as “badly hurt,” “watching the exit,” or “unshaken”; it
is a time-stamped Transcript cue, not a permanent numeric meter. Only an explicit Discovery becomes
durable Codex knowledge under G34/G45.

**Implementation consequence.** Create explicit response schemas/read services at every player
boundary, separate from internal/admin/agent data. Apply the same policy to REST, SSE payloads,
Recap, Codex, and cached client state; test representative unlearned NPC, Companion, and combat
responses for forbidden fields as well as expected visible fields.

**Current evidence.** `CharacterResponse` returns complete companion `narrative_profile` and
`companion_meta`, including possible `private_facts`, `secret`, raw approval totals, and numeric
approval-log deltas. NPC list/get returns every seeded NPC with full stats, inventory, spells,
disposition/tier, and private narrative profile whether met or not. `SessionResponse` and
`CombatResponse` return raw `combat_state`; monster exact HP/AC/actions and pending reaction frames
include pre-rolled outcomes, internal plan queues, cursor, settings snapshot, and facts.

**Resolve by.** Implement the decision and contract-test both positive visibility and negative
non-leakage cases so a new JSONB field does not leak by default.

### G34 — Lore storage cannot support the current Codex promise (**FIX + DECIDE**)

**Decision (2026-07-13).** The player-facing Codex is an append-only Campaign Journal of
player-visible discoveries. Each entry records its source Turn/time and topic links (person,
place, thread, or event), and is never edited or deleted in place. A Codex topic page is a read
projection that groups this history; it may show a concise current “known so far” summary derived
from recorded entries, but preserves the timeline.

**Visibility consequence.** World Lore and private campaign memory may inform internal agents, but
they enter the Codex only when a player-visible discovery explicitly records them. Visibility is
written with the entry, not inferred by the frontend from a mutable World Bible row.

**Implementation consequence.** Introduce an append-only journal representation/read service or
replace the current overwrite-only use with one that preserves revisions as entries. Keep internal
memory separate from player-facing journal serialization. Define topic links and an explicit empty
state, then project People, Places, Threads, Events, and day references from entries rather than
fabricating them from arbitrary lore keys.

**Current evidence.** `WorldBibleEntry.revealed_at_turn_id` claims to gate player visibility, but no
writer sets it. `/campaigns/{id}/lore` returns every entry and the response omits the reveal marker.
Entries are one mutable fact per `(campaign, type, key)` and upsert overwrites content. Ember instead
shows only revealed knowledge grouped into people/places/threads, with first-met context, dated
append-only history, open questions, and “nothing deleted.”

**Unknown.** Is Codex a flat view of current canonical facts, an append-only player journal, or an
entity read model synthesized from world bible + scenes + turns? Are WBE entries themselves all
player-visible, making `revealed_at_turn_id` misleading?

**Resolve by.** Implement the append-only player discovery writer and player-safe Codex projection.
Contract-test a hidden internal fact, a discovered fact, a later correction, topic grouping, and a
new Campaign with no discoveries.

### G35 — Day summaries and the exposed clock are not reliable chronology (**FIX + DECIDE**)

**Decision (2026-07-13).** `in_game_hours_elapsed` remains the canonical arithmetic time value.
The server projects it through the World calendar into a player-safe date, day number, and
time-of-day, and records each Turn's in-game start/end. A Day entry is an immutable Campaign Journal
entry finalized once when that in-world day closes, sourced only from events and narration excerpts
within that day.

**Rest consequence.** A Rest advances the same clock and appends an explicit journal/time event;
it is never invisible elapsed time. The client performs no calendar arithmetic and does not create
or deduplicate Day entries.

**Implementation consequence.** Give time-advancing operations one clock service, persist enough
source/boundary identity to make daily finalization idempotent, and expose the calendar projection
through the Codex/Recap/Browser read models. Define the first partial day and current unclosed day
as explicit display states rather than pretending each has a final summary.

**Current evidence.** When one or more days elapse, `maybe_roll_days` gathers every completed DM
response in the Session and writes that same concatenation for each newly crossed day. Turns carry
no in-game timestamp or day boundary, so multiple days can receive identical campaign-to-date text.
Standalone rest time emits no Turn event. The player receives only raw
`in_game_hours_elapsed`; world calendar length and the server's Day/time-of-day label remain
internal.

**Unknown.** Is the calendar an accurate per-day journal, a periodic recap, or decorative elapsed
time? What anchors a turn/rest/travel event to an in-world time, especially when several days pass at
once?

**Resolve by.** Implement and integration-test a no-time turn, rest, one day boundary, multiple day
advance, restart/retry at a boundary, and Calendar/Codex reads for partial and finalized days.

### G36 — Turn history exposes dead fields and no coherent pending-interaction view (**DECIDE**)

**Decision (2026-07-13).** Player reads split into two purpose-built projections. Transcript is the
immutable player-facing record of player input, final narration, visible dice/mechanical outcomes,
and timestamps. Pending Moment is the single live foreground projection from G43: kind, opaque
resume id, player-safe prompt/options, owning Turn/combat context, and allowed actions.

**Boundary consequence.** Internal continuation plans, settings snapshots, raw events, and
checkpoints remain persisted but are never public in either projection. Reconnect asks for the
current Pending Moment, not a historical Turn JSON blob. Once resolved, the outcome appears in the
Transcript and the live projection changes atomically.

**Implementation consequence.** Give every suspension kind one typed pending schema and opaque
resume/resolve path, remove unused public Turn fields or give them a real internal lifecycle, and
make Transcript ordering/idempotency explicit. The UI can restore a focused interruption without
recreating hidden engine continuation.

**Current evidence.** `Turn.dice_rolls` is reserved and never written. `Turn.checkpoint_id` is only
set by `update_turn_response`'s optional argument, but current callers leave it null. Skill and
companion suspensions live in loose `check_data`; reaction suspension instead lives inside raw
`combat_state` and stores its owning turn in an internal frame. `events` and pause settings are loose
engine JSON exposed directly by `TurnResponse`.

**Unknown.** Is turn history an audit/debug record, the player transcript, or both? What single read
tells a reconnecting client which interaction is pending and how to resume it without seeing the
engine continuation?

**Resolve by.** Implement the projections and contract-test fresh/reconnecting/duplicate-resolve
cases for check, companion proposal, reaction, and combat level-up suspensions. Verify forbidden
engine fields are absent from all player responses.

### G44 — Mechanical “events” are persisted but not streamed as SSE (**FIX + DECIDE**)

**Decision (2026-07-13).** Every player-visible mechanical outcome is emitted as a typed SSE event
when it occurs and persisted into the same player Transcript record for reconnect/history. SSE is
live delivery; Transcript is the recovery source. `turn_end` is emitted only after every foreground
event for that Turn has been delivered and persisted.

**Event boundary.** The player protocol has a small versioned vocabulary with player-safe payloads:
damage/health-band change, condition, movement/zone, dice result, resource change, combat lifecycle,
Pending Moment, and derived-state update. No raw engine dictionaries cross this boundary. A client
that reconnects catches up from Transcript/Pending Moment rather than trying to replay an internal
event queue.

**Implementation consequence.** Make the combat/mechanics emitter feed the request's SSE producer
and the Transcript writer from one validated event representation. Define event ordering, stable
event ids, and the response schema before wiring UI animation; test live stream, reconnect, and
persisted recovery for each player-visible event family.

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

**Resolve by.** Implement the shared event representation and contract-test event ordering,
player-safe payloads, persistence, live delivery, and reconnect recovery. Remove any Ember live
animation that does not have a corresponding typed server event.

### G42 — Fire-and-forget epilogues have no ordering or freshness contract (**FIX + DECIDE**)

**Decision (2026-07-13).** `turn_end` is a strict player-visible consistency boundary. Before it is
emitted, the server commits every change that can affect the next action or current visible game
state: Scene/Location/cast, Act progress, combat, Turn Suspension, and player-visible mechanical
state. The next Turn may rely on that state immediately.

**Derived-work boundary.** Only non-authoritative enrichment may run afterward, such as optional
lore indexing or companion reflection. It may not alter gameplay truth. Each job is tied to its
source Turn and versioned; on completion the client receives an explicit derived-state-updated
event or observable version with the affected panel(s). A new Turn never waits for enrichment.

**Implementation consequence.** Move correctness-critical writes into the foreground turn
finalization transaction/sequence and serialize them per Session. Define a small versioned derived
work contract rather than silently mutating reads after `turn_end`; failures are observable without
making the completed Turn invalid.

**Current evidence.** `_narrate` emits `turn_end` and only then independently schedules LoreKeeper,
Scene Director post-pass, companion reflection, and scene summarization. The browser receives no
completion/version event for those derived writes; failures are logged but not reflected in player
state. A fast next turn can begin before the previous turn's scene deltas, act progress, lore, or
approval land, and epilogues from successive turns can complete out of order.

**Unknown.** Which state is guaranteed current at `turn_end`, and which is explicitly eventual? Must
the next turn wait for prior scene/act bookkeeping even if the previous response did not? How should
the frontend know when to invalidate Codex, Party, map, and campaign-summary reads?

**Resolve by.** Implement the boundary and contract-test that a new Turn observes prior
correctness-critical changes; derived jobs cannot overwrite newer state; and the client can detect
completion/failure and refresh only affected reads. Slice 11 is a natural implementation owner if
assigned, but retry logic alone does not answer the product freshness question.

### G43 — Pending moments and live streams do not exclude new mutations (**FIX + DECIDE**)

**Decision (2026-07-13).** A Session has exactly one foreground moment. In `idle`, ordinary play
mutations are allowed. While a Turn is `resolving`, only reads and stream reconnect are allowed.
While it is `suspended`, only that moment's required resolve/reject action and reads are allowed.
In combat, only legal combat/reaction actions and reads are allowed. Terminal campaigns remain
read-only under G33. Rest, loot, equipment, spell preparation, and settings changes require `idle`;
they cannot bypass a pending moment. V1 has no cancellation after a Turn is accepted: reconnect
resumes or discovers the same foreground moment.

**Combat level-up exception.** A PC with a previously earned pending level-up may deliberately
start it during combat at the start of that PC's own turn, before committing an action, and only
when no check, reaction, or other suspension is open. It becomes the sole foreground combat
level-up suspension. Confirmation atomically updates the Character and that combatant's snapshot,
then resumes the same combat moment; initiative, position, conditions, and already-spent
action/bonus-action/reaction remain unchanged. Eligibility is persistent: XP earned hours earlier
may be spent at that later dramatic moment. G20 must still define the immediate HP and new-resource
semantics, rather than leaving them to accidental implementation.

**Implementation consequence.** Model the foreground state on the server, including suspension
kind and owning Turn/combat checkpoint, and enforce the operation matrix at every mutating route.
Do not use disabled client controls as the lock. Make reconnect, duplicate resolve, and the
combat-level-up handoff idempotent.

**Current evidence.** `turns.prepare` does not reject a new turn when an earlier Turn has a pending
skill check or companion proposal, or when `combat_state.pending_reaction` exists. A new combat turn
can therefore bypass or overwrite a suspended reaction; multiple unresolved check turns can coexist.
Settings, rests, equipment, spell preparation, leveling, loot, and character mutations also have no
shared policy for an in-flight SSE turn. G11 separately notes that spell preparation is not a
checkpoint at all.

**Unknown.** Is there exactly one foreground moment per Session? Which side-panel mutations are safe
between turns, during a stream, during combat, and while a checkpoint waits? Is cancellation allowed,
and what does reconnect do with an abandoned moment?

**Resolve by.** Implement and contract-test every state/action combination, including duplicate
submits, reconnect during resolution, all ordinary mutations rejected while suspended, and the
delayed combat level-up path. Expose the state through the player-safe projection from G36; the
focused modal in Ember cannot be the only lock.

### G37 — Done

## Settings and agency

### G21 — Settings overrides can be added but not cleared (**FIX + DECIDE**)

**Decision (2026-07-13).** Remove persistent Campaign Presets and sparse override inheritance from
the product and backend contract. A Campaign owns one complete, typed Campaign Settings value. The
former `narrative` resolved values become the server-owned initial defaults: AI companion control,
silent passive checks, Narrative death mode, fade content boundaries, normal narration, and AI
reactions. There is no hidden source, inherited exception, or semantic difference between a setting
chosen at creation and the same setting changed later.

**Player flow.** Campaign creation displays those real default values and may submit the player's
chosen complete settings before first play. Settings later patches exact named controls directly.
The UI explains each control and its options, including AI/Suggest/Player and death-mode outcomes;
it need not explain a fictional preset source. It offers one explicit **Restore all defaults** action
that replaces every setting with the server defaults. A per-control “restore default” is merely an
ordinary write of that default value, not deletion of an override.

**Implementation consequence.** Replace `StoredCampaignSettings(preset, overrides)`,
`CampaignPreset`, `_PRESETS`, resolve/inherit machinery, preset response fields, and sparse-merge
semantics with one validated full Campaign Settings schema and a narrowly typed partial update
command. Persist the full effective value (or deterministically normalize to it at the persistence
boundary), return that same value from reads, and make reset an explicit replacement. Update all
callers/tests and Ember; no compatibility behavior is needed for old campaign data unless such data
exists when implementation begins. G41 still defines when an already-started Turn sees a changed
setting.

**Current evidence.** Sparse override models reject nulls and `update_settings` deep-merges patches.
Changing a preset retains all prior overrides, `{}` removes nothing, and there is no field-level or
whole-preset reset operation. Once a value becomes custom, the public contract cannot restore
inheritance from a preset.

**Verification.** Contract-test default Campaign creation, creation with changed settings, every
direct patch, Restore all defaults, a subsequent read/reconnect, rejected unknown/nested-invalid
values, and no preset/override fields in public transports. Verify that a settings change obeys the
foreground timing contract in G41 rather than mixing policy within one Turn.

### G41 — The “one settings snapshot per turn” boundary is porous (**FIX + DECIDE**)

**Decision (2026-07-13).** Campaign Settings may change only while the Session is `idle`, as
defined by G43. They cannot change during combat, stream resolution, a pending check/reaction/rest
decision, or any other foreground moment. When a player action is accepted, the server snapshots the
complete direct Campaign Settings value onto its Turn. Every continuation of that action—checks,
companion decisions, reactions, combat resolution, narration, and death handling—uses that one
immutable snapshot exclusively.

**Boundary consequence.** The next accepted eligible action uses the settings then saved on the
Campaign. A standalone idle command, such as beginning a Rest, takes one settings snapshot when it
begins and keeps it until that command resolves. The snapshot is authoritative engine state, not a
player-visible UI object; Player Projections show only the current Campaign Settings and the result
of the already-resolved action. There is no mixed-policy Turn and no promise that a mid-combat toggle
will alter an in-flight outcome.

**Implementation consequence.** Make the complete direct settings schema from G21 the only input to
all turn/combat/rest mechanics, persist it once at the foreground boundary, and pass it through every
nested continuation. Remove live Campaign settings reads from executor, reaction, damage/death, and
agent paths once the snapshot exists. Enforce the idle-only mutation guard server-side before the
settings route writes anything.

**Current evidence.** Turn preparation resolves a settings snapshot and persists it with skill-check
and companion-action pauses; reaction frames also carry a copy. The UI says changes apply from the
next turn. However, combat execution and reaction resumption re-read `reaction_control` from the live
Campaign, and damage re-reads the live death mode. Settings PATCH remains available while a turn or
reaction is pending. A mid-turn edit can therefore change resolution semantics even though narration
or another part of the same continuation uses the captured snapshot.

**Verification.** Integration-test a changed setting before a Turn, a rejected setting change during
every foreground state, and a newly accepted Turn observing that saved value. Exercise pending
checks, Player/Suggest/AI reaction paths, death mode, narration, and a Rest command to prove no
continuation re-reads live Campaign Settings.

### G22 — Companion Dialogue AI/Suggest/Player is not three behavior modes (**FIX + DECIDE**)

**Decision (2026-07-13).** Companion Dialogue controls only who supplies a Companion's spoken
words in a meaningful dialogue moment. It never grants combat, check, equipment, level-up, or other
mechanical authority. The three modes are distinct:

- **AI** — the Companion agent may supply a relevant in-character spoken response.
- **Suggest** — when a meaningful Companion response is needed, the engine opens a Dialogue Pending
  Moment with one in-character draft. The player may Send it unchanged, Edit then send it, or Skip it.
- **Player** — the agent never supplies the Companion's spoken words. The player deliberately selects
  **Speak as [companion]** in the composer and enters that line. If an NPC directly requires that
  specific Companion's answer, the engine opens the same explicit prompt; the player is never
  expected to infer that an ordinary PC input is secretly companion roleplay.

**Moment and narration boundary.** A Suggest/Player Dialogue Pending Moment records its speaker,
context, draft where applicable, allowed Send/Edit/Skip actions, and owning Turn, so reconnect
restores the same choice under G36/G43. It is opened only for a meaningful required response, not
for generic atmospheric chatter. In every mode the narrator may describe a minimal, warranted
observable physical beat, but it may not fabricate a spoken line in Player mode or create a canned
companion reaction on every turn. The dialogue prompt catalog must enforce this boundary.

**Implementation consequence.** Replace the shared current non-AI meta note with typed dialogue
intent/suspension/resume paths and a dedicated composer subject. Persist only the player-approved
line or AI-produced delivered line in the Transcript, never a hidden abandoned draft as if spoken.
Pass the chosen mode through the immutable settings snapshot (G41), constrain Scene Narrator and
Dialogue agents accordingly, and expose speaker/control state through Player Projections.

**Current evidence.** The setting accepts `ai | suggest | player`, but `resolve_dialogue` treats both
non-AI modes identically and returns only a meta note that dialogue is player-controlled. There is no
draft, approval checkpoint, selected speaking subject, companion-text request, or resume route.
Meanwhile every narrator context still includes companions and the SceneNarrator prompt explicitly
tells the model to voice occasional companion lines regardless of the dialogue setting.

**Verification.** Contract-test each mode for a direct NPC-to-Companion question, an explicit
Speak-as request, Send/Edit/Skip, reconnect with a pending draft/manual response, duplicate resolve,
and no automatic spoken Companion line in Player mode. Test that a dialogue result cannot mutate
mechanics and that narration emits neither forbidden speech nor repetitive filler reactions.

### G23 — Companion Checks and Equipment controls are dead; Leveling controls unrelated spells (**FIX + DECIDE**)

**Decision (2026-07-13): Companion Checks.** Remove the `companion.checks` setting entirely. An
active check is initiated by the player and uses the Player Character or an eligible Companion
explicitly selected under G25; Companions do not autonomously begin active checks in v1. Automatic
Perception/Insight remains the separate server-resolved Passive Check system in G24 and is controlled
only by its disclosure policy. This removes a dead toggle rather than inventing unsolicited
companion actions.

**Decision (2026-07-13): Companion Equipment.** Remove the `companion.equipment` setting entirely.
The player directly manages equipped legal items for every active Party Companion while the Session
is idle. G48's Party Transfer moves an item to that Character first where necessary; the canonical
equipment service validates proficiency, slots, and other legality. Companions never silently
optimize or change their own loadout in v1. The current “AI” value is removed because it only locks
the player without providing real management.

**Decision (2026-07-13): Companion Advancement.** Retain a separate **Companion Advancement**
control with values Player and Auto. Player opens the same legal level-up choice surface for that
Companion at an idle boundary. Auto resolves every pending companion level-up only at an eligible
idle boundary using that Companion Definition's version-pinned authored advancement priorities; it
is deterministic, legal, and never an LLM guess or generic invisible optimizer. A Companion never
uses the Player Character's special start-of-own-combat-turn level-up exception.

**Decision (2026-07-13): Companion Spell Preparation.** Add a separate **Companion Spell
Preparation** control with values Player and Auto. Player preparation is an explicit choice in the
Camp Scene before long rest settlement; Auto selects a legal list during that same long-rest flow
from the Companion Definition's authored preparation priorities. It is independent of advancement:
the player may choose one manually and the other automatically. Both controls use the word **Auto**,
not AI, because no conversational agent is deciding a build.

**Implementation consequence.** Remove the old `companion.leveling` coupling and replace it with the
two direct settings in G21's full Campaign Settings schema. Extend published Companion Definition
validation to require enough deterministic legal priorities for every supported choice point, or
make Auto unavailable for that companion rather than silently falling back. G20 owns XP eligibility
and level-up mechanics; G11 owns the Camp/long-rest sequence.

**Current evidence.** `companion.checks` is persisted and included in Tactical but no production
code reads it; every active skill check selects the first PC. Equipment mode `ai` only rejects player
equip/unequip requests—no agent or deterministic manager equips companion gear—so “AI manages legal
equipment” currently means locked. Companion auto-leveling is real, but the same leveling flag also
decides whether long-rest spell preparation is automatic, a separate responsibility. Equipment
legality itself omits proficiency and off-hand/shield rules.

**Verification.** Contract-test the absence of Companion Checks/Equipment settings, explicit
player-selected companion active checks and legal equipment changes, Player and Auto companion
advancement at idle, and Player and Auto preparation in Camp. Prove an Auto plan is legal,
version-pinned, deterministic, and unavailable rather than guessed when incomplete; prove neither
automatic path interrupts combat or crosses the other control's boundary.

### G24 — Passive Perception/Insight settings are narration hints, not checks (**ALIGN + DECIDE**)

**Decision (2026-07-13).** Passive Perception and Insight are always real, deterministic server
mechanics at their declared triggers; the setting controls disclosure, not eligibility or whether the
engine runs them. Every eligible present Party member uses their derived passive score. `silent`
records the result and applies objective consequences (including avoiding surprise) with no immediate
field note. `surfaced` emits a player-safe Observation when it matters. `on_demand` records one latent
result and reveals that same result if the player asks for a general read while it remains relevant;
it never rerolls, fabricates a retrospective result, or reveals expired information. A mechanical
consequence remains visible where play necessarily exposes it—for example, an actor who is not
surprised at combat start.

**Current evidence.** The settings are passed only into the SceneNarrator prompt. There is no passive
Insight statistic, deterministic passive-check evaluation, recorded result, or visibility event.
Authored hidden details move into `discovered_facts` only after an active rolled check. Ember says
Silent records a result, Surfaced creates a visible field note, and On demand withholds it until
asked—none of those artifacts exist.

**Unknown.** Which authored triggers require a passive check, and how is passive Insight derived and
bound to a target claim/deception?

**Resolve by.** Implement deterministic party passive-check/reveal events with the decided visibility
policy, source/expiry for latent results, and player-safe Transcript/SSE payloads. Define authored
passive Perception/Insight triggers, passive Insight derivation, and target-claim/deception data.
Contract-test all three settings, multiple eligible characters, surprise prevention, duplicate
trigger protection, expiry, and reconnect disclosure.

### G26 — The reaction prompt advertises a serverless 20-second deadline (**FIX + DECIDE**)

**Decision (2026-07-13).** Remove the 20-second timer entirely, including decorative client copy.
V1 reactions have no deadline. `AI` resolves a legal reaction automatically; `suggest` persists a
player prompt with the engine recommendation; `player` persists the same prompt without a
recommendation. Prompts survive refresh/reconnect and wait for an explicit accept, decline, or valid
override. A future time pressure mode requires a separately designed server-owned deadline and is not
implied by this setting.

**Current evidence.** The executor includes `countdown_seconds=20` in the prompt but persists no
deadline and never auto-resolves. A pending reaction remains indefinitely until `/reactions` receives
a decision. A client-only timer can race reconnects, background tabs, or two devices and cannot
authoritatively apply the engine recommendation.

**Resolve by.** Remove countdown fields/copy, implement the three decided agency paths, and test
prompt persistence, reconnect, accept/decline/override, and automatic AI resolution. No expiry test
belongs in v1 because no expiry exists.

## Play mechanics

### G10 — Dying, death saves, combat state, and death modes do not form a state machine (**FIX + DECIDE**)

**Decision (2026-07-13).** All modes share one authoritative conscious/downed/healed/stable/dead
state machine, but diverge at the death-risk branch. A downed actor is unconscious, cannot act, move,
or react, and is removed from ordinary turn authority. Healing restores normal eligibility; stabilizing
stops death-save progression without restoring HP. Natural 1/20, damage at 0 HP, and massive damage
follow ordinary 5e death-save semantics wherever death saves apply.

**Death-mode contract (2026-07-13).** `hardcore` uses the ordinary death-save process; a confirmed
PC death, including instant death, is terminal and transitions the Campaign to `ended_dead`. `narrative`
also uses ordinary death saves, but a confirmed PC death becomes a narratively defeated state: the PC
cannot resume that combat, and the authoritative combat/scene resolution applies one real, recorded
authored or validated recovery consequence after danger ends. It never silently restores the PC to
the same fight. `pacifist` is the most user-friendly mode: at 0 HP the PC is knocked out and cannot
be finished off; no death saves, instant death, or campaign-ending state applies. Once immediate
danger ends the PC recovers to 1 HP. Hitting 0 HP alone never forces capture, separation, stolen
objectives, or another punitive loss of player control; at most the scene moves on or the Party
chooses to retreat. Healing may still restore a knocked-out PC before the encounter resolves.

**Party scope decision (2026-07-13).** Death Mode applies to the PC and recruited Companions, not
only the PC. Pacifist protects every Party member with safe knockout/recovery. Narrative turns a
Companion's confirmed loss into a recorded recovery consequence such as injury, separation, capture,
or temporary departure, never silent deletion. In Hardcore, Companions may die under ordinary rules,
but only the PC's confirmed death ends the Campaign. Hostile NPCs and monsters use ordinary death and
declared non-lethal rules; the player's safety setting does not protect them.

**Narrative Recovery Outcome decision (2026-07-13).** Narrative mode resolves a confirmed PC or
Companion death only after the immediate danger has ended, through one typed **Recovery Outcome**.
An authored encounter/Scene may publish eligible branches such as a capture by surviving captors, a
rescue by a present and able ally, or escape to a known safe place. A branch has a stable key and
declares its permitted location/Scene transition, time advance, affected Party members, inventory
consequence if any, and typed follow-up hook. The server validates every prerequisite against
authoritative combat/Scene state: captors must remain present and capable, a rescuer must actually
exist, a retreat route/destination must be real, and the declared outcome must be legal for the
affected Party.

If no authored Recovery Outcome is eligible, the deterministic fallback is a Party withdrawal to the
most recent safe location or Camp Scene. The conflict remains unresolved. The fallen character
recovers under the decided Narrative mode rules, but cannot rejoin the combat that caused the defeat.
The LLM receives the already selected outcome only to narrate it; it may not invent a captor, rescuer,
new destination, stolen item, separation, or other setback. Narrative may apply an authored recorded
setback, unlike Pacifist, but it never deletes a Character or turns an ungrounded narration into a
durable loss of player control.

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

**Resolve by.** Implement one authoritative state machine shared by damage, healing, initiative,
rests, death saves, campaign status, and player projections. Implement a Recovery Outcome selector
after encounter resolution, with publication validation for every authored branch and its hooks, plus
the safe-withdrawal fallback. Persist the selected key and all resulting state before narration, then
emit player-safe events/Transcript entries. Implement the three decided death-mode branches and the
already planned player-rolled death-save suspension. Update all three Ember surfaces to one exact
death-mode contract. Test every transition, mode, combat end, rest, and player projection—including
captor/rescuer/retreat eligibility, fallback selection, idempotence/reconnect, Companion recovery, and
no punitive Pacifist fallout.

### G11 — Rest mixes missing mechanics, ephemeral prose, and a non-blocking spell-prep request (**FIX + DECIDE**)

**Decision (2026-07-13).** A Rest is an idle-only foreground Turn with typed sub-decisions and one
atomic final commit. A short rest lets the player choose legal hit-die spending; Companions follow
their agency setting. A long rest resolves all required preparation choices before commit, then
updates time, HP/resources, hit dice, conditions, and prepared spells together. Every rest writes a
reconnectable Pending Moment where needed plus Transcript, time, and Campaign Journal events; neither
narration nor elapsed time exists only in a transient stream.

**Rest entry and Camp Scene decision (2026-07-13).** Play exposes one Rest entry action that first
checks the established `safe | risky | hostile` Rest Availability and lets the player choose short or
long. Safe rest is allowed, hostile rest is blocked, and risky rest requires an explicit confirmation
for both rest types. A short rest is immediate: the player spends hit dice one at a time, the server
rolls each through G31 and displays the result, then the Party returns to the same gameplay Scene when
the player finishes. A long-rest request does not apply recovery immediately. It transitions to a
dedicated Camp Scene, where the Party can have camp-specific dialogue and complete preparation; only
an explicit settle-for-the-night action commits the long rest and advances to the subsequent Scene/day.
A long-rest Camp Scene is normal Play state, not a modal laid over the prior Scene. Risky confirmation
does not license an invented ambush: an interruption requires a future typed authored Encounter
Trigger under G38/G50.

**Camp Event decision (2026-07-13).** Camp Scenes support a version-pinned, authored YAML Camp Event
catalog. An event declares a stable key, compact premise/prompt, eligibility (such as safety, act,
party member, relationship band, discoveries, once-only/cooldown), relevance tags, and only typed
outcomes/hooks that the engine supports. The server deterministically filters the full catalog to a
small eligible candidate set; an LLM may select one supplied key that fits the bounded Camp Dossier,
or select none, but may not inspect all events or invent one. The selected key/outcome is persisted
before narration. Events are optional and sparse—quiet companion moments, discoveries, or declared
risky-rest interruptions—not mandatory rest busywork.

**Current evidence.** Both existing rest services already use the current Scene's `safe | risky |
hostile` safety level: safe is allowed, hostile is blocked, and risky returns a confirmation-required
response. The confirmation says the Party “might be ambushed,” but there is no interruption/encounter
mechanism, so accepting it currently performs an ordinary rest. A short rest restores resources and
Warlock slots but always reports zero HP;
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

**Decision (2026-07-13).** Each combat Scene uses a compact authored/published Tactical Sketch:
authoritative zone ids, bidirectional connections, distance, cover category, terrain, typed hazard,
entrances, and stable visual anchors/layout. The player sees a hand-drawn/stylized sketch that
reflects that actual topology; it need not be a grid or exact architectural floor plan. A visual room,
route, obstacle, cover marker, terrain marker, or hazard marker must correspond to published state;
the client must not invent geometry or imply a mechanical effect that the server does not own.

**V1 terrain and hazard floor.** Each zone has one typed terrain category: `clear`, `difficult`, or
`blocked`. `difficult` uses the authoritative movement-cost rule; `blocked` is not a legal movement
destination. Cover is an authored category whose mechanics are derived server-side. V1 ships exactly
two mechanical Hazard Templates:

- `dangerous_ground` triggers when a combatant starts its turn in the zone and resolves the template's
  declared save/damage effect;
- `unstable_ground` triggers when a combatant enters the zone and resolves the template's declared
  save/effect, including the supported prone outcome. When forced movement has a validated combat
  path, it uses the same entry trigger rather than a special LLM judgment.

Each template owns its trigger, save, damage/effect, player-safe icon, and concise factual rules
label. An authored template selection may choose only a published variant whose mechanical values are
validated against the Rules Corpus baseline selected by G54; neither a Scene author nor an LLM writes
ad-hoc bonuses, DCs, or dice expressions. A ZoneSeeder/LLM may draft a candidate Sketch before
publication, but live play never infers authoritative geometry or numeric modifiers from prose.

Smoke or darkness, pits/falling, deep water, elevation, elaborate traps, and any other environment
whose underlying visibility, verticality, movement, condition, or trap contract is not implemented
remain **descriptive Scene details** or bounded G49 Affordance Inventory interactions. The UI must not
style them as automatic zone mechanics. This restriction does not prohibit creative use: a player may
still attempt a supported creative interaction through G49, which validates the action and records a
real consequence rather than turning prose into an unearned automatic effect.

**Current evidence.** Combat zones contain topology, categorical close/far distances, cover category,
numeric cover bonuses, difficult terrain, and free-text hazards. The ZoneSeeder LLM supplies both
cover category and raw bonuses; normalization checks ids but does not derive or cross-check the
numbers. Hazards have no mechanics. Edges are not required to be symmetric. Ember draws irregular
rooms/paths and labels them as a tactical plate even though no coordinates or polygons exist.

**Implementation consequence.** Define and validate the Tactical Sketch schema at content
publication: bidirectional topology, legal terrain/cover/hazard keys, stable anchors for every zone,
valid entrances, and no raw mechanical numbers. Give the Player Projection the matching topology and
only player-safe terrain/cover/hazard labels. Render one actual stylized map vocabulary—interiors,
streets, bridges, forest edges, and so on—from those anchors rather than generic uneven circles.
Implement the two V1 templates through normal combat event resolution, record every trigger/save/effect
in the Transcript, and reject an unavailable template at publication rather than silently degrading it.
Test topology symmetry; invalid anchors/categories; clear/difficult/blocked movement; each hazard's
trigger, success, failure, and repeat behavior; forced entry once supported; player-safe rendering;
and reconnect/replay visibility. Add further hazard families only alongside the engine contracts they
need.

### G25 — Active skill-check authority and roll resolution are internally inconsistent (**FIX + DECIDE**)

**Decision (2026-07-13).** The player selects the acting PC or Companion, defaulting to their PC.
The server validates Party membership, present eligibility, and agency, then computes every modifier
from authoritative sheet state. RulesLawyer/DM may propose whether a check is required, its skill,
DC, and circumstances, but never a modifier or other value the engine can derive.

**Dice contract (superseded 2026-07-13).** Every official die is generated by the server-authoritative
Session RNG from G31; the player initiates the roll and the UI displays/animates that real result. A
normal check generates one d20 and advantage/disadvantage generates two, from which the server selects
high/low and computes the total. This same contract covers checks, attacks, saves, damage, initiative,
and hit dice. Help and Inspiration grant advantage but do not stack. Inspiration cannot be spent if it
would add no die. A physical-dice/trust mode is explicitly deferred rather than hidden as an exception.

**Authored discovery contract.** Resolution records the total and explicit revealed discovery keys,
not one misleading generic `success` boolean. Each declared discovery compares that same total with
its own declared DC; narration receives only the actual revealed keys/text. A generic check result
and a specific hidden discovery may therefore differ without contradicting the engine.

**Implementation consequence.** Make actor identity and normalized roll circumstances part of the
typed Pending Moment, recompute all mechanical inputs in the resolver, draw official dice through G31,
and update the player Transcript/SSE event with the authoritative dice and revealed keys. The client
never supplies modifiers, die values, or an outcome.

**Current evidence.** RulesLawyer receives deterministic character modifiers but returns `modifier`
as LLM output, which the server trusts rather than recomputing. It always acts for the first PC, so
companion checks and multiple-PC intent are impossible. It can return advantage/disadvantage and Help,
but `ResolveRequest` accepts only one ordinary d20 plus an optional second roll specifically for
inspiration; runtime ignores the check's `roll_type` entirely. Spending inspiration without a second
roll is allowed and consumes it for no added chance. Authored hidden details are evaluated again
against their own DC, which RulesLawyer never sees, so `roll_result.success` can be true while the
specific discovery the action targeted remains hidden.

**Unknown.** Who chooses the acting character? Which parts are DM judgment (need, skill, DC,
circumstance) and which must be deterministic (modifier, proficiency, advantage dice)?

**Resolve by.** Implement and test PC/Companion selection, absent/ineligible actor rejection,
straight/advantage/disadvantage/Help/Inspiration combinations, duplicate resource protection,
server-authoritative dice/animation payloads, generic checks, and multiple authored discoveries at
different DCs.

### G27 — Loot transfer proves ownership but not fictional eligibility (**FIX + DECIDE**)

**Decision (2026-07-13).** An authoritative Scene/encounter outcome creates a visible, unclaimed
Loot Bundle linked to its source and current Scene: defeat, surrender, gift, opened container, or a
successful pickpocket check. Only bundle contents can be claimed; claiming consumes a specific entry
idempotently. The UI renders issued bundles, never a source's private inventory.

**Recipient consequence.** Every item or currency award has an explicit Character recipient, which
defaults to the Player Character in the UI. Currency remains individual Character state; v1 has no
shared party treasury. A future merchant/trade interaction may explicitly transfer individual
currency, but neither shared ownership nor invisible pooling is inferred. Pickpocket is a
current-Scene check that creates its own bundle only on success.

**Implementation consequence.** Replace arbitrary `npc_id`/item-name transfer with a bundle-entry
claim authorized by current Scene, foreground state, and eligible Party recipient. Record source,
availability reason, and claim result in the player Transcript. Define containers as valid bundle
sources rather than treating every item owner as lootable.

**Current evidence.** `/loot` will move any named item or currency from any NPC in the campaign to any
campaign character. It does not require the source to be dead, present, discovered, surrendered, or
issued as available loot. The full NPC response leaks inventory. Pickpocket intent resolves a name
campaign-wide without current-presence scoping. The helper `list_dead_in_scene` exists but the public
route does not use it.

**Unknown.** Is loot source-authorized by a pending “spoils available” record, inferred from a dead
current-scene NPC, or allowed after any narrated permission? How are containers and shared party
currency represented?

**Resolve by.** Implement the bundle/claim model and test defeated, surrendered, gifted, container,
pickpocket success/failure, absent source, duplicate claim, item recipient, and currency recipient.

### G48 — Party inventory and currency transfer does not exist (**DECIDE**)

**Decision (2026-07-13).** V1 supports an explicit Party Transfer while the Session is `idle`.
The player may transfer an item quantity or currency amount between the active Player Character and
recruited Companions. Currency remains individual. An item is automatically unequipped before
transfer and both sheets recalculate. Manual transfer is available only when Companion Equipment
control is `Player`; under AI control, the AI manages equipment instead.

**Boundary consequence.** Transfers are atomic, recipient-specific, and player-visible Transcript
events. V1 has no shared bag/shared currency. Merchant buying/selling and barter are separate future
transaction systems, not implicit extensions of Party Transfer.

**Implementation consequence.** Add one idempotent operation with explicit source, recipient, item
quantity or currency amount; validate active Party membership, inventory/balance, foreground state,
and equipment agency. On item transfer, clear equip state and recalculate source/recipient sheets;
emit a typed inventory/currency event.

**Current evidence.** Inventory and currency are Character-owned. The only implemented transfer is
NPC → Character loot; equipment offers equip/unequip only. No route, application service, or
foreground policy moves an item or currency between the Player Character and a recruited Companion.

**Unknown.** May a player redistribute equipment and individual currency among the active Party? If
so, must both characters be present and idle, how does Companion equipment agency affect it, and what
happens to an equipped item? Is trade with a merchant a separate future transaction rather than a
general transfer?

**Resolve by.** Implement and test item stack split, full item transfer, equipped source item,
currency transfer, insufficient balance, non-Party recipient, AI equipment control, non-idle
rejection, duplicate request, and Transcript/SSE recovery.

### G28 — Inspiration can be stored and spent only on one check path, but cannot be earned normally (**FIX + DECIDE**)

**Decision (2026-07-13).** A Character holds at most one Inspiration. During foreground Turn
finalization, DM may propose an award with a player-visible reason; the server validates and records
one idempotent `inspiration_awarded` event. Narration never silently grants it.

**Spend contract.** The player may spend Inspiration before a player-controlled ability check, attack
roll, or saving throw. It grants advantage under G25's dice contract, cannot stack with existing
advantage, and is not spent when it would add no die. Structured combat must use the same typed
pending/roll mechanism before its UI exposes the control.

**Implementation consequence.** Give the foreground finalization service a typed inspiration-award
proposal with reason/source identity and a one-held validation. Thread the shared spend rule into
checks and the future typed combat roll operations; remove narrator tool instructions and any
visible combat affordance until that operation exists.

**Current evidence.** SceneNarrator's prompt tells a streaming text model to call
`grant_inspiration`, but that narrator has no tool loop. The only grant path is the local MCP tool.
Skill-check resumption can spend inspiration, subject to the dice flaw in G25. Structured combat has
no inspiration input or operation, while Ember exposes inspiration as an available character
resource.

**Unknown.** Who awards inspiration in normal play—structured post-pass, narrator output, deterministic
rule, or human control? Can it be spent on combat attacks/saves as well as active checks?

**Resolve by.** Implement and test award, duplicate award, already-held rejection, visible reason,
check spend, combat attack/save spend once supported, no-effect spend rejection, and Transcript/SSE
events.

### G29 — The main combat executor cannot deliver the character-sheet actions it presents (**FIX + DECIDE**)

**Decision (2026-07-13).** G29 is a code-heavy completion of the existing typed combat engine, not
a rewrite and not a reason to narrow Cairn into a tiny action list. Damage/HP/temp HP/range, zones
and movement, saving throws, damage-triggered concentration checks, attack and damage-spell
resolution, and several reactions already exist. Build on those foundations.

**Required v1 action/effect floor.** Complete universal actions and economy (Dash, Dodge, Help,
Disengage, Grapple, Shove, stabilization, item use, and proper bonus actions); make the existing
healing, conditions, and concentration primitives usable by normal casts/features/items; add
condition duration, removal, saves, and mechanical effects where required; and provide typed
operations for exposed class features, feats, and item effects. Every class, subclass, spell, feat,
and item selectable at creation or obtainable in v1 must have a real engine effect. Unsupported
content is not exposed to players; narration never claims that a no-op happened.

**Implementation consequence.** Use reusable typed effect primitives and a published
support/capability matrix, rather than a bespoke narration exception per spell. Preserve the
existing executor/mutation/reaction substrate where it already carries authoritative state. This is
a pre-slice rules-engine program with integration and combat-contract coverage, not frontend polish.

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

**Resolve by.** Inventory every player-exposed content record, publish its supported operation/effect
mapping, then implement and contract-test the required floor against real combats. Retain only
unimplemented catalog content outside player selection/reward surfaces until its mechanics land.

### G30 — Combat plans are typed but not turn-authoritative (**FIX**)

**Decision (2026-07-13).** Every combat operation is validated against the active turn and its
legal economy before it mutates state. Only the current, conscious combatant can spend its action,
bonus action, movement, or voluntarily end its turn. Reactions remain an explicit exception: they
require their own valid trigger/checkpoint and the reacting combatant's unused reaction. A plan does
not choose who advances: the server advances the current combatant after its legal completion or
explicit pass. Combat can end only through an authoritative victory, defeat, retreat, or other
validated resolution condition.

**Implementation consequence.** Put one common turn/actor/economy gate in the executor and make
every typed operation pass through it; operation-specific validation follows that gate. Make
`advance_turn` an actor-free request to pass/complete the current turn rather than planner authority
over a named actor. Preserve the narrow reaction path, but validate its trigger, owner, and economy
there too.

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

### G49 — Creative actions have no common adjudication boundary (**DECIDE + FIX**)

**Current evidence.** Outside combat, the Intent Router can classify a free-form instruction as a
skill check and RulesLawyer can propose an Intimidation check, DC, and advantage/disadvantage. That
path is already flawed in the ways recorded in G25, but it exists. Once combat is active, every
player instruction bypasses that path and is forced through CombatResolver. Its prompt accepts only
move, attack, cast, ready, arbitrary condition application, advance, and end combat. There is no
typed operation for an in-combat ability check, contested social action, improvised action, creative
spell/feature/item use, environment interaction, morale response, or a non-damaging spell effect.

**Decision (2026-07-13).** This is one Play-wide contract, not a combat exception. A player may
describe any purposeful action in natural language, including an unusual use of a spell, feature,
item, terrain, social leverage, skill, or a combination of them. Combat adds timing and action
economy; it does not become an intent whitelist. The DM assesses the actual current fiction and the
actor's real capabilities. It may conclude that the result is automatic, impossible, requires a
check/contest, benefits from advantage or a DC change, or produces a bounded world/combat consequence.
A clever choice is rewarded because it changes the fictional situation, not because the player found
a magic wording.

**Example boundary.** A lone bandit whose allies have fallen may reasonably run or surrender with no
roll because the encounter state already warrants it. A creative threat or spell use can strengthen
that case and earn advantage where its written effect and the fiction genuinely help. Conversely, a
hostile or fanatical enemy may resist, and no spell phrasing creates a compulsion that the spell,
feature, or item does not actually provide. A successful social/creative action may change enemy
morale and make flight/surrender the authoritative next outcome; it does not silently grant an
unearned `end_combat` operation.

**Visibility principle (2026-07-13).** What the player learns is also contextual. The DM may narrate
an honest observable cue—an enemy looks bloodied but defiant, glances repeatedly at an exit, or
falters after a successful threat—or award a more specific read as the consequence of an action. It
must not expose private numeric state or claim a fact the engine cannot support. The server keeps
authoritative health, resolve, motives, and hidden facts private, while a Player Projection contains
only validated public cues: derived health bands, visible behavior/posture, and explicit discoveries.
A cue is a time-stamped observation in the Transcript; an explicit discovery becomes durable Campaign
Journal knowledge under G34/G45. The UI may render these cues, but never invent a permanent morale
meter merely because a private state exists.

**Context-budget principle (2026-07-13).** An adjudicator never receives all Campaign history,
world lore, actor data, or raw state “just in case.” It receives a server-built, token-budgeted
Adjudication Dossier: (1) a compact deterministic immediate-state core for the acting moment;
(2) small entity/capability cards only for the actor, targets, objects, spells, features, and facts
actually implicated by the instruction; (3) a bounded selection of relevant summaries/discoveries;
and, if needed, a small fixed number of scoped read-only fact lookups. Every included or looked-up
fact has a stable identity and visibility/authority classification. The model may cite only supplied
facts or such lookup results. Selection must degrade by omitting lower-priority history, never by
dropping current rules, action economy, or directly relevant facts. Summaries compress history; they
do not become authoritative substitutes for mechanics or discoveries.

**Dossier construction decision (2026-07-13).** Dossier construction is deterministic and
server-owned. The model does not choose which broad records, histories, or private stores to load.
It receives the fixed core plus the server-selected relevant cards, then may request only a small,
fixed budget of scoped read-only fact lookups. Lookup results remain classified evidence, not a
license to fetch arbitrary campaign context or expose it to the player.

**Combat Posture decision (2026-07-13).** Do not use a universal numeric morale track. An NPC or
enemy instead has private authored temperament/commitments (for example survive, protect a person,
buy time, or never surrender), server-derived pressure facts (such as bloodied, isolated, allies
defeated, outnumbered, leader down, restraint, and a usable escape route), and one authoritative
current Combat Posture: `fight`, `defend`, `flee`, `surrender`, or `parley`. The DM may propose a
posture change only by citing those facts and commitments; the server validates the proposed posture
and enacts it through normal combat/scene transitions. Posture is not automatically disclosed; the
player learns it only through validated Observable behavior or an earned Discovery.

**Posture checkpoint decision (2026-07-13).** Posture is evaluated only when combat begins, when a
meaningful pressure event occurs (including a leader/ally defeat or flight, becoming bloodied or
isolated, an escape-route change, or a successful creative/social action), or at the NPC's own turn
start. It is not reconsidered by an LLM after every narrated hit. A transition to `flee`, `surrender`,
or `parley` is an explicit state change that follows normal turn/scene rules rather than narration
that silently skips an encounter.

**Posture eligibility decision (2026-07-13).** The server derives physical eligibility from
consciousness, communication ability, known usable exits/routes, restraint, present actors, and the
survival of any protected person/object. Authored commitments distinguish hard constraints (for
example “will not surrender” or “must protect the relic”) from priorities (survival, loyalty, revenge,
buying time). The DM selects only a physically legal posture, must honor hard constraints, and may use
priorities as characterful evidence rather than as a deterministic score. `Flee` means normal intent
to reach an escape route, never disappearance. `Surrender` and `parley` are explicit player-visible
state changes, never forced player acceptance.

**Surrender and parley decision (2026-07-13).** A surrendering enemy becomes a yielded actor: it
cannot attack, react, or flee unless that surrender is explicitly broken, and remains real state while
other combat continues. The player may later accept the surrender, restrain/search/interrogate the
actor through normal actions, or attack. An NPC may offer parley, but that neither creates a ceasefire
nor interrupts the player with a mandatory modal; combat continues until the player side explicitly
accepts a truce. A mutual truce may transition to a normal Scene only when no remaining hostile actor
prevents it. Breaking a truce is an explicit new hostile action, not a narration side effect.

**Capability contract decision (2026-07-13).** Every player-exposed spell, feature, item, and class
ability has two server-owned contracts: an executable Mechanical Effect Contract for its exact typed
rules effect (required by G29), and a compact Creative Affordance Card for what it can plausibly
influence in the fiction and its limits (for example sound, light, force, fire, concealment,
communication, movement, or fear). The adjudicator receives the card rather than a broad rules dump
and may reward a creative use within those affordances. Evocative prose never grants an unregistered
power or replaces the executable effect contract.

**Atomic Creative Resolution decision (2026-07-13).** One creative player intent resolves as one
atomic action. It may combine a real spell, feature, item, or environment interaction with a creative
objective, but the engine validates and spends every required cost exactly once. If a referenced
capability costs an action, the creative attempt uses that action; it does not also gain an unpriced
social/skill action. Any check or contest is part of that same resolution. Outside combat, the same
contract applies with time, attention, resources, and plausible interruption in place of turn economy.

**Consequence primitives decision (2026-07-13).** Creative consequences compose a small set of
server-owned primitives rather than a menu of canned tricks or raw LLM state writes: executable rules
effects (damage, healing, conditions, movement, and resources); declared scene-object or terrain-state
changes; a sourced, scoped, expiring tactical fact; relationship, Discovery, or Combat Posture
changes; a validated surrender/retreat/encounter-resolution transition; or narration only. The DM may
combine these primitives in unexpected ways, but cannot invent a new primitive. A successful creative
plan must create a real mechanical, environmental, social, or knowledge fact that later play can use.

**Scene affordance decision (2026-07-13).** Scene opening creates a hidden, structured Affordance
Inventory alongside narration: relevant objects, terrain features, exits, hazards, and their allowed
state changes. It may include unrevealed but plausible details. A player can discover or use an entry
through normal adjudication, but the DM may not conjure a conveniently useful object only after seeing
the intended exploit. Each Scene also declares a constrained Environment Palette for genuinely
open-ended mundane details (for example a warehouse, tavern kitchen, or roadside camp). A new detail
may be introduced only when it fits that precommitted palette, then must be recorded as a Scene fact
before its effect resolves.

**Why prompts are insufficient.** An LLM can interpret an action and make a bounded DM judgment, but
it cannot be trusted to be the sole source of the relevant facts or to mutate authoritative state.
It must not invent damage, a condition, a resource change, a spell effect, a relationship change, or
an encounter conclusion. The engine must supply and validate durable evidence—actor capabilities and
resources, explicit spell/feature/item support, conditions, location/environment state, past
discoveries, NPC disposition/commitments, and objective combat events—and preserve the same action
economy, target eligibility, capability, and transcript guarantees as ordinary combat.

**Current context evidence.** `build_dm_context` already caps recent days at five and recent Turns at
six, and collapses older beats of a long Scene into `scene_progress_summary`. That is a useful
history-compression base. It nevertheless unconditionally appends all always-on lore, the full
current-act premise, scene prose, and every present-cast profile; its comments mark relevance
retrieval as future work. CombatResolver similarly receives serialized raw combat state and party.
Neither path has a per-agent context budget, relevance contract, stable fact citation, or narrow
on-demand lookup.

**Unknown.** Which objective facts/commitments make each Combat Posture eligible, and at what
checkpoints may it change? Which bounded consequence handlers can Atomic Creative Resolution invoke?
What fixed dossier budgets and which narrow fact lookups are allowed for each agent? Which facts must
be supplied to the DM so its judgment is good rather than generic? How may a scene gain a newly
relevant object or terrain feature without opportunistically inventing player advantage? Which
remaining data shape, budgets, and fact-lookup limits make this contract implementable?

**Resolve by.** Define one server-validated Creative Adjudication path shared by exploration and
combat. The DM/RulesLawyer proposes an interpretation—actor, declared method, cited relevant facts,
legal referenced spell/feature/item, whether a roll is needed, candidate skill/ability or contest,
DC, advantage reason, and proposed bounded consequence. The server independently validates the cited
facts, actor, turn/economy, actual resources, source text/capability, target eligibility,
environment state, and all derived modifiers; it then opens the same typed check/roll Pending Moment
as G25 when uncertainty remains. Implemented consequence handlers own all mutations: normal
spell/feature effects, terrain/object state, explicit Combat Posture/relationship state, discoveries,
and validated surrender/retreat/combat resolution. Add scenario contracts for a posture change and
lawful enemy flight after a rout, creative spell use that earns advantage, unusual skill use outside
combat, a clever
environmental use, an impossible request, an unsupported effect, a reward that reveals a durable
fact, and a successful attempt that changes the situation without silently inventing state. A
validated observation projection owns player-facing cues without leaking private state. Define and
test dossier selection, token caps, relevance retrieval/lookup limits, fact citations, and graceful
omission on a long-running Campaign before placing this path on the hot turn loop.

### G31 — Session RNG repeats the same rolls (**FIX**)

**Decision (2026-07-13).** Each Session owns one server-secret deterministic RNG stream: a persisted
seed plus an atomically advanced cursor. Every official random draw derives from that stream, and its
result is recorded in the authoritative Transcript/event record. The stream is unpredictable to
players, stable across retries, and auditable from persisted results. Tests inject a known stream;
production gameplay uses neither module-global randomness nor a fresh seeded generator per roll.

**Current evidence.** `session_rng(session)` constructs a new `random.Random` from the unchanged seed
on every call. Repeated attacks, saves, damage rolls, and death saves therefore restart the same
sequence; separate helpers also use module-global randomness, so randomness is both predictable and
inconsistent. The model comment acknowledges that no runtime RNG state is persisted.

**Resolve by.** Persist and transactionally advance the cursor exactly once for each official draw;
route every roll helper through it; keep tests deterministic through injection; and add regression
coverage for consecutive draws, rollback/retry, and the absence of module-global gameplay RNG.

### G38 — Only a player can start combat, and only against already-instantiated NPC ids (**DECIDE**)

**Decision (2026-07-13).** Combat may begin from a player action, a hostile NPC/monster action, or a
declared hazard through one typed Encounter Trigger. The DM may propose a trigger only from an
authored Scene hook, present cast, or a precommitted encounter/monster entry; the server validates
the source, creates the allowed participants, resolves initiative and surprise, records the reason,
and emits the authoritative combat entry. An LLM may not create enemies merely because a fight would
be dramatic.

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

### G50 — Reinforcements cannot join an active combat through ordinary play (**DECIDE + FIX**)

**Decision (2026-07-13).** V1 Reinforcement Arrivals may come only from actors already present in the
Scene or from a precommitted encounter wave with an authored trigger and entry route. Each arrival
rolls initiative through G31's Session RNG, enters through its validated zone, preserves the active
combatant's turn, starts with normal action economy, and emits a player-visible arrival event. An
actor merely “nearby” but off-scene may not teleport into combat; that awaits an explicit travel/alert
model.

**Current evidence.** A low-level `add_combatant` tool and state helper can insert a Character, NPC,
or SRD monster into an active initiative order and preserve the current turn index. It is not an
ordinary player/DM flow: no combat plan or Encounter Trigger can invoke it; the caller supplies a
pre-rolled initiative total; an NPC need not be present in the Scene; and a monster is selected by a
bare SRD name. It assigns the entrant to the first friendly zone (or the first zone) without an
arrival route, delay, encounter source, team/presence authorization, Transcript/SSE lifecycle, or
travel rule. Thus the primitive is useful implementation evidence, not actual reinforcement support.

**Unknown.** Which sources may reinforce an encounter: actors already in the Scene, precommitted
encounter waves, party/nearby actors who can realistically hear and arrive, or a later broader world
response system? When do they arrive, where do they enter, how is initiative rolled and placed, and
what can the player observe before arrival?

**Resolve by.** Define a typed Reinforcement Arrival owned by the encounter/scene runtime. Validate a
source actor or precommitted wave, team, route/entry zone, timing/trigger, and eligibility before
using the existing insertion primitive. Roll initiative with G31's server RNG, insert without changing
the active combatant, initialize normal economy, persist the source/arrival, and emit a player-safe
event/Transcript entry. Reject arbitrary NPC ids, bare monsters, and off-scene “nearby” arrivals until
their travel/alert contract exists. Contract-test allied and hostile waves, arrival before/after the
active index, invalid/off-scene source, duplicate arrival, and reconnect visibility.

### G51 — The prompt catalog has no audited product or engine contracts (**AUDIT GATE + FIX**)

**Decision (2026-07-13).** The Prompt Catalog Audit exists first to make Cairn's DM agents deeply
informed and capable of unusually good, specific Dungeon Master decisions—not merely to reduce their
authority. Each surviving agent receives a rich, server-built, role-specific evidence package: the
current authoritative moment; relevant Scene, Party, NPC, encounter, capability, and rules cards;
the selected Campaign history, discoveries, relationships, and world lore; and the exact task and
decision surface it owns. The goal is a DM that can connect a creative player action to the actual
people, prior consequences, terrain, rules, and dramatic situation rather than falling back to generic
prose or shallow keyword matching.

**Context design.** “More context” does not mean concatenating the whole database and transcript
into every call. Per G49, the server constructs a high-information Adjudication Dossier in layers:
(1) complete immediate authoritative state for the decision; (2) relevant detailed cards and selected
history, including the facts that make a surprising but grounded callback possible; and (3) a small,
bounded set of explicit scoped fact lookups when the supplied evidence identifies a genuine need.
The audit must determine, agent by agent, what evidence is essential, what is merely useful, the
retrieval/ranking rule, token budget, and lookup budget. Important omitted facts are an audit failure;
irrelevant bulk that weakens reasoning, costs excessively, or buries the current situation is not a
virtue. Summaries compress history but do not replace canonical facts, rules, or recorded discoveries.

**Authority remains deliberate.** Rich context allows a model to make strong interpretations,
creative connections, dialogue, tactical choices, and grounded proposals. It does not permit it to
silently persist arbitrary facts or mechanical outcomes. The server validates and commits durable
gameplay state through the contracts in G25/G29/G32/G49. Background work may prepare a
non-authoritative summary or draft, but cannot independently mutate facts that affect later play.
This is an execution guarantee, not a reason to starve the DM of useful evidence.

**Current evidence.** The backend has seventeen separately versioned `v1.md` agent prompts:
`ally_ai`, `combat_resolver`, `companion_reflector`, `dialogue`, `enemy_ai`, `intent_router`,
`lore_keeper`, `npc_builder`, `readied_parser`, `recruiter`, `rules_lawyer`, `scene_builder`,
`scene_director_pre`, `scene_director_post`, `scene_narrator`, `scene_summarizer`, and
`zone_seeder`. A versioned filename is not an audit: there is no catalog that states each prompt's
owner, allowed input projection, authoritative boundary, available tools, output contract,
player-visible language contract, context budget, or acceptance fixtures. Several prompts still
describe contracts being corrected elsewhere in this register—for example the combat resolver's
operation framing precedes G29/G49, the scene narrator suggests an inspiration operation that it
cannot perform (G28), the rules lawyer and zone seeder receive or reason over untrusted/raw
mechanical values (G25/G12), and broad narrative context conflicts with G49's bounded Adjudication
Dossier.

This is more than prose polish. Prompt drift can advertise unsupported actions, cause an agent to
invent authority, leak unnecessary state into an invocation, or make the player-facing game sound
generic and robotic. In particular, narration and dialogue must avoid unsolicited faux-poetic
tabletop filler (for example, abstract repeated environmental mood lines) when a concrete event,
choice, consequence, or sensory fact is needed.

**Initial prompt-by-prompt audit (2026-07-13; implementation disposition still requires the
catalog pass).**

- **`scene_narrator` — retain and substantially rebuild as the primary player-facing DM voice.** It
  needs the richest read-only dossier: committed outcome/events, current Scene and cast, relevant
  facts/history, safety/tone, and explicit visible/hidden boundary. Its current prompt asks it to
  call a nonexistent `grant_inspiration` tool and over-prescribes atmospheric output; inspiration
  instead follows G28's validated path. Its style fixtures must reject generic faux-poetic filler
  while preserving concrete sensory detail, momentum, and character-specific reactions.
- **`dialogue` — retain and enrich as the voice of one present entity.** It currently usually receives
  only profile, disposition, and player input; its advertised “recent events” are normally absent.
  Give it the current conversational situation, public history/relationship facts, goals, and only
  earned private-disclosure evidence. It may propose a disposition/relationship change, which the
  server validates; it must never expose profile secrets simply because they were supplied.
- **`rules_lawyer` — retain as an adjudication proposer, not a calculator or generic skill-check
  classifier.** The current output always requires a check despite prose that says some actions do
  not; it returns an LLM-provided modifier; and it sees no Scene, target, environment, rule detail,
  or actual player-selected actor. Replace that output with the G25/G49 proposal: no-check versus
  check/contest, actor/method, cited facts/capability, proposed DC/circumstances, and bounded
  consequence. The server derives modifiers and validates all rule facts.
- **`combat_resolver` — reshape into the G29 combat action interpreter.** Its current generic
  operation menu predates the action floor and accepts raw combat/Party JSON. It must receive an
  exact legal-action/capability/target/zone/reaction view and return only a typed intent that the
  executor can validate. It cannot grant conditions, end combat, or select raw mechanics merely by
  producing an operation name. Creative combat uses the shared G49 path rather than a second
  freeform combat loophole.
- **`ally_ai` and `enemy_ai` — retain as tactical planners, with different evidence cards.** Both
  currently see raw state and a short operation list. Ally planning needs Companion agency, player
  instruction, current goals/approval, legal capabilities, and visible allies; enemy planning needs
  authored temperament/commitments, Combat Posture, pressure facts, legal capabilities, and known
  routes. Both return a validated legal plan only; neither rolls, narrates, or writes state.
- **`intent_router` — reduce to a non-authoritative intake hint or retire after a richer common
  adjudication entry exists.** It sees only the player's text but currently chooses a processing
  branch such as `skill_check` or dialogue. It cannot know who is present, whether an action is
  risky, or whether a named target is real. A server-owned intake path must resolve those facts;
  any surviving model classifier merely extracts candidate references and cannot deny a creative or
  hybrid action because it does not fit a fixed label.
- **`readied_parser` — keep only if Readied Actions remain in the implemented G29 floor.** It should
  translate a player declaration into a strict trigger candidate over a supplied legal event/target
  vocabulary, never infer an unsupported trigger. If ready is deferred from the floor, remove this
  prompt with it; it is not a general natural-language rules parser.
- **`recruiter` — retain as a bounded in-character proposal for a candidate from G17's authored
  Companion Roster.** Current dynamic/recurring-NPC recruitment conflicts with the curated-roster
  decision. It needs the authored recruitment policy, candidate's public/private permitted evidence,
  relationship history, eligible condition keys, and Party state; the server alone makes a roster
  member recruitable and records a typed conditional requirement.
- **`companion_reflector` — retain the character judgment, but move it out of fire-and-forget
  mutation.** It currently runs after the completed Turn and directly adjusts approval from player
  input, narration, and events. It needs actual relationship history and a bounded event view, then
  may propose a typed relationship event; the foreground resolver validates, persists, and exposes
  it with the Turn. A parse failure must not silently erase a consequential reaction.
- **`lore_keeper` — retire as a writer of canonical world facts.** It currently extracts arbitrary
  “facts” from generated narration and upserts World Bible entries after the Turn. G34/G45 instead
  require durable Journal/Discovery records from authoritative events. A future non-authoritative
  index/tagging helper may summarize already-recorded facts, but it cannot create, revise, or key
  gameplay canon from prose.
- **`npc_builder` — retain only for bounded background-NPC generation/deepening.** It may create a
  small profile for an already legitimate, present background NPC and extend it without contradiction;
  it may not create major figures, recruitment eligibility, secrets that unlock authored content, or
  a new Scene cast. It needs a richer local canon/relationship card and must persist a validated
  profile/provenance before dialogue. G39/G52 control presence and portrait consequences.
- **`scene_builder` — retain only as a one-time, validated campaign-owned Scene setup service.** It
  currently writes an LLM scene into `Location.authored_scene` on first entry, with raw hidden prose
  that cannot satisfy G45's stable discovery keys. It must create the bounded Scene/Affordance
  Inventory before player interaction, validate stable keys, hooks, cast, safety, and topology, then
  persist that snapshot. It cannot add convenient people or retroactive secrets after observing a
  player plan.
- **`scene_director_pre` — merge its useful encounter/travel proposal into the foreground Scene
  adjudication path.** Current logic only recognizes player-started combat against already-present
  NPCs and direct reachable travel. Its output must be validated by G38/G39 and may not become a
  parallel world-transition authority.
- **`scene_director_post` — remove its background authority.** It currently advances acts/time,
  discovers facts, moves NPCs, changes Scene state, and schedules transitions after narration. Those
  outcomes must be proposed and committed in the foreground atomic resolution, with the narrator
  receiving the result rather than causing it retroactively.
- **`scene_summarizer` — retain solely as non-authoritative history compression.** It may run after
  the Turn and write a replaceable summary/cache, but must summarize canonical events and recorded
  facts rather than establish truth from prose. The raw full transcript needs bounded compaction and
  fixtures for omitted/contradicted facts before it feeds any future dossier.
- **`zone_seeder` — move to pre-publication Tactical Sketch drafting or retire from live combat.** It
  currently produces raw cover bonuses, free-text hazards, and an asymmetric graph at combat start.
  G12 requires typed terrain/hazard templates, derived mechanics, stable anchors, and publication
  validation. No live combat may depend on an unvalidated generated tactical map.

**Audit gate.** Before a feature slice changes agent behavior, turn the initial disposition above
into a versioned catalog for every surviving prompt: its caller, typed evidence package, retrieval
and lookup budgets, output/proposal shape, server validation path, player-visible voice contract,
and positive/negative fixtures. Retired prompts must have their caller removed or replaced. No
further product interview is required unless this audit reveals a real contradiction with a locked
contract.

**Resolve by.** Before the next feature slice, perform one Prompt Catalog Audit covering every
current prompt, rather than rewriting them as one generic mega-prompt. For each surviving agent,
record and enforce:

- its single job and deterministic owner/caller;
- the smallest typed input projection it may receive (G6/G49), its token/context budget, and any
  bounded scoped lookup it may request;
- the exact structured decision, tool call, or player-facing text it may return; unavailable tools
  and direct mechanical/persistence mutation must be explicitly prohibited;
- authoritative facts it may cite versus material it may only propose, including the server
  validation path for every proposal;
- a role-specific style contract. Player-facing prompts use concrete, varied, situation-specific
  language; they do not pad turns with generic thematic or faux-literary narration. Internal
  planners return compact operational output, not prose;
- positive and negative fixture cases, including adversarial requests to invent facts, exceed action
  economy, disclose hidden information, use an unsupported capability, or write canned atmospheric
  filler.

Then retire redundant prompts and revise the others deliberately with explicit version bumps. The
future Slice 12 evaluation harness should make these fixtures regression checks in CI, but its later
implementation does not remove the need to define this catalog and its product/engine contracts now.

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
