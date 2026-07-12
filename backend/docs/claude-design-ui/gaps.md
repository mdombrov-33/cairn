# Ember frontend contract gaps

This register records product decisions and backend dependencies exposed by the canonical Ember UI
reference. Read it before Slice 15/15.5 planning. It is not evidence that a capability exists; current
behavior remains owned by [`../architecture.md`](../architecture.md), and sequencing remains owned by
[`../roadmap.md`](../roadmap.md).

Each item states the verified evidence, why the frontend cannot safely guess, and what must be decided
or implemented. Close an item only when the owning code, tests, architecture documentation, and Ember
reference agree.

## Phase-A blockers

### G1 — Campaign resume and recap have no complete source

**Ember contract.** Selecting **Continue** opens Recap before Play. A first-ever campaign skips it, and
Play offers **Review recap** to reopen the same surface.

**Verified current evidence.** `Session.summary` is exposed by `SessionResponse`, but no current
workflow writes it. Day summaries are written and exposed through the calendar surface, while scene
progress summaries are internal narration context. There is no single response that supplies the
recap headline, recent situation, active threads, and current character state.

**Why this matters.** The frontend cannot treat a nullable, unwritten field as the canonical recap or
reconstruct narrative truth by scraping rendered turns. Doing so would make resume behavior depend on
client history and would disagree across devices.

**Decision required.** Choose the server-owned recap representation and when it is refreshed. The
smallest likely shape is a campaign/session resume read model assembled from authoritative recent
summary data, calendar entries, current scene/location, party state, and pending moments. Decide
whether `Session.summary` becomes actively maintained or is removed from the Recap plan in favor of
that read model. Add contract tests for first entry, resume, concluded campaigns, and an empty recap.

### G2 — Resume detection is not defined

**Ember contract.** Recap is a threshold on returning to an existing campaign, not a screen shown
between ordinary turns.

**Verified current evidence.** The backend's `Session` is a technical continuation record, not a
user-visible sitting, and it does not encode a browser visit or “last opened” boundary.

**Why this matters.** The frontend needs a deterministic way to distinguish starting a new campaign,
refreshing during play, reconnecting after an SSE interruption, and returning hours or days later.

**Decision required.** Keep this as frontend navigation policy unless the product needs cross-device
last-opened state. Define the exact trigger in Slice 15.5 and test that refresh/reconnect do not force
Recap while Campaign Browser → Continue does.

### G3 — Exploration-map graph is stored but not exposed

**Ember contract.** The campaign map shows discovered locations, their connections, the current
location, and known-but-unvisited exits. Layout is generated on the client because the graph has no
coordinates.

**Verified current evidence.** `Location.connections` exists in JSONB, but current HTTP responses do
not expose a campaign location graph suitable for the map.

**Why this matters.** The frontend cannot derive undiscovered/known visibility or adjacency from the
current location alone. Static mock nodes must not become an accidental API contract.

**Decision required.** Add a player-safe location-graph read surface with stable location ids, names,
player-visible descriptions, discovery state, adjacency, travel eligibility, and current location.
Private authored scene data must remain server-side. Geographic coordinates are a separate product
choice: without them Ember is an illustrated route chart, not an accurate terrain map.

### G4 — Gallery and uploaded portraits cannot be persisted

**Ember contract.** Phase A supports a curated gallery and local-file upload; generation is a visibly
disabled Phase-B affordance. The player can crop/reposition an uploaded image and select or skip a
portrait.

**Verified current evidence.** `Character.portrait_url` exists and is returned by
`CharacterResponse`, but `CharacterCreate` and `CharacterPatch` cannot set it. No upload/storage,
gallery manifest, image validation, crop metadata, or portrait mutation route exists.

**Why this matters.** A frontend-only upload preview would be lost after creation and could mislead the
player into believing the portrait was saved.

**Decision required.** Choose Phase-A asset storage and ownership, define accepted file types/size and
cropping behavior, expose the curated gallery, and add an authorized portrait update. Decide whether
the persisted value is an immutable asset id or a URL. Keep AI generation out of this contract.

### G5 — Character identity UI and the planned Weave shape have drifted

**Ember contract.** Manual editing is primary. The player edits name, appearance, backstory,
personality, voice, and goals; optional **Weave from concept** fills those same fields and never changes
mechanics.

**Verified current evidence.** `CharacterCreate` already accepts a loose `narrative_profile`. Its
typed domain shape uses `name`, `personality`, structured `voice`, `physical`, `backstory`, `goals`, and
other fields. The archived Slice-15 text still describes standalone `bio` and `voice_traits`, and no
Weave agent or endpoint exists.

**Why this matters.** Building Weave against the archived names would create a second identity model or
require lossy translation. Loose dictionaries also allow the client and backend to disagree silently.

**Decision required.** Lock a player-editable narrative-profile request/response schema, including
which fields are optional for player characters. Define Weave output against that schema and return a
draft for editing. Do not add separate `bio` or `voice_traits` concepts unless the domain model is
intentionally changed.

### G6 — Player-safe companion data is not separated from private data

**Ember contract.** A selected companion uses the full character-sheet language plus mood, vague
approval band, player-visible reason lines, and active agency. Raw approval values, numeric deltas,
`secret`, and narrative `private_facts` never appear.

**Verified current evidence.** `CharacterResponse` returns the complete `narrative_profile` and
`companion_meta` dictionaries. Those stored shapes can contain `private_facts`, raw approval,
approval-log `delta`/`total`, and `secret`.

**Why this matters.** Hiding fields in React is not a secrecy boundary; browser users can inspect the
response. It also invites later components to render private data accidentally.

**Decision required.** Add a player-facing companion projection that omits private fields and derives
the approval band/mood server-side. Decide which goals and approval reasons are public. Cover the exact
JSON with contract tests before building the Party sheet.

### G7 — Character rules text needs a stable lookup strategy

**Ember contract.** Skills, saves, features, spells, conditions, weapons, armor, and other rules nouns
are descriptive and inspectable from the sheet.

**Verified current evidence.** Character responses primarily carry names/indices and current values;
SRD routes expose several catalogs, but there is no locked frontend lookup/normalization contract for
every rules noun shown in Ember.

**Why this matters.** Hard-coded descriptions would drift from the engine, while issuing ad-hoc reads
per row would create slow, inconsistent sheets.

**Decision required.** During Slice 15.5, inventory the existing SRD endpoints against every sheet
section and choose a cached client catalog/query strategy. Add only the narrow missing reads. Rules
descriptions remain SRD-owned; the character endpoint should not duplicate the catalog.

### G8 — Alignment catalog is not exposed

**Ember contract.** Character creation uses a 3×3 alignment compass with plain definitions.

**Verified current evidence.** Alignment data ships in the SRD files and creation accepts a string,
but there is no `GET /v1/srd/alignments` route.

**Decision required.** Add the planned catalog route and validate submitted alignment against the same
catalog, or deliberately keep a frontend-owned closed list and document that contract. The current
hybrid—free input with an unavailable catalog—should not ship.

### G9 — Initial prepared-spell state is incomplete

**Ember contract.** Creation explains known/available/prepared spells correctly, and prepared casters
enter play with a legal day-one preparation. Long rests later use the dedicated preparation page.

**Verified current evidence.** Creation persists `spell_choices` into `spells_known`; the long-rest
workflow owns `prepared_spells`. The canonical reference already flags that the initial prepared-spell
contract is unresolved. Subrace spell grants are also not applied by character creation.

**Decision required.** Define creation behavior per caster type: known-spell choices, day-one prepared
choices/defaults, always-prepared subclass spells, and racial spells. Make the creation preview and
created character round-trip agree in integration tests.

### G10 — Player-rolled death saves require a suspension contract

**Ember contract.** A downed player presses **Roll death save**, uses the same focused dice surface, and
the submitted result resumes the same combat turn.

**Verified current evidence.** Active skill checks are player-rolled, but death saves are currently
engine-owned. The reference labels player death rolls as Planned Phase A.

**Why this matters.** A visual roll without a persisted combat checkpoint can reroll, race the combat
executor, or desynchronize on reconnect.

**Decision required.** Add the planned player-roll/resumption contract with exact checkpoint and SSE
coverage, or keep death saves automatic and redesign the downed state accordingly.

## Phase-A product decisions that can remain frontend-owned

### G11 — Rest entry and risky confirmation need one canonical flow

**Ember contract.** Rest begins from the persistent character band. The player chooses short or long
rest without leaving Play; success streams normally, `rest_blocked` stays inline, and only a risky rest
requires confirmation. Prepared casters continue to spell preparation after a long rest.

**Verified current evidence.** Separate short/long-rest endpoints already support immediate success,
blocked responses, and `confirm_risky`. The old reference interstitial had no engine meaning.

**Decision required.** This is primarily a Slice-15 interaction decision: use one compact rest chooser,
then render exact engine outcomes. Confirm whether risky confirmation repeats the chosen request in
place and whether cancelling returns focus to the turn input. No new rest mode or atmospheric
transition endpoint is needed.

### G12 — Combat and map geometry are illustrative, not authoritative

**Ember contract.** Combat uses a large tactical plate with named zones, occupants, cover,
difficult-terrain, hazards, and close/far connections. The exploration map uses the same inked route
language.

**Verified current evidence.** Combat zones contain descriptions and topology, not polygons or room
coordinates. A `close` edge costs 30 feet and `far` costs 60 feet; difficult terrain doubles movement.
The old mock's arbitrary 10/15-foot labels and invented “+2 to spot” annotation are not engine facts.

**Decision required.** Treat node silhouettes, paths, contour lines, and landmark art as illustrative.
Only labels, attributes, occupants, adjacency, categorical distance, and derived movement cost carry
mechanical meaning. If accurate floor plans or geographic maps become a requirement, add authored
geometry as a separate future contract rather than inferring it from prose.

### G13 — Recap access after entry is a navigation decision

**Ember contract.** Continue enters through Recap; a small **Review recap** action in the campaign rail
reopens it without pretending that Recap is a permanent global tab.

**Decision required.** Confirm this behavior during Slice-15 interaction testing. It needs no backend
change once G1 supplies the read model.

## Phase-B / deferred boundaries

### G14 — Portrait generation remains separate from gallery/upload

No image-generation provider, agent, key, moderation policy, storage lifecycle, entitlement, or cost
control exists. Keep **Generate portrait** disabled and labeled Phase B. Do not let this defer Phase-A
gallery/upload work from G4.

### G15 — Account, billing, authentication, and admin remain visual-only

The Ember shell may show their direction, but Phase A continues through the development identity seam.
Do not invent prices, usage, checkout success, admin authorization, or user-owned settings before
Slices 14/14.5 establish those contracts.

## Review checklist before Slice 15/15.5

1. Decide G1–G5 and G8–G10, or explicitly sequence them alongside the frontend.
2. Make G6 a transport-security requirement, not only a rendering convention.
3. Confirm the frontend-owned flows in G11 and G13.
4. Decide whether route-chart maps are sufficient for Phase A; if yes, keep geometry illustrative.
5. Reconcile the archived Slice-15 dependency table with this register rather than copying its older
   field names or assumptions.
