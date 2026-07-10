# Cairn — Design Document v5

> Replaces v4. v4 archived as `v4(old).md`. Each slice is a self-contained unit: build, decide, fix bugs, verify. Open design questions resolved (see "Decisions resolved 2026-05" log at bottom).

---

## What this is

A persistent-campaign TTRPG platform. One shared handcrafted world. Multiple campaigns set in that world — each with its own premise, location, conflict, and cast. Players pick a campaign, pick or create a character, and play inside that campaign until it concludes or they abandon it. An AI DM narrates scenes, voices NPCs, runs skill checks, tracks lore, and runs combat. State is fully persisted in Postgres — players resume exactly where they left off.

Stack: FastAPI + LangGraph + LangChain tools + LiteLLM + Postgres + SSE. Python-only for v1 (see decision log on Go/MCP timing).

---

## What's running today

100+ integration tests green. Foundational backend complete.

- FastAPI backend — campaigns, sessions, turns, characters, NPCs, combat, lore
- LangGraph turn graph — intent classification, Postgres checkpointer
- Seven agents — `intent_router`, `rules_lawyer`, `npc_dialogue`, `scene_narrator`, `lore_keeper`, `combat_resolver`, `combat_ai` (routes to `ally_ai` / `enemy_ai` prompts by role)
- Combat — `CombatResolver` (player turns), `combat_ai` (NPC/ally turns), death saves, 15 conditions, turn economy (action/bonus/reaction/movement tracking), saving throws / skill checks / initiative / AoE / temp HP / contests / late join / stabilize / exhaustion / XP award
- Tool system — LangChain `@tool` + `Annotated[]`, `ALL_TOOLS` + `COMBAT_TOOLS`. Combat service split into a package (`_helpers`, `state`, `mutations`, `rolls`).
- LoreKeeper — fire-and-forget after every turn, writes NPC/PLACE/EVENT/QUEST to world bible
- Turn events log — `Turn.events` JSONB, every combat mutation emits a typed event
- HITL skill checks — two-phase: setup prose → `check_required` → player rolls → outcome prose
- Auth — dev shim only: `X-User-Id` header. Real auth in Slice 14.
- Phase 0 schema work done: `feats`, `hit_die_size`, `hit_dice_remaining`, `is_dead`, `tool_proficiencies`, `armor_proficiencies`, `weapon_proficiencies` columns added.
- SRD reference data + read-only routes for races, subraces, classes, backgrounds, feats, spells, equipment, conditions, monsters, skills, languages.

### Data models

| Model             | Key fields                                                                                                 |
| ----------------- | ---------------------------------------------------------------------------------------------------------- |
| `Campaign`        | `owner_id`, `name`, `template_id` (string, no FK yet), `world_bible_namespace`                             |
| `Session`         | `campaign_id`, `current_location_id`, `combat_active`, `combat_state`, `summary`, `started_at`, `ended_at` |
| `Turn`            | `session_id`, `idx`, `player_input`, `dm_response`, `events`, `check_data`, `dice_rolls`, `checkpoint_id`  |
| `Character`       | Full D&D sheet — see model file. `is_companion: bool`, `is_dead: bool`.                                    |
| `NPC`             | Full combat + narrative fields, `disposition`, `location_id`                                               |
| `Location`        | `campaign_id`, `name`, `description`, `connections`, `zones`                                               |
| `PartyMember`     | `session_id`, `character_id` — ties characters to sessions (likely retired in Slice 5)                     |
| `WorldBibleEntry` | `campaign_id`, `namespace`, `type` (NPC/PLACE/EVENT/QUEST), `key`, `content`                               |

### Folder structure

```
backend/src/cairn/
├── agents/              combat_ai, combat_resolver, intent_router, lore_keeper,
│                        npc_dialogue, rules_lawyer, scene_narrator
├── api/v1/routes/       campaigns, sessions, turns, characters, npcs, combat, srd
├── context.py           ContextVar[current_turn_id]
├── db/                  models, queries, migrations
├── domain/services/     turns, sessions, campaigns, npcs, characters, leveling,
│                        feat_effects, equipment, combat/ (_helpers, state, mutations, rolls)
├── llm/                 client.py, router.py, models.yaml
├── pipelines/           turn_graph.py, checkpointer.py
├── prompts/             ally_ai, combat_resolver, enemy_ai, intent_router, lore_keeper,
│                        npc_dialogue, rules_lawyer, scene_narrator — all versioned markdown
├── seed/templates/      tavern_v1 (locations.yaml, npcs.yaml) — partial seed scaffolding
├── srd/                 JSON data: classes, races, spells, feats, conditions, equipment, etc.
└── tools/               combat.py, dice.py, game_state.py, resources.py, srd.py
```

---

## Architecture

### Layering (hard rules)

```
api/v1/routes/    HTTP only — parse, call service, format response
domain/services/  Business logic — no FastAPI, no SQLAlchemy imports
db/queries/       All DB access — services and tools go through here only
tools/            Thin LLM-callable wrappers — call domain/services/, never own logic
agents/           One file per agent — agent_setup() + complete()/complete_with_tools()
llm/client.py     All LLM calls — no direct litellm imports anywhere else
prompts/          Versioned markdown + Jinja2 — load_prompt(name, version)
```

### Turn flow — non-combat

```
POST /sessions/{id}/turns
  → turns.service.prepare()
    → combat_active? → hardcode "combat_action", skip graph
    → else → turn_graph.run()
        ├── narrative_action → scene_narrator streams tokens
        ├── skill_check      → rules_lawyer → check_required SSE → [player rolls] → scene_narrator
        └── npc_dialogue     → scene_narrator with npc_context
  → turn_end SSE
  → lore_keeper fires async (fire-and-forget)
```

### Turn flow — combat

```
POST /sessions/{id}/turns  (combat_active = true)
  → combat_resolver tool loop (COMBAT_TOOLS)
  → enemy/ally turns via combat_ai (routes to enemy_ai or ally_ai prompt)
  → scene_narrator streams narrative
  → turn_end SSE
```

### Agents

| Agent                                    | Prompt file                         | Model tier | Does                                                                                                                                                                    |
| ---------------------------------------- | ----------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `intent_router`                          | `intent_router/v1.md`               | Fast       | Classify: narrative_action / skill_check / npc_dialogue. Accepts both explicit ("I want an Arcana check") and implicit ("I examine the runes") phrasings → same intent. |
| `rules_lawyer`                           | `rules_lawyer/v1.md`                | Fast       | Determine skill + DC + modifier. Receives active character + thin party manifest (Slice 3).                                                                             |
| `dialogue` _(rename pending in Slice 6)_ | `dialogue/v1.md`                    | Mid        | Voice any non-player entity — NPC or companion. Receives companion approval/mood (Slice 7).                                                                             |
| `scene_narrator`                         | `scene_narrator/v1.md`              | Frontier   | Stream DM prose. Silent passive checks on scene entry (Slice 6).                                                                                                        |
| `lore_keeper`                            | `lore_keeper/v1.md`                 | Fast       | Extract NPC/PLACE/EVENT/QUEST/RELATIONSHIP from DM response, write to world bible                                                                                       |
| `combat_resolver`                        | `combat_resolver/v1.md`             | Frontier   | Tool loop for player combat actions                                                                                                                                     |
| `combat_ai`                              | `ally_ai/v1.md` or `enemy_ai/v1.md` | Mid        | **Combat only.** ally = party tactics (sees companion approval/mood), enemy = adversarial. Receives zone state (Slice 9).                                               |
| `scene_director` _(new in Slice 6)_      | `scene_director/v1.md`              | Mid        | Pre-routing — detect combat triggers, scene transitions, act progression. Advances `in_game_datetime`.                                                                  |

---

## Design philosophy

These are the experience-level goals the code serves. Keep them in mind when scoping slices.

- **Hybrid player agency.** Player can describe actions OR explicitly request rolls — both valid. DM narrates outcomes in fiction; no DC popups, no DM dashboard. The system is character-driven by default but rewards players who think mechanically.
- **System owns mechanics, LLM narrates them.** Concentration, temp HP, exhaustion, action economy, AC derivation, inspiration — all enforced in code. The LLM never has to remember a rule. This is the same philosophy as the temp_hp PHB rule already baked into `apply_temp_hp`.
- **Authoring is the foundation.** Major NPCs and authored scenes are deep documents — many pages of prose, not stubs. Builder agents produce lighter content for fill (background NPCs, unauthored locations). The system scaffolds richness through prompt-craft and state, but cannot substitute for authoring effort. Templates with thin content play thin.
- **Depth through populated worlds.** NPCs are people with multi-page backstories, current goals, prejudices, relationships, and private knowledge. Scenes are layered situations with atmosphere, surface details, hidden details, and secrets revealed progressively as engagement deepens. Companion approval and mood ride on top of the same character schema. The LLM doesn't _drive_ depth; it _honors_ depth authored or built into the world.
- **Curated foundation, AI-filled gaps.** Templates seed canon (gods, key NPCs, acts, major scenes). Builder agents fill the gaps for background NPCs and unauthored locations. LoreKeeper writes campaign-specific events. Two players on the same template start identical and diverge.
- **Theater-of-mind combat with named zones.** Not a grid. Not pure narrative. 3–6 named zones per scene, close/far/out-of-range categories, movement between zones is a tool action.
- **Per-campaign control sliders.** Players choose how much agency to delegate to AI (combat, dialogue, equipment, leveling, passive checks) via three presets + advanced overrides. No single "correct" play style.

---

## Design decisions (locked)

**Handcrafted world + campaigns.** One shared world with rich lore. Multiple campaigns set in different parts of that world — each handcrafted. The LLM executes and improvises within structure; it does not invent structure. Critical Role DM model.

**Campaign acts structure.** Each campaign is divided into acts with central conflict and core events. LLM moves through acts based on play. Final act resolution triggers epilogue + campaign complete.

**Campaign isolation + world echoes.** Campaigns are isolated. `CAMPAIGN_CONCLUDED` world bible entries echo into future campaigns as history. Async, not real-time.

**Sessions are technical, not user-facing.** Player opens game, resumes where they left off. _(Caveat: code currently exposes `POST /sessions/{id}/end` — reconciled in Slice 5.)_

**Scene summaries handle context compression. No session summarizer service.** Scene ends → `Scene.summary`. DM receives current act context + current scene summary + last N turns within scene. World bible carries long-term facts via LoreKeeper. RAG over world bible in Slice 13.

**3–4 premade characters per campaign.** Bios fit the campaign context.

**Custom character onboarding via intro scene.** 2–3 turn intro scene placed by DM, knows campaign + character context.

**Ability scores use standard array only.** `[15, 14, 13, 12, 10, 8]` sorted. Point-buy + rolled are v2. The tradeoff (less character diversity) is accepted for v1 balance simplicity.

**Backend derives all character stats from SRD.** Client sends choices, backend derives.

**One character per campaign run.**

**Hybrid player agency.** Both explicit and implicit roll requests are valid input. IntentRouter routes both to `skill_check`. DM still narrates in fiction.

**Companions are AI-controlled by default — configurable per campaign.** Full sheets, viewable by the player. Per-campaign settings (Slice 10) let players override: `Narrative` (AI everything), `Balanced` (AI proposes, player can override; checks auto-surface), `Tactical` (player controls full party, AI only does dialogue). Default = Narrative.

**NPC and companion narrative depth share one rich profile schema.** Multi-page authored documents: physical description, personality, voice, multi-paragraph backstory (5+ years of past, key events), current goals (immediate / midterm / life), prejudices, relationships (named individuals — alive, dead, missing, estranged), private facts. **No mechanical dialogue gating** — the LLM has the facts in prose and reveals them through behavior, partial answers, deflections, body language, silences. Companion approval / mood / personal_goal / secret is a layer on top of the same schema, not a separate model. (Slice 7.) Inter-companion relationships, romance arcs = v2.

**Three builder agents for unauthored content.** NPC builder generates background or recurring NPCs on demand (light-to-near-full profile depending on tier). Scene builder generates situation snapshots when the DM moves the party to an unauthored location. **No act builder in v1** — acts are the spine, authored only. Act builder is v2 territory when users author their own campaigns.

**Authoring discipline is the contract.** Major NPCs in templates are written as deep documents (many pages of prose). Authored scenes are layered (atmosphere / surface / hidden / secrets / NPCs with current beats / threads in the air / hooks out). Slice 7 and 8 deliverables include one fully authored example each as the bar. Templates that ship with thin content will play thin no matter how good the prompts are — this is non-negotiable.

**Scene depth — scenes are situations, not descriptions.** Layered authoring: atmosphere, surface_details, hidden (per-check), secrets (per unlock condition), NPCs with current activity, threads in the air, hooks_out. Runtime state on every scene: `discovered_facts`, `unresolved_threads`, `beat_count`, `tension_level`, `mood`. SceneNarrator reveals layers progressively as engagement deepens; never info-dumps. Scene Director nudges pacing via beat_count and tension. (Slice 8.)

**Party model — Characters vs NPCs:**

- `Character` (`is_companion=False`) — player's PC. Full sheet, player-controlled.
- `Character` (`is_companion=True`) — companion/sidekick. Full sheet, AI-controlled by default.
- `NPC` — all world entities: enemies, merchants, quest givers, allies. DM/AI-controlled.
- Combat ally — an NPC temporarily fighting for the party (`role="ally"`).

**Character death is a state, not a delete.** `is_dead: bool` on Character. `DELETE /characters/{id}` is mistake cleanup only.

**Death model has three modes per campaign:**

- `hardcore` — PC death = campaign ends, marked read-only "Ended (dead)".
- `narrative` (default) — DM narrates recovery with consequences (captured / wounded / in a temple in debt). HP set to 1, story continues.
- `pacifist` — PC can't drop below 1 HP. Narrative bruises only.
  Companion death always runs the death save sequence; on full failure, `status=dead`. Story-driven revival (cleric, druid companion, divine intervention) is possible — no item-based revival in v1.

**Combat is zone-based.** 3–6 named zones per combat scene. Each combatant occupies one zone. Distance categories: `close` / `far` / `out_of_range`. SRD ranges map to categories (5–15ft = close, 30–120ft = far, >120ft = out_of_range — exact mapping in Slice 9). Movement between zones is a tool action with movement-budget cost. (Slice 9.)

**Passive Perception auto-rolls silently on scene entry.** SceneNarrator rolls; on success weaves into narration ("you catch a glint under the rug"). On failure says nothing. Explicit checks ("I want to perceive") route through RulesLawyer and surface visibly. Per-campaign override available in settings.

**Concentration is system-enforced.** When a concentrating character takes damage, `apply_damage` auto-rolls a CON save (DC = `max(10, damage_taken // 2)`). On fail, drops concentration and removes the linked effect. (Slice 6.)

**Inspiration is a binary flag.** `Character.has_inspiration: bool`. Can't stack. DM calls `grant_inspiration` for good roleplay. Player calls `spend_inspiration` for advantage on a roll. (Slice 6.)

**In-game time is tracked.** `Session.in_game_datetime`. Advanced by travel actions, rests, and narrative scene transitions. Long rest requires safe location AND at least 8 in-game hours since last long rest. DM sees current time in context. UI displays it.

**Multiclass-ready schema, single-class enforced in v1.** `Character.classes: list[{name, level, hit_dice_spent}]` instead of `character_class: str`. v1 enforces `len(classes) == 1` at creation and level-up. Avoids migration when v2 lifts the constraint.

**Seedable RNG.** `Session.rng_seed: int` initialized at session creation. Services read from `random.Random(seed)` rather than module-level `random.*`. Tests deterministic without patching. Replay possible (v2).

**Spell preparation is modeled per class.** Wizards prepare from spellbook, clerics/druids/paladins from full class list, sorcerers/bards know fixed spells. `prepared_spells: list[str]` distinct from `spells_known: list[str]`. Long rest re-prepares.

**System-computes-facts.** `CombatResolver` produces typed outcome; `SceneNarrator` prose-renders from it. The LLM narrates facts, never owns them.

**Turn events log.** Every mutation calls `_emit(db, event)`. Makes evals tractable.

**Tools are thin wrappers.** Business logic in `domain/services/`. No game logic in `tools/`.

**SRD is the source of truth for rules.** Features are string names; LLM queries SRD lookup tools at runtime.

**Reactions are engine-resolved, not LLM-invented.** OA shipped inline in `move_combatant` (Slice 9); the general reaction engine — bus + registry, Shield / Absorb Elements / Counterspell / readied / Sentinel, plan-then-execute combat, engine to-hit, settings-gated player round-trip — is **locked as Slice 10.5** and generalizes that OA. No reaction bus before then.

**Action economy is tool-enforced.** `use_action`, `use_bonus_action`, `use_reaction`, `spend_movement`.

**Multi-user-ready schema, single-player v1.** Campaign membership lives in a `campaign_members` list (or `Campaign.member_ids`) from day one, even though v1 always has one member. Avoids migration when multiplayer arrives in v2.

---

## Conventions

- **NOT NULL columns with defaults** — always add `server_default` alongside `default`. Alembic only picks up `server_default`. Integers: `server_default="8"`. JSONB lists: `server_default="[]"`. JSONB dicts: `server_default="{}"`.
- **Migrations** — always Alembic-generated (`make revision`). No hand-written SQL.
- **Package management** — always `uv add`. Never edit `pyproject.toml` by hand.
- **Prompt versioning** — every agent has a versioned markdown prompt in `prompts/{name}/v1.md` with frontmatter (`temperature`, `version`). Loaded via `load_prompt(name, version)`.
- **Tool pattern** — `@tool` decorator, `Annotated[type, "description"]` per param, `await tool.ainvoke({"arg": val})` at call sites. Never `.coroutine()`.
- **RNG** — services that roll dice take a `Random` instance (or read it from session). Module-level `random.*` is for non-game contexts only.

---

## Roadmap

Each slice is self-contained: **Build** (what we ship), **Decide** (questions that block the work), **Fix** (bugs to clean up while in the area), **Verify** (acceptance criteria).

---

### Post-6 reimagining — agenda (in progress, started 2026-07)

Slices 1–6 are **DONE** and are the fixed reference (the working engine). Everything after 6 is being **reimagined from scratch**: the original post-6 slices captured the core *intent* (iterated with an LLM), but the goal now is to **enhance them, lock exact implementation at Slice-6 fidelity, add slices the old doc never covered, and hunt logic flaws / cross-slice inconsistencies** so it all coheres into one production app. Constraints: **solo dev; hosting budget $5–15/mo** (rules out AWS managed stack — see Slice on deploy); LLM API spend is a separate axis, near-zero in dev via local Qwen.

**Working method:** grill one slice → write it into this doc at full fidelity → compact → next. This doc is the shared source of truth across compactions. Plain-language framing for the user (not deep on all code internals).

**Grilled + rewritten so far:**

- ✅ **Slice 7** — reimagined & locked (see below).
- ✅ **Slice 8** — reimagined & locked (scene depth + pacing; state via resolver + Scene Director passes, no mid-stream tools).
- ✅ **Slice 9** — reimagined & locked (tactical zones + AI movement; feet-mapped movement on real Speed, hard range gate, OA inline; full reaction engine split out to its own slice).
- ✅ **Slice 10** — DONE (per-campaign gameplay settings + agency presets; model choice is deliberately absent from `Campaign.settings`; content lines/veils + narration verbosity added; account-tier model routing is configured for Phase A and becomes per-user in Slice 14.5).
- ✅ **Slice 10.5** — reimagined & locked (reaction engine; full scope OA + Shield + Absorb + Counterspell + readied + Sentinel; **engine now owns to-hit** via `roll_attack`, revising Slice 9 cover-AC to hard; reaction bus + registry; **plan-then-execute combat** — deterministic/replayable; deterministic AI heuristics; `reaction_control` suggest/player/ai via Slice 10; player round-trip via `reaction_prompt` SSE + `POST /reactions`; full nesting LIFO depth-4 economy-bounded; readied actions parsed once to structured triggers).
- ✅ **Slice 10.7** — reimagined & locked (MCP server + tool registry; **server** direction only — expose the stateful engine outward; tools are already MCP-shaped (context-by-param, own DB session); tagged **auto-discovery registry** (`@register(tags=…)`) replaces the fragile hand-maintained `ALL_TOOLS`/`COMBAT_TOOLS` — subsets are tag-derived, a guard test forbids unregistered tools; symmetric-pair **consolidation** ~58→~40; **FastMCP** streamable-HTTP mounted at `/mcp` on FastAPI, single process; **one `@tool` def → two projections**, no `mcp/` folder, no internal dogfooding; **no auth** in Phase A behind `MCP_ENABLED`, auth+internet exposure gated to Phase B).
- ✅ **Slice 13** — reimagined & locked (world-bible RAG; **pgvector-in-Postgres, no Qdrant, no GraphRAG** — corpus is small + hand-authored + tagged; hybrid dense + Postgres FTS + tag boost fused with RRF, local FastEmbed embedder + cross-encoder reranker (`RERANK_ENABLED`), two concurrent retrievals with scene-scoped lore cache; cross-campaign echoes deferred).

- ✅ **Plans & entitlements — GRILL COMPLETE, locked as Slice 14.5** (grilled 2026-07; corrected 2026-07-10). The monetization/entitlement layer above Slice 14's auth. The user's current **Free / Plus / Pro** account tier directly selects the hosted model bundle and gates campaign count · image-gen · turns/day; campaigns never select a second model tier. BYOK remains orthogonal and later. **Entitlement-first** — plan model + enforcement now, manual assignment, checkout deferred to Phase B (Lemon Squeezy/Paddle MoR). Safety/content/RAG/builders/agency **never gated**. Phase B.

**Phasing (decided 2026-07):** build the **core app + frontend running locally on the dev machine first**, then do all production/ops hardening as a **deferred second phase**. Rationale: prove the game is fun and coherent end-to-end before spending effort (and money) on deployment/observability/security. **MCP is core, not deferred** — we have 50+ tools and no MCP surface; it belongs with the core tool work.

**PHASE A — Core app + frontend (do now):**

- Existing gameplay slices to grill/enhance (keep core intent, lock implementation, find flaws): ✅ 8 (scene depth), ✅ 9 (zones), ✅ 10 (settings), ✅ 13 (RAG — pgvector hybrid dense + FTS + tags + RRF + local reranker). **All gameplay slices grilled.**
- ✅ **Reaction engine — reimagined & locked as Slice 10.5** (grilled 2026-07). Full scope (OA + Shield + Absorb + Counterspell + readied + Sentinel); **engine now owns to-hit** (`roll_attack`, revises Slice 9 cover-AC to hard); reaction bus + registry; **plan-then-execute combat** (deterministic/replayable); deterministic AI heuristics; `reaction_control` = suggest/player/ai via Slice 10; player round-trip via `reaction_prompt` SSE + `POST /reactions`; full nesting (LIFO, depth 4, economy-bounded); readied actions parsed once to structured triggers.
- ✅ **MCP integration — reimagined & locked as Slice 10.7** (grilled 2026-07). **Server** direction chosen (expose the stateful engine; client deferred — nothing external to consume yet). Tagged auto-discovery **registry** replaces the hand-maintained tool lists (fixes the `ALL_TOOLS`-rot / forget-to-append smell) + symmetric-pair consolidation ~58→~40; **FastMCP** streamable-HTTP mounted at `/mcp`; one `@tool` def → two projections (no `mcp/` folder, no internal dogfooding); no auth in Phase A behind `MCP_ENABLED`, auth gated to Phase B.
- ✅ **UI / frontend — GRILL COMPLETE, locked as Slice 15** (grilled 2026-07). **Full ground-up rebuild** of the temp reference (`Cairn App v2.html` → new `Cairn App v3.html`) into an accurate, replicable visual spec — *not* grilling frameworks. Direction locked: **"Cartographer's Table"** (waymarked-trail shell; reading-column + field-notes-margin play screen; pure-prose w/ margin ticks; modal dice; combat mode-switch w/ zone map; premade dossier + custom-forge creation; **discovered-locations node-map** as the signature; diegetic DM "thinking"; approval bands w/ no raw number; full Phase-B visual-only account/billing screens). Four backend deps surfaced (Weave agent, player-rolled death saves, portrait image-gen, template-browse endpoint). Full detail in Slice 15. **Definition of "core done": the app + frontend run on the dev machine and a full session is playable.** The visual spec is built: **`Cairn App v4.html`** (v3 + three review rounds; see Slice 15 Decisions 9–12).
- ✅ **Frontend architecture / build — GRILL COMPLETE, locked as Slice 15.5** (grilled 2026-07). The *how* to Slice 15's *what*. Stack: **Vite + React 19 SPA · TanStack Router + Query · Zustand · Tailwind v4 · React Aria Components skinned by us (no shadcn-default kit) · React Flow maps · openapi-typescript · RHF+Zod · Motion · Vitest/RTL/MSW/Playwright · Biome**. SSE via `fetch`+`ReadableStream` (typed event union → tokens to Zustand, structured events to Query cache; reconnect = refetch, no backend dep). Auth deferred to Phase B behind a swappable `authProvider` seam (Phase A = `X-User-Id`). Hosting = Vercel Hobby for now (reversible). **The retired AWS deploy slice is nuked; a budget-correct VPS deploy slice is still to be written (Phase B).**

**PHASE B — Production hardening (deferred until Phase A is playable locally):**

- **Infra / deploy.** Minimal always-on box first (the fire-and-forget post-turn work needs a persistent process, which rules out scale-to-zero serverless as the primary target), then harden. Deploy arch OPEN (ADR pending): single VPS (Hetzner/Lightsail) + docker-compose vs GCP e2-micro free tier. Budget $5–15/mo hosting. **Read refs:** `Terraform — Zero to Hero Guide.md`, `AI Deployment — Ultimate Guide.md`.
- **MLOps / observability.** Langfuse (decided) for tracing; cost/latency/error visibility; right-sized to free-tier SaaS, not a self-hosted Prometheus/Grafana stack. **Read ref:** `MLOps — Zero to Hero Guide.md`.
- **Security.** Prompt-injection defense, jailbreak/abuse handling, PII/output filtering, secret management, rate/spend abuse. **Read ref:** `AI Security.md`.
- **Auth + cost controls** (old Slice 14).
- **Ops hardening + evals** (old Slices 11, 12).
- **Sound / audio.** Ambient/scene audio + a sound-design content pass — scope TBD. (The UI/game **sound layer/plumbing** — soundcn — lands in Slice 15.5; this Phase-B item is the richer ambient/scene audio on top.)

**Also pending / cross-cutting:** rewrite the stale day-1 intro ("What's running today" etc.) to reflect reality post-6; decide final slice numbering/ordering (lean: insert named slices, don't renumber, to preserve cross-references); the deploy-arch ADR (Phase B).

**Content standard (2026-07).** Authored content depth bar = the `the_iron_vow` lore chunk + `serel_vane` profile (multi-section lore ~500–700 words; profiles with multi-paragraph backstory + full fields). **Real worlds/scenarios are 20+ files of lore + cast, not 3–4** — the architecture must assume that (retrieval-first: lean `always_on` chunks, depth in retrievable chunks + per-character profiles; RAG is Slice 13). The authored set is a **backbone** (major/recurring figures + core lore + key places); the **long tail (background NPCs, off-map locations) is generated on demand** by the NPC builder (Slice 7) and the location builder (Slice 8) — you do not hand-author everything. A full content pack for a world/scenario is **iterative content work**, not an engine-slice blocker.

---

### Slice 1 — Character CRUD + schema cleanup — DONE

Schema rewrite, derivation logic, ownership/auth pattern. See git history.

---

### Slice 2 — Feat effects + Leveling service — DONE

`domain/services/feat_effects.py`, `domain/services/leveling.py`, level-up math.

---

### Slice 2.5 — Equipment + AC derivation + feat completeness — DONE

Equipment system, AC derivation formula, armor/weapon proficiencies wired at creation, full feat-handler audit.

---

### Slice 3 — Missing combat tools + skill check correctness — DONE

_Depends on: Slice 2 for `award_xp`. Other tools independent._

Fill the gaps in `COMBAT_TOOLS` and fix the silently-broken skill-check flow.

**Build (new tools) — DONE:**

- `roll_saving_throw`, `roll_skill_check`, `roll_initiative`, `add_combatant`, `remove_combatant`, `resolve_contest`, `apply_aoe_damage`, `apply_temp_hp`, `stabilize_character`, `award_xp`, `add_exhaustion` / `remove_exhaustion`.

**Build (SRD lookup tools — confirm aliases) — DONE:**

- `get_feat_info`, `get_feature_info`, `get_spell_info`, `get_condition_effects` map to existing `lookup_*`.

**Fix (current focus — RulesLawyer context):**

The core fix: `_resolve_skill_check` in `turn_graph.py` calls `rules_lawyer.run(state["player_input"])` with no second argument. The agent has `character_context: str = ""` and renders "No character data available" into the prompt. So DCs and modifiers are based on player input alone, not the character's actual ability scores or proficiencies. **Skill checks are mechanically wrong today.** Must be fixed before Slice 12 (evals).

**RulesLawyer context payload (decided):**

- **Active character's full sheet** (ability scores, proficiencies, level, features, feats, conditions).
- **Thin party manifest** — for each other party member: `{name, character_class, level, ai_controlled: bool, key_skill_mods: {athletics: +5, perception: +3, stealth: +2, ...}}`. Not full sheets. Used so RulesLawyer can recognize "Bob can Help me with Athletics → advantage."
- "Active character" = the combatant the check is being made for. Usually the PC. If the AI controls a companion and that companion does the check, the companion is active. If player says "can my cleric companion examine these runes" → companion is active.

**Help action handling (in this slice):**

- RulesLawyer response includes `helper: {character_id, name} | None` when it judges a party member could plausibly help (matching skill proficiency, present in scene).
- If `helper` is set, the rolled check uses advantage.
- Group checks ("everyone make a stealth check") are deferred to a future slice.

**Build (loot transfer):**

- `loot_item(npc_id, item_name, character_id)` tool — moves item from NPC inventory to character inventory. **No auto-equip** — equipping is a separate player decision via the existing equip route. **No AC re-derivation** — the NPC is dead so their AC doesn't matter; the character hasn't equipped the item yet so theirs doesn't either. The tool is plain inventory mutation, nothing more.
- `POST /v1/sessions/{id}/loot` route — body `{npc_id, item_name, character_id}`. Calls the loot service directly (no LLM in the path). This is the player-facing entry point: the frontend (Slice 15) renders a "Loot body" UI that reads `GET /v1/npcs/{id}` for the inventory and POSTs each item the player picks. **No NPC state validation in Slice 3** — alive vs. dead is a narrative concern, not enforced mechanically. Pickpocketing (looting an alive NPC) requires a skill check and is deferred to Slice 6.
- The tool stays registered in `ALL_TOOLS` for future use by an exploration tool loop. Slice 3 does not wire it into any agent.

**Verify:** `roll_saving_throw` for DEX +3 proficiency at DC 14 returns correct total and pass/fail (already verified by `test_combat_tools.py`). `apply_aoe_damage` applies half damage to targets that pass the save (verified). RulesLawyer's returned modifier matches the character's actual modifier for the skill it picked. RulesLawyer with a 4-member party returns `helper={...}` when a party member has matching proficiency. Hybrid agency: both "I check the runes" and "I want an Arcana check on the runes" route to `skill_check` intent. `POST /v1/sessions/{id}/loot` moves the named item from the NPC's inventory to the character's inventory — item disappears from one, appears in the other, no AC changes, no auto-equip.

---

### Slice 4 — Short/long rest + XP/leveling routes

_Depends on: Slices 1–3._

Ship rest mechanics and the level-up flow. Services exist (Slice 2); this slice wires them through routes.

**Build (short rest):**

- `apply_short_rest(session_id)` tool — reset resources where `resets_on == "short_rest"`.
- `roll_hit_die(char_id)` tool — spend one HD, roll d{hit_die_size} + CON mod (min 1), heal.
- `POST /v1/sessions/{id}/short-rest` route (shipped name — hyphenated).

**Build (long rest):**

- `apply_long_rest(session_id)` tool — full HP, all slots, all resources, half max HD restored, exhaustion -1, **re-prepare spells** (for prepared casters), advance `in_game_datetime` by 8 hours.
- `POST /v1/sessions/{id}/long-rest` route (shipped name — hyphenated).

**Build (rest safety check — new):**

- Both rest tools call `_can_rest(db, session, type) -> (ok: bool, reason: str)`.
- Reads current scene's `safety_level` (set by scene_director: `safe | risky | hostile`) and combat state.
- Hostile or in-combat → blocked. Risky → narrative gate (DM asks "are you sure? you might be ambushed"). Safe → proceed.
- Returns reason for narrative use ("the dungeon is too dangerous to rest here").

**Build (XP + leveling):**

- `award_xp` called by combat resolver at combat end (already wired).
- `level_up_pending` event when threshold crossed; player sees pending indicator, submits choices.
- `GET /v1/campaigns/{cid}/characters/{ch}/level-up` — preview what the next level grants.
- `POST /v1/campaigns/{cid}/characters/{ch}/level-up` — applies `{hp_method, hp_roll, asi, feat, feat_options, new_spells, subclass}`.
- `POST /v1/campaigns/{cid}/characters/{ch}/grant-xp` — manual DM milestone award.
- Level-up mid-combat is allowed (D&D RAW). No combat-state gating.

**Build (spell preparation flow):**

- Long rest re-prepare for prepared casters (cleric/druid/paladin/wizard): server clears `prepared_spells`, response signals UI to prompt for re-prep, player POSTs `prepared_spells: [...]`, server validates count and class legality.
- Known-spell casters (sorcerer/bard/ranger/warlock) skip this flow.

**Fix:**

- **`resets_on` never consumed** — resources have a `resets_on` field but nothing reads it. `apply_short_rest` and `apply_long_rest` scan resources and reset by trigger.
- **Subclass features at later levels not auto-granted** — read subclass level table, append matching features on level-up.
- **Bardic inspiration uses** — special-case in `initialize_resources` and level-up: `bardic_inspiration: {current: cha_mod, max: cha_mod, resets_on: long_rest}` (becomes `short_rest` reset at bard L5).

**Decide:**

- **Companion leveling** — auto vs player choice. Resolved by Slice 10: depends on `settings.companion.leveling`. `ai` → server picks balanced choices; `player` → player submits choices same as their PC.
- **Short rest hit dice** — PHB allows multiple HD per short rest. ~~Keep one-at-a-time via repeated `roll_hit_die` calls; player decides when to stop.~~ **Superseded (Slice 15 resolution + shipped route):** the rest is one click, the route takes no body, and hit-dice spend is automatic inside `apply_short_rest`; `roll_hit_die` remains an internal tool, not a player-driven loop.

**Verify:** Defeat enemy → XP awarded → threshold crossed → `level_up_pending` event → preview returns correct features → submit choices → Character updated. Short rest restores Action Surge but not Hit Dice on the same trigger. Long rest re-prep prompts wizard; sorcerer skipped. Rest in active combat is rejected. Mid-combat level-up works.

---

### Slice 5 — World restructure + auxiliary schema — DONE

_Depends on: Slice 4._

Restructures `Campaign → Session → Turn` to `World → CampaignTemplate → Campaign → Scene → Turn`. Also bundles the v1 schema additions that don't fit elsewhere: multiclass-ready schema, in-game time, RNG seed, multi-user-ready membership, campaign settings JSONB, inspiration flag.

This is the biggest schema slice. One autogenerated alembic migration covers all the changes — pre-launch, no production data, nuke-and-reseed is fine.

**Why this slice exists — the narrative continuity contract.**

Every schema choice here serves one goal: an event in turn 1 still influences the story in turn 500. Players, NPCs, factions, promises, debts, deaths — all interpolate forward. The DM is not a memoryless improv engine; it's a campaign-aware author with permanent recall over canon facts and graceful compression of the rest.

The data model that delivers this — locked in this slice, refined in later slices:

```
WORLD ─────────────────────────── canonical lore (factions, geography, deities, history).
                                  Authored prose. Read-only at runtime.
                                  Names notable figures so templates can ground in shared canon.
                                  Calendar definition (month names, hours_per_day) lives here.

  ↓

CAMPAIGN TEMPLATE ─────────────── scenario in the world. Premise, acts (3–5), core events (3–4 per act).
                                  Owns NPC + location blueprints — the cast and stage.
                                  May reference world figures (a template can feature a world-canon
                                  character; that character also gets a normal NPC blueprint inside the
                                  template, optionally tagged with a world_lore_ref).
                                  Authored content.

  ↓

CAMPAIGN ──────────────────────── one player's playthrough. Clones the template's NPC/location blueprints
                                  into per-campaign rows on creation — mutations from play stay isolated
                                  to this playthrough (campaigns are isolated by locked design).
                                  Tracks current_act_index, settings, status, member_ids.
                                  Builder agents (Slices 7, 8) extend the roster mid-play with background
                                  NPCs / unauthored scenes — these attach to the campaign, not the template.

  ↓

SCENE ─────────────────────────── a situation, not a description. Owned by the campaign, tagged with
                                  act_index + location. Holds summary, mood, safety_level, and (Slice 8)
                                  layered authored content + runtime state (discovered_facts, threads,
                                  beat_count, tension). Scene Director (Slice 6) owns scene lifecycle.

  ↓

TURN ──────────────────────────── one player input + one DM response. Has events log + check_data +
                                  scene_id. Granular evals operate at this layer.

CROSS-CUTTING:
  WORLD BIBLE ENTRIES ────────── per-campaign canon: NPC profiles, places, events, quests,
                                  relationships, factions, day summaries, campaign-concluded markers.
                                  LoreKeeper writes; RAG retrieves (Slice 13).
                                  This is the actual long-term memory — turn 500 reaches turn 1 through here.

  DAY SUMMARIES ──────────────── written when in-game-hours crosses a day boundary. Compression layer
                                  above scenes. Drive both the calendar UI sidebar and DM context.
```

**How the DM stays continuous across an arbitrarily long campaign:**

When SceneNarrator (or any DM-facing agent) builds context for a turn, it stacks layers from largest to smallest scope. None of these layers replace the others — they all flow into the prompt.

```
1. World lore — FILTERED         template's `always_on_lore_keys` chunks + chunks retrieved by RAG
                                 over current location / NPCs present / active threads. Never the
                                 full world. Prompted as "background; do not steer scenes toward
                                 these elements." (RAG wired in Slice 13.)
2. Current act premise           + core events of this act (small, always-on)
3. Relevant world bible entries  retrieved via RAG over the campaign's bible (Slice 13)
4. Recent day summaries          last 5-7 days verbatim — tunable per campaign
5. Older day summaries           available via retrieval, not always loaded
6. Current scene state           discovered_facts, NPCs present, threads (Slice 8 fills this)
7. Recent turns in scene         last N turns verbatim
```

Every schema field this slice ships exists to feed one of those layers. The DAY_SUMMARY type, the `embedding` column on world bible, the `Scene.summary`, the calendar definition on World, the `current_act_index` on Campaign, the `revealed_at_turn_id` on world bible entries — they're not bookkeeping, they're the spine of continuity. If we ship this slice and an event in turn 1 can't influence turn 500, the slice failed.

**Decide first:**

- **Session lifecycle** — `POST /sessions/{id}/end` route + `Session.ended_at` + `Session.summary` conflict with locked design ("sessions are technical"). Resolution: drop the route, treat sessions as auto-managed play blocks, repurpose `summary` for an internal play-block summary used in context assembly. Lock here.
- **Act length** — aim 20+ hours of play per act, under 200 total. Needs playtesting.
- **Act advancement detection** — explicit `advance_act()` tool. Auditable, no auto-guessing.
- **World bible visibility** — players can see discovered lore via `GET /v1/campaigns/{cid}/lore`. Filtered by what the DM has mentioned (LoreKeeper tags entries with `revealed_at_turn_id`).
- **Adventure layer** — fold into Scene or keep as separate layer. Lean Scene-only (Adventure is bookkeeping over scenes within an act); decide during build.

**Build (data model):**

- `World` model — `name`, `calendar: JSONB`. Seeded by us.
- `WorldLoreChunk` model — **lore is chunked, not a single blob.** Each faction, region, deity, notable figure, historical event is its own row: `world_id` FK, `category` (`faction | region | deity | figure | history | custom`), `key`, `title`, `content` (prose), `tags` (list[str], used for retrieval matching — location names, faction names, themes), `embedding: vector` (nullable, populated in Slice 13), `always_on: bool` (some chunks every campaign in this world sees; most are retrieval-only).
  - **Why chunked**: dumping the full world into every DM prompt biases the LLM toward forcing world-lore elements into every scene. Chunking + retrieval lets the DM see only the lore relevant to the current scene/location/NPCs, with strict prompt discipline ("background reference; do not steer scenes toward these elements").
  - Templates can mark additional chunks as always-on for their scenario via `CampaignTemplate.always_on_lore_keys: list[str]`.
- `CampaignTemplate` model — `world_id` FK, `title`, `premise`, `acts` JSONB (`[{title, premise, core_events: [str]}]`), `status: draft | published`.
- `PremadeCharacter` model — `template_id` FK, full character sheet JSONB. **Scope for this slice: ship the model + seed-loader + ONE authored example for `tavern_v1`.** The remaining 2-3 premades are content-authoring work, parallel to engineering, can land any time after.
- `Campaign` updates:
  - Replace string `template_id` with FK to `CampaignTemplate`.
  - Add `status: active | completed | abandoned | ended_dead`.
  - Add `current_act_index: int`.
  - Add `settings: JSONB` (default `{}`, structure defined in Slice 10).
  - `death_mode` lives inside `settings` JSONB (no top-level column). Slice 10 defines the full settings shape.
  - Add `member_ids: list[str]` (single-player v1, multi-ready for v2).
- `Scene` model — `campaign_id`, `act_index`, `location_id`, `started_at`, `ended_at`, `summary`, `scene_mode: exploration | combat | social`, `safety_level: safe | risky | hostile`. **Table is created in this slice but no rows are written yet** — Scene Director (next slice) owns scene creation and transitions.
- `Turn.scene_id` FK — **nullable in this slice.** `# TODO next slice: Scene Director creates Scene rows on transitions; backfill existing turns to the active scene; tighten this column to NOT NULL once populated.`
- `Session` updates:
  - Keep `in_game_hours_elapsed` (shipped in Slice 4) as the arithmetic field for all time math.
  - Add `rng_seed: int`.
- `World` updates:
  - `calendar: JSONB` — in-world calendar definition (`month_names`, `days_per_month`, `weekday_names`, `epoch_label`, `hours_per_day` default 24). Authored once per world. `format_in_game_time(hours, calendar)` helper returns labels like "Day 4 of Riftfall, late evening". The single shipped world (`cairn_v1`) gets a basic authored calendar in this slice — month/day naming can be sparse, the mechanism is what matters.
- `Character` updates:
  - **Replace `character_class: str` with `classes: list[{name: str, level: int, hit_dice_spent: int, subclass: str | None}]`.** v1 enforces `len(classes) == 1` at creation/level-up; v2 lifts.
  - Add `has_inspiration: bool` (default false).
  - Add `companion_meta: JSONB` (default null; populated for `is_companion=True` in Slice 7 — `approval`, `mood`, `personal_goal`, `secret`).
- `WorldBibleEntry`:
  - Add `embedding: vector` column (nullable; populated in Slice 13 RAG).
  - Add `revealed_at_turn_id: int | None` (player lore-book visibility filter).

**Build (seed runner):**

- `make seed TEMPLATE=tavern_v1` loads authored content from files into DB. Splits cleanly:
  - **DB-row authored content** (one-time, idempotent upserts):
    - `seed/worlds/cairn_v1/` — `world.md` (calendar, top-level world fields) + `lore/*.md` (one file per `WorldLoreChunk`: faction, region, deity, figure, history). Markdown with frontmatter; body is prose.
    - `seed/templates/tavern_v1/template.md` — premise, acts, `always_on_lore_keys`, `world_id` reference. Authored prose for premises and act core_events.
    - `seed/templates/tavern_v1/premade_characters/*.md` — frontmatter = sheet, body = bio/personality. Ship one authored example in this slice.
  - **YAML-cloned-per-campaign content** (cloned into per-campaign rows at campaign creation, mutated during play):
    - `seed/templates/tavern_v1/npcs.yaml` and `locations.yaml` — existing files. Cloning logic stays as-is.
- Authoring UX (admin UI for editing world/template content in-browser) is out of scope for this slice — files are the v1 authoring surface; UI can come later without schema changes.

**Build (scene hierarchy logic):**

- `SceneNarrator` context updated: current act premise → current scene summary → last N turns within scene + current `in_game_datetime`.
- When scene ends: write summary to `Scene.summary`, advance `in_game_datetime` by scene duration.
- When campaign concludes: LoreKeeper writes `CAMPAIGN_CONCLUDED` world bible entry.

**Build (world bible updates):**

- Add `FACTION`, `SESSION_END`, `CAMPAIGN_CONCLUDED`, `RELATIONSHIP`, `DAY_SUMMARY` to `_VALID_TYPES` in `agents/lore_keeper.py`.

**Build (day-roll + calendar):**

- `domain/services/day_roll.py` — watches `in_game_hours_elapsed`; when a turn or rest crosses a day boundary (every `hours_per_day` from world calendar), assembles that day's `Scene.summary` rows + key turn events into a paragraph and writes a `DAY_SUMMARY` world bible entry (`day_index`, `label` from `format_in_game_time`, `summary` text). Permanent — never deleted, never overwritten.
- DM context layering (used by SceneNarrator, locked here, refined in Slice 6/8):
  1. Relevant world bible entries via RAG (Slice 13 wires retrieval; column shipped this slice).
  2. Current act premise + core events.
  3. Last N days verbatim (default N=5, tunable per campaign later).
  4. Current scene state — discovered_facts, threads, NPCs present (`Scene.runtime_state` lands in Slice 8; placeholders for now).
  5. Last N turns in current scene verbatim.
- `GET /v1/campaigns/{cid}/calendar` route — returns all `DAY_SUMMARY` entries ordered by `day_index`. Powers the calendar sidebar UI in Slice 15 (clickable day → summary text).

**Build (multiclass migration mechanics):**

- Data migration: for each existing character, write `classes = [{name: character_class, level: level, hit_dice_spent: 0, subclass: subclass}]`.
- Update `character_to_dict`, `CharacterCreate`, `CharacterResponse`, all leveling code, all references.
- Validation rule in service: `if len(classes) != 1: raise ValueError("multiclass not supported in v1")` until v2 lifts it.

**Build (RNG plumbing):**

- `Session.rng_seed: int` — stored for the record; v1 does NOT persist runtime state across rolls. Replay is a v2 feature; we'll add `rng_state` persistence then if we want it.
- `domain/services/rng.py::session_rng(session) -> random.Random` returns `random.Random(session.rng_seed)`.
- Refactor combat service callsites to use `session_rng(session)` instead of module-level `random.*`.
- Tests pass a known seed and assert against predicted sequences while holding the Random object — no cross-roundtrip determinism promised in v1.

**Fix:**

- **`Campaign.template_id` string with no FK** — migrate to FK.
- **`PartyMember` is per-session, not per-campaign** — drop the table; derive party from `Character.campaign_id`.
- **`scene_narrator` has no campaign context** — fix in the context update above.
- **`lore_keeper` key generation inconsistent** — inject existing entry keys into the LoreKeeper prompt for match-or-create.
- **`NPC.disposition` never read** — fix in Slice 6 dialogue rewrite + `scene_narrator` context update here.
- **Session lifecycle conflict** — drop the route, document.

**Verify:** `Scene` table exists (empty — populated by Scene Director next slice). `Turn.scene_id` column exists and is nullable. `SceneNarrator` context bounded to current act + recent day summaries + (later) scene. Campaign conclusion writes `CAMPAIGN_CONCLUDED`. `make seed TEMPLATE=tavern_v1` creates a playable campaign. Existing characters migrated to `classes` array without data loss. Combat services use `session_rng(session)` — a test that constructs a Random with the same seed produces the predicted sequence (no cross-roundtrip determinism promised in v1).

---

#### How this slice works (reference)

A map of what was built and how the pieces talk to each other. Read this when you come back and need to reconstruct the mental model — it describes the _system_, not the diff.

**The data hierarchy and what owns what**

```
World (worlds)                  authored canon: name, calendar (month names, hours_per_day).
  └─ WorldLoreChunk             one row per faction/region/deity/figure/history. always_on flag
     (world_lore_chunks)        marks chunks every campaign sees; the rest are retrieval-only.
CampaignTemplate                a scenario in a world: premise, acts[] (each with core_events),
  (campaign_templates)          always_on_lore_keys, status. Authored once.
  └─ PremadeCharacter           pickable pre-rolled sheets for the template (sheet JSONB).
     (premade_characters)
Campaign (campaigns)            a player's playthrough. FK -> template. Tracks current_act_index,
                                status (active/completed/...), settings JSONB, member_ids.
  ├─ Character                  party = characters with this campaign_id (no join table).
  │                             classes JSONB [{name,level,hit_dice_spent,subclass}], single-class
  │                             in v1; class_name/subclass_name are read-only properties over it.
  ├─ NPC / Location             cloned from the template's YAML at campaign creation; mutate in play.
  ├─ Scene (scenes)             situations. TABLE EXISTS BUT EMPTY this slice — Scene Director
  │                             (Slice 6) creates rows and stamps Turn.scene_id.
  ├─ Session (sessions)         technical play-block. One per campaign (no /end). Holds
  │                             in_game_hours_elapsed, last_day_summarized, rng_seed.
  │   └─ Turn (turns)           one player input + DM response. scene_id is nullable for now.
  └─ WorldBibleEntry            per-campaign canon written by LoreKeeper + day_roll. Types now
     (world_bible_entries)      include FACTION/RELATIONSHIP/DAY_SUMMARY/CAMPAIGN_CONCLUDED.
                                day_index orders DAY_SUMMARY rows; revealed_at_turn_id is the
                                player-visibility filter; embedding is nullable until RAG (Slice 13).
```

Distinction that drives everything: **template content is authored canon (seeded once, never mutates); campaign content is per-playthrough (cloned, mutates freely).** Two players on `tavern_v1` start identical and diverge.

**Layers (per CLAUDE.md) and who calls whom**

- `api/v1/routes/` — HTTP only. `campaigns.py` now also serves `GET /{id}/lore` and `GET /{id}/calendar` (both via `lore_service`, not direct queries). `sessions.py` lost `/end` and `/lore`. `turns.py` builds the DM context (skipping combat/rest) and passes it to `scene_narrator`.
- `domain/services/` — business logic, no FastAPI/SQLAlchemy-engine imports:
  - `campaigns.py` — `create()` resolves the template _key_ from the request to a template _row_ (404 if unseeded), then clones NPC/location YAML. `advance_act()` bumps the act or, past the final act, sets `status=completed` and writes a `CAMPAIGN_CONCLUDED` entry. Scene Director (Slice 6) is the future caller of `advance_act`.
  - `sessions.py` — `start()` assigns a random `rng_seed`; party derives from `campaign_id`, no enrollment.
  - `rng.py` — `session_rng(session)` -> `random.Random(seed)`. Combat (`combat/rolls.py`, `combat/state.py`) threads this through every die roll. Not persisted across rolls (replay = v2).
  - `day_roll.py` — `maybe_roll_days(db, session)`: walks session→campaign→template→world for `hours_per_day`, and for each newly elapsed day writes a `DAY_SUMMARY`. Wired into short/long rest (the only time-advancing actions this slice; travel/scene time comes with Scene Director).
  - `narrative_context.py` — `build_dm_context(db, session_id)` assembles the layered DM context: always-on lore → current act → recent day summaries → recent turns. RAG (layers 1 full + 3 + 5) and scene state (layer 6) are intentionally stubbed; they land in Slices 13 and 8.
  - `lore.py` — ownership-checked reads of world bible / day summaries for the routes.
- `agents/lore_keeper.py` — extracts canon from the DM response into the world bible; now receives existing entry keys so it updates instead of duplicating.
- `db/queries/` — the only place that touches the ORM. New modules: `worlds`, `campaign_templates` (+ premades). `characters.get_party_for_session` replaces the dropped `party_members`.
- `cli/seed.py` — admin entry point (`make seed TEMPLATE=<key>`). Reads authored markdown+frontmatter / YAML from `seed/` and upserts World + WorldLoreChunk + CampaignTemplate + PremadeCharacter. Reuses the Python queries directly (it's an ops script, not an HTTP path). See deferred note on a future standalone CLI.

**A turn, end to end (non-combat):** `POST /sessions/{id}/turns` → `turns.service.prepare()` runs the graph to classify intent → route calls `narrative_context.build_dm_context()` → streams `scene_narrator` tokens with that context → on completion, `schedule_lore_keeper()` fires async to write canon. A long rest advances `in_game_hours_elapsed`, which triggers `day_roll.maybe_roll_days()` → a `DAY_SUMMARY` lands in the world bible → the next turn's context includes it, and `GET /campaigns/{id}/calendar` surfaces it.

**Authoring workflow:** edit files under `seed/worlds/<world>/` and `seed/templates/<template>/`, run `make seed TEMPLATE=<key>` (idempotent upserts). NPC/location blueprints stay as YAML and clone at campaign creation; world/template/premade are DB rows.

**Deliberate deviations from the original spec (not bugs):**

- _No `len(classes) == 1` validator._ There is no API path to submit more than one class (`CharacterCreate` takes a single `character_class`), so an explicit guard would be dead code (CLAUDE.md: no error handling for impossible scenarios). Single-class is enforced by the absence of a multiclass entry point.
- _No character data-migration._ The migration drops `class`/`subclass` and adds an empty `classes` array; we used nuke-and-reseed (pre-launch, no production data). If a populated DB ever needs this migration, a backfill step must be added first.
- _Campaign conclusion mechanism is `advance_act()`, not LoreKeeper._ The spec phrased it as "LoreKeeper writes CAMPAIGN_CONCLUDED"; in practice the explicit `advance_act` service writes it directly on the final-act transition (auditable, no LLM guessing — matches the "explicit advance_act() tool" decision).

---

### Slice 6 — Scene Director + Dialogue rename + Combat polish - DONE

_Depends on: Slice 5._

The "make the DM smart" slice. Adds meta-routing via Scene Director, restructures the turn graph so combat is no longer special-cased outside it, ships system-enforced concentration + inspiration + death modes, extends loot, polishes combat, and lays the foundation for the dialogue and DM-persona work that lands in Slices 7 + 8.

This slice is the largest architectural shift since Slice 5. This section is the implementation handoff — every decision is locked here.

#### Architectural shift — turn graph topology

Before Slice 6, `turns.service.prepare()` branches: if `db_session.combat_active` it hardcodes `intent="combat_action"` and skips the graph entirely; otherwise it runs `turn_graph.run()` which is `route_intent → (skill_check | npc_dialogue | rest | END)`. Combat is special-cased outside the graph.

After Slice 6, the graph runs every turn. Scene Director is the first node. Combat is a routing decision inside the graph, not a bypass before it. The streaming boundary stays at the route layer — the graph produces non-streaming pre-processing only; the route layer then streams the chosen narrator/resolver.

```
START → scene_director (pre-input pass)
  ├─ combat_active=true               → combat_terminus
  ├─ combat_trigger detected          → combat_entry → combat_terminus
  ├─ pending_transition set on session → scene_create → intent_router → resolvers
  └─ no meta event                    → intent_router → resolvers
```

A second Scene Director pass (post-response) runs **after** streaming completes, in the same fire-and-forget slot as LoreKeeper. It updates Scene state for the next turn — see Scene Director section below.

The `combat_active` bypass in `turns.service.prepare()` is removed. The route layer reads the graph's final state to decide what to stream (combat resolver vs scene narrator vs skill check setup vs npc dialogue vs rest context).

#### Build — Scene Director (the centerpiece)

**Two LLM passes per turn. Both are required for the slice to function.**

##### Pre-input pass (latency-critical, fast tier)

- `agents/scene_director.py::run_pre(player_input, context) -> ScenePreOutput`
- `prompts/scene_director_pre/v1.md` (Jinja template)
- `llm/models.yaml` entry under `agents:` for `scene_director_pre` (fast tier, with fallbacks)

**Input** (assembled by `domain/services/scene_director_context.py::build_pre_input_context(db, session_id, player_input) -> dict`):

```
player_input: str
current_scene:
  location_name: str
  scene_mode: str                  # exploration | social
  safety_level: str                # safe | risky | hostile
  authored_summary: str | None     # Scene.summary if set (rare — usually only set after scene closes)
  npcs_present: list[{name, role, disposition}]
reachable_locations: list[{id, name, one_line}]   # from Location.connections of current location
combat_active: bool
pending_transition: bool           # if true, scene_create runs this turn; pass mostly no-op
current_act:
  title: str
  premise: str                     # 1–2 sentences
session_time_label: str            # e.g. "Day 4 of Riftfall, late evening"
```

Deliberately omitted: mood, beat_count, tension_level (Slice 8 columns); turn history (post-response's job); companion approval (Slice 7); world bible chunks (RAG = Slice 13); full NPC profiles (Slice 7 — disposition + name is enough to identify hostile targets).

`npcs_present` source for Slice 6: `npc_queries.list_by_location(campaign_id, location_id)`. **Slice 8** introduces scene-level presence (`Scene.npcs_present` JSONB with in-scene state) and switches the source then. (Slice 7 kept NPCs at the location level; scene-level presence is a scene concern.)

**Output** (`ScenePreOutput` TypedDict):

```python
{
  "combat_trigger": {"hostile_npc_ids": list[uuid]} | None,
  "scene_transition_pull": {"to_location_id": uuid, "reason": str} | None,
  "pacing_nudge": str | None,        # always None in Slice 6 — schema slot for Slice 8
}
```

##### Post-response pass (background, mid tier)

- `agents/scene_director.py::run_post(player_input, dm_response, context) -> ScenePostOutput`
- `prompts/scene_director_post/v1.md`
- `llm/models.yaml` entry for `scene_director_post` (mid tier, with fallbacks)
- Scheduled by the route layer **after streaming completes**, via `asyncio.create_task` in the same slot as LoreKeeper. The player never waits on it.

**Input** (assembled by `scene_director_context.py::build_post_response_context(db, session_id, turn_id) -> dict`):

```
player_input: str
dm_response: str                   # the streamed narration that just landed
current_scene:                     # same shape as pre-input + nothing extra in Slice 6
  location_name, scene_mode, safety_level
recent_turns: list[{player_input, dm_response}]   # last N=5 within current scene
combat_events_this_turn: list[dict]               # from Turn.events JSONB (combat events only)
current_act:
  title, premise
  core_events: list[str]           # for act_progress detection
session_time_label: str
```

**Output** (`ScenePostOutput` TypedDict):

```python
{
  "combat_ended": bool,              # safety-net; combat_resolver is the primary authority
  "scene_transition_push": {"to_location_id": uuid, "reason": str} | None,
  "time_advance_hours": int,         # 0 unless scene_transition_push is also set (see Time advancement)
  "act_progress": bool,              # true if DM narrated a core_event resolution
}
```

Slice 8 will extend post-response output with `tension_delta` and `mood`.

##### Combat trigger handling

When pre-input pass returns `combat_trigger != None`:

- `combat_entry` graph node calls `combat_service.state.init_state(db, session_id, enemies)` directly — no LLM hop. Enemies are derived from `combat_trigger.hostile_npc_ids`.
- Invalid NPC ids (not in scene, or unknown) are filtered with a warning log. If the result is empty, `combat_entry` falls back to no-op and the graph routes to `intent_router` (player swung at nothing; DM narrates as narrative_action).
- `init_state` flips `Session.combat_active = true`, initializes `combat_state` (initiative, combatants, etc.).
- Graph then routes to `combat_terminus`; route layer streams the combat resolver.

**Scope for Slice 6:** NPC-driven combat triggers only. SRD-monster spawns from authored scenes (e.g., "you walk into a room with three goblins") are deferred to Slice 8, which adds authored `encounter` declarations on scene YAML.

**Combat END** is owned by `combat_resolver` via the existing `end_combat` tool — combat_resolver is the deterministic authority for when combat is over (all enemies at 0 HP; or TPK). The post-response Scene Director pass only OBSERVES `combat_active=false` and may detect a follow-on scene transition. It does not itself flip `combat_active`.

##### Scene transition handling (pending_transition flag)

Scene boundaries are detected by either pass and applied on the **next** turn:

1. **Detection.** Pre-input pass MAY set `Session.pending_transition: {to_location_id, reason}` when the player pulls a transition ("I head to the tavern"). Post-response pass MAY set the same flag when the DM pushes a transition ("...you walk out into the cold street and head home"). Detection is the only thing the post-response pass does for scene boundaries — it never mutates Scene rows itself.
2. **Application.** On the next turn, the pre-input pass sees the flag set, and the graph routes through a `scene_create` node before `intent_router`:
   - Calls `scene_summarizer` agent (new — see below) to write `Scene.summary` + `ended_at` on the old scene.
   - Creates the new `Scene` row (location_id, started_at, scene_mode from authored data if any else `exploration`, safety_level default `safe`, summary `None`).
   - Stamps the current `Turn.scene_id` with the **new** scene id. The previous turn (whose post-response pass set the flag) keeps the old scene_id — its action belonged to the old scene.
   - Clears `Session.pending_transition`.
3. SceneNarrator on this turn receives `is_scene_entry=true` in its context. The Slice 8 layered-scene rules later use this flag for "first-entry narration discipline" (atmosphere first, 2–3 details max). Slice 6 SceneNarrator just uses it to weave in the arrival moment.

Sub-cases:

- **Unauthored target location**: scene_create writes a thin Scene row with only required fields. SceneNarrator falls back to `Location.description` + nearby NPCs + act premise + current scene `mood`/`safety_level`. Slice 8 `scene_builder` will enrich.
- **Pre-input pass and post-response pass both set the flag on adjacent turns**: the post-response pass on turn N sets it; pre-input pass on turn N+1 reads and acts; if turn N+1's pre-input also detects a new pull, the second detection silently overwrites the first (the second is more recent and reflects the player's most recent intent).

##### `scene_summarizer` — new dedicated agent

- `agents/scene_summarizer.py`
- `prompts/scene_summarizer/v1.md` (fast tier)
- `llm/models.yaml` entry for `scene_summarizer`
- Called synchronously from `scene_create`. Input: the old scene's authored data (if any) + the list of `(player_input, dm_response)` pairs for all turns belonging to the scene. Output: a 1–2 paragraph prose summary written to `Scene.summary`.
- Cost is acceptable in the latency path because transitions are infrequent (~every 10–30 turns), and the user is reading the new scene's narration anyway.

##### Initial scene on session start

`sessions.service.start()` eagerly creates the campaign's first `Scene` (location = `campaign.current_location_id`, scene_mode = `exploration`, safety_level = `safe`). Every turn from turn 0 has a non-null `scene_id`. No special "no current scene yet" state machine edge.

If the player's first input happens to be a transition, the pre-input pass sets `pending_transition`; the **second** turn's `scene_create` handles it (turn 0 stays in the auto-created scene). Acceptable — authored campaigns nearly always have an authored opening scene at `current_location_id` anyway.

##### Existing turns / migration backfill

Migration: `DELETE FROM turns; DELETE FROM sessions;` + `ALTER COLUMN scene_id SET NOT NULL` on the turns table. Pre-launch posture, same as Slice 5. No backfill script needed.

#### Build — Time advancement coordination

Slice 6 introduces a second writer to `Session.in_game_hours_elapsed` (Scene Director post-response), alongside the existing rest service. To prevent double-counting and centralize day-roll triggering:

- **New service**: `domain/services/time.py::advance_time(db, session, hours: int, source: str) -> None`. Updates `in_game_hours_elapsed`, emits a `time_advanced` event into `Turn.events` (with `source`), and calls `day_roll.maybe_roll_days`. Single writer, single day-roll caller.
- **Migrate rest service** onto it (was calling `day_roll` directly).
- **Post-response handler** checks `Turn.events` for a `time_advanced` event BEFORE applying Scene Director's `time_advance_hours` proposal. If already present, skip and log. Prevents long-rest + DM-narrated-sleep double-count.
- **Narrative time advancement is bounded**: Scene Director's prompt instructs that `time_advance_hours > 0` is only valid if `scene_transition_push` is also set on the same response. Mid-scene narration never advances time. This makes sense narratively (a scene is a few minutes; the boundary is the natural commit point) and bounds the LLM's discretion to one decision per transition.

#### Build — Scene mode + combat_active orthogonality

`Scene.scene_mode` (`exploration | combat | social`) and `Session.combat_active` (bool) are **orthogonal axes** post-Slice-6:

- `scene_mode` is set ONCE by `scene_create` at scene birth. Source: authored Scene's declared mode if any (Slice 8 YAML schema declares this); else `exploration`. It does not change during the scene's lifetime.
- `combat_active` remains the sole source of truth for "combat-tactics mode on." Only `combat_entry` and `end_combat` touch it. `scene_mode` is left alone — when combat ends mid-social-scene, the scene resumes as the social situation it was.
- The roadmap-as-originally-written line "exploration → combat auto-calls start_combat" is reinterpreted: combat starts via Scene Director's `combat_trigger`, regardless of scene_mode. `scene_mode` is metadata for SceneNarrator + Scene Director to understand the scene's nature.
- The `social` value is reserved for Slice 8 authored scenes; Slice 6 ships only `exploration` and `combat` (the latter only via `combat_entry` flipping `combat_active`, not via scene_mode mutation).

#### Build — Dialogue rename + plumbing (content rewrite is Slice 7)

Slice 6 unblocks dialogue for both NPCs and companions. The deep `NarrativeProfile` schema and the prompt rewrite land in Slice 7 — Slice 6 ships the minimum to make companion dialogue functional.

- Rename: `agents/npc_dialogue.py` → `agents/dialogue.py`. Update `models.yaml` (`npc_dialogue` → `dialogue`), `prompts/npc_dialogue/` → `prompts/dialogue/`, `turn_graph.py` (`_resolve_npc_dialogue` → `_resolve_dialogue`, node name updated), all tests.
- Provisional `DialogueEntity` TypedDict: `{name, bio, personality, disposition}`. **No `voice_traits`** — it doesn't exist on the current schema and adding a column we'll move in Slice 7 is the worst of both worlds. Voice arrives with `NarrativeProfile` in Slice 7.
- **Companion lookup fallback**: `_resolve_dialogue` calls `npc_queries.find_by_name` first; on None, falls back to `character_queries.find_companion_by_name(campaign_id, name)`. Companions speak through the same path as NPCs.
- **Context plumbing**: dialogue prompt receives `last_5_turns_in_scene: list[{player_input, dm_response}]` + matching world bible entries (key-match against existing bible keys for the named entity — no RAG until Slice 13).
- Dialogue prompt itself is lightly updated to accept a companion entity. The deep rewrite happens in Slice 7.

#### Build — DM persona foundation (`scene_narrator/v1.md` rewrite)

`prompts/scene_narrator/v1.md` rewritten with a strong DM persona: tone, pacing, style, awareness of campaign genre and current act. Provisional companion context (name, bio, personality) — replaced by full `NarrativeProfile` injection in Slice 7. Layered scene rules and pacing instrumentation come in Slice 8.

Slice 6 additions:

- `is_scene_entry: bool` context flag — when true, prompt instructs the DM to weave in the arrival moment.
- `intro_mode: bool` context flag (see Custom character onboarding) — when true, prompt instructs the DM to weave in the character's backstory hook and establish their reason to be in the world for the next few turns.
- `death_recovery: bool` context flag — when true (narrative-mode PC death just happened), prompt instructs the DM to narrate the wake-up scene with consequences.
- `dead_npcs_with_inventory` context (see Loot extensions).
- Companion entities present in scene (name, bio, personality only — depth in Slice 7).

#### Build — Inspiration mechanic

- `domain/services/inspiration.py`:
  - `grant(db, character_id, reason: str)` — idempotent (no stacking); sets `Character.has_inspiration=True`; emits `inspiration_granted` event.
  - `spend(db, character_id)` — raises `ConflictError` if not inspired; sets `False`; emits `inspiration_spent` event.
- `tools/inspiration.py`:
  - `grant_inspiration(character_id, reason)` — LLM-callable. Registered in `ALL_TOOLS` and `COMBAT_TOOLS`.
  - `spend_inspiration(character_id)` — registered in **neither** registry. Only called from request handlers, never by LLMs.
- **Granters (prompts updated)**: `scene_narrator` and `combat_resolver` both get a one-paragraph addition on when to call `grant_inspiration` — genuinely clever play, dramatic RP. Not for routine actions. `scene_director` and `dialogue` do NOT have it — Scene Director is meta (doesn't watch behavior) and NPCs/companions don't grant inspiration in 5e.
- **Spend mechanism (Slice 6 scope = non-combat skill checks)**:
  - `POST /v1/sessions/{id}/turns/{turn_id}/resolve` (shipped name) body grows `use_inspiration: bool = False`.
  - When true: handler validates `Character.has_inspiration`, calls `inspiration.spend`, sets advantage on the roll, returns the resolved check.
  - If `has_inspiration=False` and `use_inspiration=true`: 400.
- **Combat-path use_inspiration is punted to Slice 15** (frontend UI). Until Slice 15, players can spend inspiration only on non-combat skill checks via the API. Document this in the slice notes for Slice 15.
- **Companions can have/spend inspiration** — `has_inspiration` is on Character; companions are Characters. UI surfaces both PC and companion in Slice 15.
- Roll plumbing: existing `roll_d20_with_advantage` accepts the `advantage` flag — no new helper needed.

#### Build — Concentration enforcement (system)

Concentration was half-built before Slice 6 (`Character/NPC.concentration: String | None` columns; LLM-managed via `set_concentration`/`drop_concentration`/`roll_concentration_check` tools). Slice 6 makes the damage-triggered save automatic and tightens the schema.

- **Schema migration**:
  - `Character.concentration: String | None` → `JSONB | None` with shape `{spell_name: str, level: int, source_effect_id: str | None}`.
  - `NPC.concentration` same migration.
  - Monsters: add an optional `concentration` field to monster entries in `combat_state` (ephemeral, dies with combat_state). Same JSONB shape.
- **`combat/mutations.apply_damage`** — after damage settles, if target.concentration is not None:
  1. Roll CON save (DC = `max(10, damage_taken // 2)`).
  2. On fail: call `resource_service.drop_concentration` (returns the dropped record including `source_effect_id`) → call `combat_service.mutations.remove_effect(effect_id)` for the linked effect → emit `concentration_broken` event.
  3. On success: emit `concentration_check_passed` event.
- **New convenience tool `cast_concentration_spell(caster_id, spell_name, level, effect_args...)`** in `tools/combat.py` — bundles `apply_effect` + `set_concentration` (with `source_effect_id` pointing at the new effect) in one atomic call. Prevents drift between concentration record and effect. Registered in `COMBAT_TOOLS`.
- Existing `roll_concentration_check` tool stays in the registry as an escape hatch (LLM-detected non-damage trigger, manual narration override). Docstring updated to "rarely called — auto-fires on damage now."
- Existing `set_concentration` and `drop_concentration` services updated to accept/return the new JSONB shape.

#### Build — Death modes

- **`Campaign.settings.death_mode`** read at damage-resolution time (settings JSONB lives on Campaign per Slice 5; preset resolver in Slice 10).
- **New module**: `domain/services/death_mode.py::resolve_pc_death(db, session, character)` — called from `combat_service.state.end_state` (i.e., when combat ends) after checking PC death state. Death resolution happens at **combat END**, not per death-save failure.
- **Pacifist mode**: in `apply_damage`, if target is a PC and `death_mode == "pacifist"`, clamp `hp = max(1, hp)` BEFORE any 0-HP path. PC never goes unconscious, never gets a death save, never triggers massive damage. Pacifist does NOT protect companions (they follow normal death save sequence per spec). Pacifist does NOT affect NPCs/monsters.
- **Hardcore mode**: when `resolve_pc_death` fires for a PC who fully failed death saves, set `Campaign.status = "ended_dead"`, emit `campaign_ended` event. Campaign mutations frozen via middleware (see below).
- **Narrative mode (default)**: when `resolve_pc_death` fires, set PC HP=1, set `Session.pending_recovery: JSONB | None` to a `{reason, prior_events_summary}` dict, write a consequence tag to the world bible. SceneNarrator on the next turn consumes `pending_recovery` (injected into its context as `death_recovery=true`), narrates the wake-up, and the route layer clears the flag.
- **Recovery scene transition is organic** — `pending_recovery` does not set `pending_transition`. The next player action ("I look around the cell") triggers Scene Director's normal flow which can detect the new scene from the player's input. No mechanical plumbing.
- **TPK**:
  - Hardcore: PC death → `ended_dead`, regardless of companions.
  - Narrative: PC recovers per narrative rules. Dead companions stay dead. Player wakes alone with consequences (LLM-narrated).
  - Pacifist: PC never drops; TPK impossible by definition.
- **Companion death**: always follows the death save sequence regardless of mode; on full failure, `is_dead=True`, removed from combat. Story-driven revival possible. **Massive damage instant-kills companions outright** (see Combat polish).
- **Middleware**: `api/v1/middleware.py::require_active_campaign` decorator wrapped around all mutating routes (POST/PATCH/DELETE on /v1/campaigns/{cid}/\* and dependent routes). Returns 409 with code `campaign_ended_dead` if `campaign.status == "ended_dead"`. Reads stay open — the campaign is viewable as memory.

**New migrations**:

- `Session.pending_recovery: JSONB | None` (new column).
- `Campaign.status` enum extended with `ended_dead` if not already present (verify against Slice 5 migration).

#### Build — Loot enhancements (extends Slice 3)

- **Search narrative**: SceneNarrator's context builder always includes `dead_npcs_with_inventory: list[{name, inventory, currency}]` from a new query `npc_queries.list_dead_in_scene(scene_id)`. When player input is a search, LLM uses the data; otherwise ignored. No new intent class, no Scene Director extension. Authored chests/containers are out of scope (no schema for them in Slice 6); a later slice adds them.
- **Pickpocket flow**:
  - `CheckDecision` schema (in `agents/rules_lawyer.py`) grows `loot_intent: LootIntent | None` where `LootIntent = {npc_id: uuid, item_name: str}`.
  - `CheckData` TypedDict in `cairn/types.py` grows the same field.
  - RulesLawyer prompt updated: when player input is a steal/pickpocket attempt on an alive in-scene NPC, pick Sleight of Hand and emit `loot_intent`. NPC lookup via `npc_queries.find_by_name(campaign_id, name, scene_id=current_scene_id)`. (Fuzzy-match risk is the Slice 7 fix; not Slice 6's problem.)
  - Resolve-check handler: on success with `loot_intent` set, call the existing loot service to move the item. On failure, call `npc_service.set_disposition(npc_id, "hostile")` **deterministically** — no LLM judgment for this outcome. Failed pickpocket = hostile, period.
  - **No auto-combat from disposition flip.** NPC turning hostile does NOT trigger `combat_active`. The next turn's Scene Director may detect a combat trigger from the player's follow-up action (e.g., "I draw my sword") via the normal flow.
- **Currency loot**:
  - Existing `POST /v1/sessions/{id}/loot` route body extended:
    ```json
    {
      "npc_id": "uuid",
      "character_id": "uuid",
      "item_name": "string (optional)",
      "currency": { "gp": 0, "sp": 0, "cp": 0 } // optional
    }
    ```
  - Validation: exactly one of `item_name` or `currency` per request.
  - Service: new `loot_service.loot_currency(npc_id, character_id, currency)` alongside existing `loot_item`. Validates NPC has ≥ requested amounts; decrements NPC, increments Character.
  - `Currency` type already exists on Character and NPC (verified) — just plumb.
  - "Take all" UI (Slice 15) calls the route in a loop for items + once for currency.

#### Build — Custom character onboarding

- **Migration**: add `Character.created_from_premade_id: uuid | None` FK to `premade_characters.id`. Set by the appropriate creation service: premade-pick flow stamps it; custom-create flow leaves NULL.
- **Detection (no agent, no graph node)**: `narrative_context.build_dm_context(db, session_id)` checks: if `campaign.turn_count < 3` AND `active_character.created_from_premade_id IS NULL`, set `intro_mode=true` in the SceneNarrator context dict.
- **SceneNarrator prompt** gets a `{% if intro_mode %}` section: "the player is brand new to this world; weave in their backstory hook; place them deliberately; establish their reason to be here."
- Pure context-layer feature. No transition event when intro mode fades — `turn_count >= 3` silently returns false on turn 3; DM settles into normal play.

#### Fix — Combat polish

- **Massive damage instant-kill** (`apply_damage`): after damage drops HP to 0, compute `excess = damage_taken - hp_before_damage`. If `excess >= max_hp`, mark instant death — skip death save sequence entirely. Emit `massive_damage_death` event. Applies to PC (mode-gated by death_mode: pacifist clamps first so it never fires for PC in pacifist), companion (always — overrides their death save sequence), monster/NPC (no visible behavior change since they die at 0 HP anyway; event still fires for log consistency).
- **Subdue / knockout blow**: `apply_damage` tool grows `subdue: bool = False` parameter. When `subdue=True` and damage would drop target to 0:
  - HP set to 0, target marked unconscious + stable (no death saves).
  - PC/companion: `is_unconscious=True`, no death save sequence, no mode rules fire.
  - Monster/NPC: unconscious, alive, not dead.
  - Emit `combatant_knocked_out` event.
  - PHB constraint (subdue only valid for melee attacks) honored via prompt instruction in Slice 6; mechanical enforcement lands in Slice 9 (`apply_damage(subdue=True)` requires the attacker in melee range of the target).
- **Combatant cap fix**: replace `range(20)` in combat_resolver with `range(len(combat_state["combatants"]))`. One-liner.
- **Combat resolver inner-loop failure** (Slice 11 owns the full fix; Slice 6 only adds the event): wrap the resolver tool loop in `try/except`. On any exception, emit `combat_step_failed` event with `last_successful_step`, `error_class`, `error_msg`; re-raise so the route layer can return 500 + partial state in the SSE stream. No transactional wrapping in Slice 6 — Slice 11 chooses rollback vs document.

#### Routes — added, changed, removed

- **Removed**: `POST /v1/sessions/{id}/combat/start`, `POST /v1/sessions/{id}/combat/end`. Delete cold — no deprecation period (no frontend consumes them yet; Slice 15 will use the natural-language path). Drop `CombatStartRequest` and `CombatEndRequest` schemas. Tests rewritten to drive the full graph (preferred) or call `combat_service.state.start/end` directly (unit-level coverage).
- **Kept**: `GET /v1/sessions/{id}/combat` — needed by the Slice 15 combat tracker UI.
- **Changed**: `POST /v1/sessions/{id}/turns/{turn_id}/resolve` (shipped name) body grows `use_inspiration: bool = False`. Existing behavior preserved when omitted.
- **Changed**: `POST /v1/sessions/{id}/loot` body grows `currency` field; validation requires exactly one of `item_name` / `currency`.
- **Middleware**: `require_active_campaign` wrapped around all mutating routes under `/v1/campaigns/{cid}/*` (and dependent session/turn/character/npc routes). Returns 409 / `campaign_ended_dead` if frozen.

#### Schema changes (single migration revision)

One Alembic migration covers all the changes; pre-launch nuke-and-reseed is acceptable.

| Change                                                                                 | Reason                                                             |
| -------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `ALTER turns.scene_id SET NOT NULL` (after `DELETE FROM turns; DELETE FROM sessions;`) | Scene Director owns scene creation; every turn belongs to a scene. |
| `Character.concentration` String → JSONB                                               | New shape `{spell_name, level, source_effect_id}`.                 |
| `NPC.concentration` String → JSONB                                                     | Same.                                                              |
| `Session.pending_transition` JSONB nullable (new)                                      | Scene boundary detection-to-application handoff.                   |
| `Session.pending_recovery` JSONB nullable (new)                                        | Narrative-mode death recovery handoff.                             |
| `Character.created_from_premade_id` UUID FK nullable (new)                             | Custom-vs-premade detection for intro_mode.                        |
| `Campaign.status` enum verified to include `ended_dead` (extend if missing)            | Hardcore mode freeze.                                              |

#### Files added / changed (concrete map)

**New files**:

- `agents/scene_director.py` (with `run_pre` and `run_post`)
- `agents/scene_summarizer.py`
- `prompts/scene_director_pre/v1.md`
- `prompts/scene_director_post/v1.md`
- `prompts/scene_summarizer/v1.md`
- `domain/services/scene_director_context.py`
- `domain/services/time.py`
- `domain/services/death_mode.py`
- `domain/services/inspiration.py`
- `tools/inspiration.py` (grant only registered in tool registries)
- `api/v1/middleware.py` (or extend existing) — `require_active_campaign`

**Renamed**:

- `agents/npc_dialogue.py` → `agents/dialogue.py`
- `prompts/npc_dialogue/` → `prompts/dialogue/`

**Substantially modified**:

- `pipelines/turn_graph.py` — combat path inside graph; new nodes (`scene_director_pre`, `combat_entry`, `combat_terminus`, `scene_create`); routing rewrite; TurnState extended (new fields below).
- `domain/services/turns.py::prepare()` — drop the `combat_active` bypass; run graph for every turn; schedule post-response Scene Director pass alongside LoreKeeper.
- `domain/services/sessions.py::start()` — eagerly create the campaign's first Scene.
- `domain/services/rests.py` — migrate onto `time.advance_time`.
- `domain/services/combat/state.py::end_state` — call `death_mode.resolve_pc_death` for the PC at combat end.
- `domain/services/combat/mutations.py::apply_damage` — concentration auto-save, massive damage instant-kill, subdue param.
- `domain/services/resources.py` — `set_concentration`/`drop_concentration` JSONB shape.
- `agents/rules_lawyer.py` — `CheckDecision.loot_intent` field.
- `agents/scene_narrator.py` + `prompts/scene_narrator/v1.md` — DM persona rewrite, intro_mode/is_scene_entry/death_recovery/dead_npcs_with_inventory context.
- `domain/services/narrative_context.py::build_dm_context` — intro_mode detection, dead NPCs query, recovery flag injection.
- `llm/models.yaml` — entries for `scene_director_pre`, `scene_director_post`, `scene_summarizer`; rename `npc_dialogue` → `dialogue`.
- `api/v1/routes/turns.py` — schedule post-response pass after stream completes; consume new TurnState fields for routing.
- `api/v1/routes/combat.py` — delete POST routes; keep GET.
- `api/v1/schemas/combat.py` — drop CombatStartRequest, CombatEndRequest.
- `cairn/types.py` — CheckData.loot_intent, TurnState additions, ScenePreOutput, ScenePostOutput, DialogueEntity, NarrativeRecovery.
- `db/queries/npcs.py` — `list_dead_in_scene(scene_id)`.
- `db/queries/scenes.py` (likely new or extended) — scene CRUD for scene_create.
- `db/queries/characters.py` — `find_companion_by_name`.

**Tool registry** (`tools/__init__.py`):

- Add: `grant_inspiration`, `cast_concentration_spell`.
- `spend_inspiration` is intentionally **not** registered (request-handler only).
- `start_combat` / `end_combat` stay registered (still called by combat_entry and combat_resolver respectively).

**TurnState additions** (in `pipelines/turn_graph.py`):

- `scene_pre_output: ScenePreOutput | None`
- `is_scene_entry: bool`
- `combat_just_started: bool`

#### Punted from Slice 6 — destinations and what survives

This slice intentionally cut several items the original roadmap placed here. Each survives as a schema slot or integration point so the destination slice doesn't have to refactor.

| Cut item                                                                             | Destination           | What Slice 6 ships toward it                                                                                                                                           |
| ------------------------------------------------------------------------------------ | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Passive perception (silent/surfaced on scene entry)                                  | Slice 8               | `Campaign.settings.checks` shape documented (Slice 10 resolver wires defaults). `on_demand` mode already works via existing skill_check path.                          |
| Pacing nudge (`beat_count`, `tension_level`, `mood` on Scene)                        | Slice 8               | `pacing_nudge` field stays in ScenePreOutput schema; Slice 6 prompt always returns null.                                                                               |
| Reaction bus infrastructure                                                          | Reaction-engine slice | Nothing in Slice 6. **No reaction bus in v1.** Slice 9 resolves OA on zone-exit inline in `move_combatant` (auto-taken); the general reaction engine (Counterspell/Shield/interrupts) is its own dedicated slice after zones and generalizes that OA. Concentration auto-save stays a direct branch in `apply_damage`. |
| Combat-path `use_inspiration` flag                                                   | Slice 15 (UI)         | Service + tool + non-combat skill check path ship now. UI surfaces the toggle for combat.                                                                              |
| Scene transition pacing (tension-history "after 3 combat scenes push toward social") | Slice 8               | Depends on `tension_level` which is Slice 8. No Slice 6 work.                                                                                                          |
| `NPC.find_by_name` ranked match + scene-aware filter                                 | Slice 7               | Needs the new profile schema to be meaningful.                                                                                                                         |
| `NPC.disposition` → world bible on change                                            | Slice 7               | Same — slated with profile work.                                                                                                                                       |
| `Character.classes` single-class validator                                           | Lives in code-comment | Per Slice 5 deferred-deviation note: there's no API path to submit more than one class, so a runtime validator would be dead code.                                     |
| `tension_delta` and `mood` outputs on post-response pass                             | Slice 8               | Schema slot reserved when columns land.                                                                                                                                |

#### Verify

1. Player says "I attack the guard" on a turn with `combat_active=false`: Scene Director's pre-input pass returns `combat_trigger`, combat_entry inits state, route layer streams combat_resolver. No client REST call needed.
2. Player says "I head to the tavern": pre-input pass sets `Session.pending_transition`. On the next turn, scene_create runs — old scene gets a summary via scene_summarizer, new Scene row created, current Turn.scene_id stamps the new scene, SceneNarrator narrates the arrival with `is_scene_entry=true`.
3. DM narrates "...you walk out and head home" at the end of a turn: post-response pass sets `pending_transition`. Next turn applies it (same flow as #2).
4. Player enters an unauthored location (no authored Scene): scene_create writes a thin Scene row; SceneNarrator falls back to Location.description + nearby NPCs + act premise.
5. Concentrating wizard takes damage in combat: `apply_damage` auto-rolls CON save at DC `max(10, dmg//2)`. On fail, concentration drops + linked effect removed + `concentration_broken` event emitted. No LLM call required for the save.
6. Monster casts Hold Person, then takes damage: monster's combat_state entry has `concentration`; auto-save fires; on fail, effect removed.
7. DM grants inspiration during a roleplay moment: `grant_inspiration` tool call → `Character.has_inspiration=True`. Player POSTs to the resolve endpoint with `use_inspiration=true` → spend service flips flag false, roll uses advantage.
8. Pacifist-mode PC takes 1000 damage at HP=5: HP clamped to 1; no death save, no events for instant death.
9. Hardcore-mode PC takes lethal damage and fails death saves: combat ends, `resolve_pc_death` sets `Campaign.status="ended_dead"`, `campaign_ended` event emitted. Next mutation request returns 409 / `campaign_ended_dead`. GET routes still work.
10. Narrative-mode PC death: HP=1 at combat end, `pending_recovery` set, world bible consequence written. Next turn's SceneNarrator narrates the wake-up.
11. Subdue attack on enemy with melee weapon: enemy unconscious + stable + alive; `combatant_knocked_out` event.
12. Massive damage instant-kill: PC at HP=5 takes 60 damage (max_hp=50). HP=0, `excess=55 >= max_hp=50`, instant death, no save sequence (modulo death_mode in pacifist where clamp fires first).
13. Failed pickpocket on alive NPC: the resolve handler sets NPC.disposition=hostile deterministically; no auto-combat.
14. Currency loot: `POST /loot` with `{"currency": {"gp": 5}}` moves 5 gp from NPC to character; insufficient balance returns 400.
15. New campaign + custom character: first 3 turns render with `intro_mode=true` (SceneNarrator weaves in backstory); turn 4+ resumes normal play silently.
16. Companion speaks via dialogue: player addresses companion by name, IntentRouter routes to npc_dialogue intent, \_resolve_dialogue finds companion via fallback, dialogue agent responds.
17. Combat-resolver tool failure mid-loop: `combat_step_failed` event emitted; 500 returned with partial state in SSE stream.
18. Long rest happens, post-response pass tries to also advance time: `time_advanced` event already in `Turn.events` from rest service → post-response skips, logs.
19. Time advancement: Scene Director only sets `time_advance_hours > 0` when also setting `scene_transition_push`. Mid-scene narration does not advance time.
20. `POST /v1/sessions/{id}/combat/start` returns 404 (route deleted); `GET /v1/sessions/{id}/combat` still returns combat state for the Slice 15 tracker.

---

### Slice 7 — NPC + companion narrative depth

_Depends on: Slice 5 (schema, scene model), Slice 6 (dialogue rename, post-response pass slot)._

> **Reimagined post-6 (grilled 2026-07).** Supersedes the original Slice 7. Decisions locked in the "Decisions locked" block below.
>
> **Grill 2 (2026-07) — character scope + recruitment.** A second grill widened this slice with three revisions, captured in the new "Character scope", "Seed structure", and "Recruitment" sections below. They **supersede** any conflicting phrasing above/below: (1) **`tier` = plot importance, decoupled from authoring depth** — a background NPC can still be richly written; (2) **world- vs scenario-scoped characters** (the Skyrim model), with a nested seed folder tree; (3) a **recruitment flow** — companions are earned in-character, not auto-joined.

Today an NPC carries thin narrative columns (`bio`, `personality`, `voice_traits`, `disposition`) and a companion is a `Character` with `is_companion=True` and an empty `companion_meta`. This slice gives every NPC and companion a deep, prose-driven **profile** — who they are, how they talk, their history, goals, prejudices, and secrets — and rewires the dialogue/narrator/ally agents to roleplay from that profile instead of a stat block. **This is the foundation slice for narrative quality.** Without depth here, dialogue plays thin, companions feel like followers, and scenes have nothing to riff on.

The mental model: every NPC and every companion is a **real person**. Authored ones are detailed, multi-section documents; builder-generated ones come out lighter but follow the same shape. **Authoring depth and narrative tier are separate dials** — a starting-tavern bartender the player talks to constantly deserves rich prose, and is still `background`.

#### Character scope — world vs scenario (locked, grill 2)

Characters exist at two authoring scopes, mirroring **World → Scenario (`CampaignTemplate`) → Campaign → Session**. The mental model is Skyrim: the *world* is the whole setting and its canon; a *scenario* is one adventure and where it starts (Riften vs Winterhold); the player navigates locations, meeting the scenario's local cast, while world-famous figures (Ulfric, Alduin) exist at world scope and appear only where they're connected.

- **Scenario cast** — the local faces of one adventure. Cloned into the campaign's `npcs` rows **at creation** (always present; the player will very likely interact). Mostly `recurring` / `background`, but a scenario may author its **own** `major` (this adventure's villain).
- **World cast** — canon figures authored once under the world. **Not** auto-instantiated — they exist as *known entities* (you can hear about Alduin through lore without meeting him). They enter a campaign only when **connected**:
  - **Explicit** — a scenario's `template.md` lists `world_characters: [<key>...]`; those clone into the campaign at creation.
  - **Lazy on-encounter** — if the player reaches a place/situation tied to a world figure the scenario didn't pre-declare, the engine instantiates them from the **authored world blueprint** (checked before falling back to builder generation — see the builder section).
- **Tier × scope are orthogonal** — a `major` can be world- or scenario-scoped; a world figure can be `recurring`.
- **Runtime stays campaign-scoped and isolated** — a world figure is *cloned* into your campaign's `npcs` rows, so your version can diverge (die, turn hostile) without touching any other campaign. World **lore** stays shared read-only (it's immutable reference); world **characters** clone (they're mutable). This preserves the campaign-isolation property the world-bible namespace already guarantees.

#### Seed structure — nested to match the hierarchy (locked, grill 2)

The old flat layout (`seed/worlds/` and `seed/templates/` as siblings) hid the hierarchy. New tree:

```
seed/worlds/<world>/
  world.md                     world summary + calendar
  lore/*.md                    shared read-only canon (unchanged)
  characters/*.yaml            WORLD cast blueprints (recruitable ones flagged)
  campaigns/<scenario>/        (was seed/templates/<scenario>/)
    template.md                premise, acts, + world_characters: [keys] connections
    characters/*.yaml          SCENARIO cast (was npcs.yaml)
    locations.yaml
    premade_characters/*.md     player-pickable PCs (unchanged shape)
```

- `templates/<scenario>/` moves under `worlds/<world>/campaigns/<scenario>/`. The seed loader + `campaigns.create` clone paths follow.
- **No `companions/` folder.** A predefined companion is a cast member (world or scenario) flagged `recruitable: true` carrying a `companion_sheet` — recruitability is a *property*, not a location (see Recruitment). This unifies predefined and dynamic companions.
- World-cast characters are seeded as **world-scoped blueprints** (analogous to `premade_characters` being template-scoped blueprints); connected/encountered ones clone into campaign `npcs` rows.

#### Recruitment — earned in-character (locked, grill 2)

A companion is a `Character(is_companion=True)` with a full playable sheet (`ally_ai` actually spends their abilities). An NPC is a lighter `npcs` row. Recruitment bridges them, serving **both** predefined (authored) and dynamic (any bonded `recurring` NPC) recruits through **one path**:

- **Spine — convert on recruit.** An unrecruited companion lives in the world as a normal **NPC** (met, talked to, promoted via the machinery below). Recruiting **converts NPC → `Character(is_companion=True)`**:
  - **Predefined** — the cast blueprint carries an authored `companion_sheet`; conversion copies it + inits `companion_meta` (approval 0).
  - **Dynamic** — a builder "stat-up" pass derives a playable sheet from the NPC's stats/profile (reuses the Phase-4 builder, pointed at sheet-building).
  - The source `npcs` row is retired once converted.
- **Adjudication — a dedicated `recruiter` prompt, not a toggle.** When a recruitment bid is detected, the candidate weighs it against their `narrative_profile` (goals, prejudices, personality) + current disposition/approval + recent history + what the player offered/proved, and returns a structured decision: **accept** / **refuse** / **conditional**. No hard numeric gate — a hostile candidate won't come; a warming one may set terms. `agents/recruiter.py` + `prompts/recruiter/v1.md` + `models.yaml` entry.
  - **accept** → conversion fires; approval starts at 0.
  - **refuse** → stays an NPC; won't be badgered; re-attemptable if circumstances change.
  - **conditional** → the ask is recorded (lightweight — an `NPC.recruitment_condition` string) and re-opens recruitment once satisfied.
- **Party cap** — soft `MAX_ACTIVE_COMPANIONS = 4`; recruiting past it requires dismissing someone (narrated, not a hard wall).
- **Dismissal** — supported: `Character(is_companion=True)` → back to an NPC at the current location, remembering the parting. **Auto-leave** on betrayal / rock-bottom approval is flagged, **not** built in v1.

#### Storage model — hybrid, not a monolith (locked)

The rich prose lives in one JSONB blob; the mutable/queryable bits stay as columns so hot-path reads and frequent mutations don't rewrite the whole blob.

- **`narrative_profile: JSONB`** on both `NPC` and `Character` — holds only prose-for-prompts fields (never filtered/queried). The existing `bio` / `personality` / `voice_traits` columns are **migrated into it and dropped**.
- **`NPC.disposition`** — **stays a column.** Read on the hot path (Scene Director's `npcs_present`, combat targeting). Companions have no `disposition` (they're party members; their standing is approval).
- **`NPC.tier: enum(major|recurring|background)`** — **new column.** Drives promotion + builder behavior; queryable.
- **`Character.companion_meta: JSONB`** — **stays its own column** (already exists). Approval/mood mutate frequently and gate behavior; nesting them in the profile blob would force a full-blob rewrite on every +5 tick. This deliberately deviates from the original "companion_meta nested inside profile" plan.

`NarrativeProfile` JSONB shape (same for premade, authored, and generated):

```yaml
name: str
race: str
age: int
profession: str
physical: str            # multi-paragraph: build, features, posture, scars, dress
personality: str         # observed behaviors, not labels ("watches before he speaks")
voice:
  accent: str
  pace: str
  vocabulary: str
  speech_quirks: list[str]
backstory: str           # multi-page prose: 5+ years of past, key events, losses
goals: { immediate: str, midterm: str, life: str }
prejudices: list[str]    # specific, justified — the moral leanings the reflection pass reads
relationships: list[{ name, relation, status, notes }]
private_facts: list[str] # known but not volunteered. NOT mechanically gated; LLM judges.
```

`companion_meta` column shape (for `is_companion=True`):

```yaml
approval: int            # -100..100, starts at 0
mood: str                # derived (see derive_mood); content|happy|upset|scared|angry|inspired|dejected
personal_goal: str       # what this companion wants from the journey
secret: str | None
approval_log: list[{ turn_id, delta, reason, total }]  # last 20 entries
```

**Schema validation at write time:** required top-level profile fields are `name`, `personality`, `voice`. Background NPCs may otherwise be incomplete; authored/recurring should be full.

#### Build — companion approval subsystem (LLM-driven, post-turn reflection)

Approval is **LLM-driven only in v1 — no hardcoded auto-triggers, no reaction bus** (the bus is combat infra that lands later; wiring deterministic triggers now would drag it in early and break slice isolation).

- **Judged in-character.** The reflection pass weighs each action against *that companion's own* `personality` + `prejudices` + `personal_goal` — not an objective morality. A cruel companion approves of cruelty; a kind one recoils at the same act. This is the whole reason to go LLM-driven — a rule table can't do "Minthara approves of burning the village" without per-companion rules.
- **Where it runs — post-turn reflection pass (locked).** The streaming narrator/dialogue agents never call approval tools mid-stream. Instead a fire-and-forget pass runs after each turn completes, in the **same slot as LoreKeeper + Scene Director post-response** (`turns.service` schedules it via `asyncio.create_task`). Uniform across narrative *and* combat turns (it reads the turn's events either way). Only fires when ≥1 companion is present.
  - `agents/companion_reflector.py` + `prompts/companion_reflector/v1.md` (fast/mid tier) + `llm/models.yaml` entry.
  - **Structured output, not a tool loop** (cheaper/deterministic): input = `{player_input, dm_response, turn.events, companions_present: [{id, name, personality, prejudices, personal_goal, approval, mood}]}`; output = `list[{companion_id, delta, reason}]`.
  - The route/service applies each delta via the service below. No LLM-callable `adjust_approval` tool in v1 (an inline DM-grant tool can be added later if wanted).
  - *Optimization note:* `companion_reflector` and `lore_keeper` both re-read the completed turn — they may be merged into one post-turn extraction call later if prod cost demands; kept separate now for single-responsibility + eval-ability.
- **`services/companions.py`:**
  - `adjust_approval(db, *, character_id, delta, reason, turn_id) -> {approval, mood, crossed_thresholds}` — clamps to [-100, 100], appends to `approval_log` (trim to last 20), recomputes mood via `derive_mood`.
  - `derive_mood(approval, recent_deltas) -> mood` — deterministic: approval band sets the baseline mood; a recent large-magnitude delta transiently overrides (e.g. a −25 hit → `angry`/`dejected` regardless of band).
- **Magnitude guidance (in the reflector prompt):** minor beats ±2–5; major moral moments ±15–30. Total clamps to [-100, 100].
- **Player-facing surfacing (locked; contradiction resolved 2026-07):** the player sees **vague bands only** ("cold" / "warming up" / "loyal") — **the raw −100..100 integer is never surfaced to the player** (it's meta-info; a DM shows behavior + consequence, not a meter — consistent with *think-like-a-D&D-player* + *engine-doesn't-nanny*). The band **and the `approval_log`** are what render in the companion profile drawer's **Approval** section: the log as colored lines — **green for delta > 0, red for delta < 0** — each with its reason string ("Burned the village down"), but **without the numeric deltas or running total**. The integer + deltas stay server-side (drive `derive_mood`, band thresholds); the API may return them but the frontend does not display them. This is a Slice-7 API/data guarantee; the frontend slice just renders band + reason strings.

#### Build — NPC tier + promotion

- **Tiers = plot importance, not authoring depth (grill 2):** `major` = the story turns on them (antagonist, key patron, arc-bearing ally) — authored-only, the builder never emits one; `recurring` = a stable returning presence with a stake; `background` = texture (bartender, guard, passerby). Depth is a separate dial — a `background` NPC can still be richly authored.
- **Auto-promotion (locked):** a `background` NPC promotes to `recurring` automatically once the player has genuinely engaged it — **≥3 dialogue exchanges** with that NPC. Promotion fires a *one-time* builder deepen-pass that extends the existing profile in place (same name/facts, fleshed out — continuity preserved).
- Promotion counter: track dialogue-exchange count per NPC (small counter column or derive from turn/scene history — decide during build; lean a `dialogue_exchange_count` column on NPC for cheap reads).

#### Build — NPC builder agent (lazy, tier-to-value cost)

`agents/npc_builder.py` + `prompts/npc_builder/v1.md`. **The builder never generates `major`** — that's authored-only ("authoring is the foundation").

- **Lazy / on-demand firing (locked):** generate only when the player actually addresses an NPC who doesn't exist. `_resolve_dialogue` calls `npc_queries.find_by_name`; on miss (and no companion match), the dialogue path **first checks the authored world-cast blueprints** (grill 2) — if the name matches a known world figure, instantiate them from the blueprint (preserving canon); otherwise the builder creates a `background` NPC — then answers. Only NPCs that get talked to are ever paid for.
- **Model tiered to value (locked):** `background` generation uses the **fast/cheap tier** (~1–2s, barely noticeable before dialogue streams). The **promotion-to-`recurring`** deepen-pass uses a **stronger tier** (rarer, earns the spend). Drops the original "always frontier builder." (Locally both map to Qwen via `models.yaml`, so dev is free.)
- **Authored-scene NPCs are the exception:** NPCs a scene explicitly declares (Slice 8 scene schema) are built when the scene is created — the author declared they matter.
- **Canon-consistency at build time (pre-RAG):** inject `{location context, factions present, existing NPCs in the area, always_on lore chunks, key-matched world bible entries for referenced names}` so a generated NPC doesn't contradict canon. RAG-quality retrieval swaps in when it lands (Slice 13); key-match is the v1 mechanism.

```
In:  location (culture, factions), role in scene, tier, existing area NPCs, atmosphere, canon context
Out: NarrativeProfile scaled to tier
     - background ≈ tight paragraph (personality + a few facts, required fields only)
     - recurring  ≈ several paragraphs (real backstory, goals, 1-2 relationships)
     - major = authored only (builder never emits this)
Persist: LoreKeeper writes the new NPC to the world bible; re-encounters retrievable (RAG, Slice 13)
```

#### Build — dialogue agent rewrite

`prompts/dialogue/v1.md` rewritten to consume `NarrativeProfile`. No mechanical fact-gating — the LLM holds the facts in prose and reveals them through behavior. Prompt rules:

```
The character below is a real person. Roleplay them.
- Stay in character. Behavior is your output.
- Do not list facts. Reveal through behavior, partial answers, deflections, silences.
- Surface private_facts only when earned in the scene (trust, persistence, leverage,
  vulnerability). Your judgment — most scenes don't warrant disclosure.
- Never invent facts not in the profile. If asked something you don't know, say so or evade
  in character.
- Pursue your goals. Push your own conversation agenda; ask back; deflect.
- Honor your prejudices.
- Companion-specific: your approval and mood color every reaction. Low approval → curt,
  withdrawn, sarcastic. High approval → open, protective, supportive.
```

Receives: full profile of the speaking entity + active PC's profile for context + last N turns in the current scene + key-matched world bible entries for the entity (no RAG until Slice 13). Companion lookup fallback already exists (Slice 6: `find_by_name` → `find_companion_by_name`).

#### Build — scene_narrator + ally_ai integration

- `scene_narrator/v1.md` — receives profiles of all NPCs and companions in scene. Drops 1–2 sentence companion reactions in narrative turns when their approval/mood/personal_goal/prejudices are touched. Sparingly, meaningfully.
- `ally_ai/v1.md` — receives the companion's full profile + current approval/mood. Behavior emerges from profile (low approval → hesitates, refuses risky support, sarcastic; high approval → takes risks for the PC), never `if approval < 0: refuse`.

#### Build — content authoring (discipline; grill 2)

Author at real depth — detailed, multi-section, not two tidy paragraphs. Depth is the *authoring* bar; **tier is plot importance** (a richly-written bartender is still `background`).

- **World cast** — `seed/worlds/cairn_v1/characters/*.yaml`: the setting's canon figures at world scope (a ruler, a legend, a known villain). These carry the `major` figures of the world; some are `recruitable`.
- **World lore** — deepen `seed/worlds/cairn_v1/lore/*.md` so the world is rich enough for world characters to be *of* somewhere.
- **Scenario cast** — `seed/worlds/cairn_v1/campaigns/tavern_v1/characters/*.yaml` (was `npcs.yaml`): Old Grim authored richly but tiered **`background`/`recurring`** (a tavernkeeper, not a plot pillar); the scenario's own `major` (if any) is this adventure's antagonist, not the barman.
- **Companions** — one or two recruitable companions in the scenario cast (flagged `recruitable`, carrying a `companion_sheet`) — e.g. a sellsword at the bar the player can earn.
- `template.md` declares `world_characters: [<key>...]` for the world figures this scenario connects.

#### Fix

- **`NPC.find_by_name` fuzzy-match risk** — currently first alphabetical substring match. Replace with ranked match + scene-aware filter (current scene's NPCs first).
- **`NPC.disposition` → world bible on change** — captured via LoreKeeper ("old_grim disposition: neutral → hostile after party refused payment").

#### Schema changes (single migration)

| Change | Reason |
| --- | --- |
| `NPC.narrative_profile` JSONB (new); drop `NPC.bio`, `NPC.personality`, `NPC.voice_traits` | Prose moves into the blob; migrate existing values in. |
| `NPC.tier` enum `major\|recurring\|background` (new, default `background`, server_default) | Promotion + builder behavior. |
| `NPC.dialogue_exchange_count` int (new, default 0) | Cheap promotion trigger. |
| `Character.narrative_profile` JSONB (new); drop `Character.bio`, `Character.personality`, `Character.voice_traits` | Same, for companions. |
| `Character.companion_meta` — no change (already exists) | Approval/mood/goal/secret/log live here. |
| `NPC.disposition` — no change (stays a column) | Hot-path read. |
| **`NPC.recruitable` bool (new, default false)** (grill 2) | Predefined companions set it; any `recurring` NPC is dynamically recruitable. |
| **`NPC.companion_sheet` JSONB \| null (new)** (grill 2) | Authored playable sheet for predefined companions; null → builder stats up dynamic recruits. |
| **`NPC.recruitment_condition` str \| null (new)** (grill 2) | Tracks a `conditional` recruiter outcome; re-opens recruitment when met. |
| **World-cast blueprint store (new)** (grill 2) | World characters seeded as world-scoped blueprints (like `premade_characters` are template-scoped); connected/encountered ones clone into campaign `npcs`. Table shape finalized at build. |

Pre-launch nuke-and-reseed acceptable (no production data). Grill-2 columns fold into the **same single migration**.

#### Files added / changed

- **New:** `agents/npc_builder.py`, `prompts/npc_builder/v1.md`, `agents/companion_reflector.py`, `prompts/companion_reflector/v1.md`, `domain/services/companions.py`, `domain/services/narrative_profile.py` (profile→prompt formatter). Extend `db/queries/characters.py` for companion-meta (no separate `companions.py`).
- **New (grill 2):** `agents/recruiter.py` + `prompts/recruiter/v1.md` + `models.yaml` entry (recruitment adjudication); `domain/services/recruitment.py` (NPC→Character conversion, dismissal, party cap); world-cast seeding + blueprint store + connection/lazy-instantiation logic in `domain/services/campaigns.py` + `db/queries`.
- **Changed:** `db/models/npc.py`, `db/models/character.py` (profile/tier/counter + recruit columns); `db/queries/npcs.py` (`find_by_name` ranked + scene-aware, tier/promotion + world-cast lookup helpers); `agents/dialogue.py` + `prompts/dialogue/v1.md`; `agents/scene_narrator.py` + `prompts/scene_narrator/v1.md`; `agents/combat_ai.py` + `prompts/ally_ai/v1.md`; `domain/services/turns.py` (schedule `companion_reflector`); `domain/services/narrative_context.py` + `scene_director_context.py` (inject profiles); `agents/lore_keeper.py` (disposition-change entries); `llm/models.yaml` (`npc_builder`, `companion_reflector`, `recruiter`); `cairn/types.py` (`NarrativeProfile`, `CompanionMeta`, `ApprovalDelta`, `NpcTier`).
- **Seed restructure (grill 2):** `seed/templates/<scenario>/` → `seed/worlds/<world>/campaigns/<scenario>/`; `npcs.yaml` → `characters/`; new `seed/worlds/<world>/characters/`; loader in `cli/seed.py` + clone paths in `domain/services/campaigns.py` follow.
- **Tool registry:** no new LLM-callable tools (approval is service-applied from reflector output; recruitment is a resolver acting on the `recruiter` decision).

#### Decisions locked (grilled 2026-07)

1. **Storage** — hybrid: `narrative_profile` JSONB for prose; `disposition`, `tier`, `companion_meta` stay columns. (Not the original monolith.)
2. **Approval mechanism** — LLM-driven only; **no reaction bus / no hardcoded auto-triggers in v1**; judged in-character against the companion's own values.
3. **Approval placement** — fire-and-forget **post-turn reflection pass** (`companion_reflector`), structured output, uniform across narrative + combat, fires only when companions present. No inline approval tool in v1.
4. **Magnitude** — ±2–5 minor, ±15–30 major; clamp [-100, 100].
5. **Surfacing** — vague bands to the player; green/red `approval_log` reason lines in the companion drawer **without numeric deltas or the running total** — the raw integer never reaches the player (see the resolved-contradiction paragraph above; a stale "raw number in the drawer" phrasing here was corrected 2026-07).
6. **Tiers** — **tier = plot importance, not authoring depth** (grill 2); auto-promote background→recurring at **≥3 dialogue exchanges**; builder caps at `recurring`; `major` authored-only.
7. **Builder** — **lazy on-demand**; cheap/fast model for `background`, stronger model only on promotion; canon context injected at build time (key-match pre-RAG); on a name miss, **authored world-cast blueprint is checked before generation** (grill 2).
8. **Approval scope** — PC↔companion only in v1; inter-companion matrix = v2.
9. **Character scope (grill 2)** — world- vs scenario-scoped cast (Skyrim model); scenario cast clones at creation, world cast clones on explicit connection or lazy encounter; runtime campaign-scoped + isolated; tier × scope orthogonal.
10. **Seed structure (grill 2)** — nested `worlds/<world>/campaigns/<scenario>/`; `npcs.yaml` → `characters/`; no `companions/` folder (recruitability is a property).
11. **Recruitment (grill 2)** — unrecruited companions are NPCs; recruiting converts NPC→`Character`; predefined ship a `companion_sheet`, dynamic recruits are statted-up by the builder; adjudicated by a dedicated `recruiter` prompt (accept/refuse/conditional, no hard gate); conditions tracked; party soft-cap 4; dismissal supported; auto-leave deferred.

#### Verify

- Authored Old Grim behaves consistently: refuses to volunteer about Maren on first ask, may share after earned trust within the scene; speech matches his voice profile; reacts to mage PCs with measured distrust.
- One NPC + a quiet PC still produces 3–5 turns of natural conversation — the NPC pushes an agenda, asks back, deflects.
- Player addresses an unscripted "bartender": builder lazily creates a `background` NPC (fast tier), dialogue answers; NPC persists; return next session, it remembers.
- Same NPC after ≥3 exchanges is promoted to `recurring`; a deepen-pass (stronger tier) extends the profile without changing established facts.
- A cruel companion's approval rises on a ruthless act; a kind companion's falls on the same act — both via the post-turn reflection pass, both logged with reasons.
- Companion at approval −40 in combat refuses to spend a daily ability on the PC; at +60 volunteers it (ally_ai reads profile + approval, no hardcoded threshold).
- Approval drawer shows the last 20 changes, green/red, each with a reason; the player never sees a raw number elsewhere.
- No dialogue response ever lists facts as bullets or dumps exposition.
- **(grill 2) Scope:** a scenario clones its local cast at creation; a connected world figure appears; an unconnected world figure is only referenced in lore until the player reaches them, then instantiates from the authored blueprint (not a fresh generation).
- **(grill 2) Recruitment:** asking a candidate to join runs the `recruiter` adjudication — a low-approval/hostile candidate refuses in character; a warming one sets a condition; meeting it and asking again yields accept → the NPC converts to a `Character(is_companion=True)` and joins the party. A dismissed companion becomes an NPC again. Recruiting a plain `recurring` NPC (dynamic) stats them up into a playable sheet.

---

### Slice 8 — Scene depth + pacing

_Depends on: Slice 5 (Scene model), Slice 6 (Scene Director, DM persona), Slice 7 (rich NPCs to populate scenes)._

> **Reimagined post-6 (grilled 2026-07).** Supersedes the original Slice 8. State is written through the seams that already exist — the skill-check resolver and the two Scene Director structured-output passes — with **no mid-stream tools**. Decisions locked in the block below.

A scene is a **situation**, not a description. This slice makes scenes feel like real D&D moments — a single room can hold 30 turns of play without rushing, because the scene has layers, NPCs have agendas, and the SceneNarrator paces with discipline.

**The problem this solves:** LLMs default to info-dumping and advancing plot on every turn. Out of the box, "I look around the room" gets one paragraph that resolves the scene. Real DMs withhold, ask back, let NPCs push, drop character moments, track what's been revealed. This slice builds the scaffolding for all five.

**Build (authored scene schema):**

```yaml
scene:
  id: tavern_back_room
  location_id: tavern_back_room
  scene_mode: social # exploration | combat | social
  safety_level: safe # safe | risky | hostile
  time_of_day: "late evening"
  atmosphere: |
    Multi-paragraph: lighting, smells, sounds, temperature, mood,
    what's worn or aging in the space, what's pristine, what's recent.
    The sensory entry into the scene before any specific detail.

  npcs_present:
    - npc: old_grim
      doing: "polishing the same glass he's been polishing for ten minutes"
      attentive_to: ["the door", "footsteps overhead"]
    - npc: hooded_man
      doing: "nursing a single ale, hood up, hasn't turned"
      attentive_to: ["the door"]

  surface_details: # visible to anyone who enters the room
    - "A locked iron chest under the writing desk"
    - "A faded war banner on the back wall — three crows on a black field,
      the Iron Vow"
    - "A row of pewter mugs above the bar, one missing — its hook bare"
    - ...

  hidden: # require a check; not described unless surfaced
    - check: investigation
      dc: 14
      reveals: "The writing desk has a false drawer along the left rail"
    - check: perception
      dc: 16
      reveals: "Faint footprints in the dust lead from the desk to the
        war banner — recent, in the last day"
    - check: arcana
      dc: 18
      reveals: "The pewter mug missing from the rack has been used as a
        focus — there's residual abjuration magic on the hook"

  secrets: # require an unlock condition (not just a check)
    - unlocked_by: false_drawer_found
      content: "Behind the false drawer: a sealed letter, addressed to
        Maren, dated three years ago, never sent. Reading it
        reveals [Edrik's death account in Grim's hand]."
    - unlocked_by: ["banner_searched", "perception_16_passed"]
      content: "A coded message tucked into the banner's binding —
        meaningful only if the party has Captain Vell's seal
        from Act 1."

  threads_in_air: # what's tense or unresolved as the party enters
    - "The hooded man arrived an hour ago. Ordered one ale. Hasn't spoken."
    - "Grim is uneasy about the hooded man but won't act first."
    - "Tomas the smith is late tonight — first time in months."

  hooks_out: # where this scene can lead
    - hook: hooded_man_intervention
      to: act_1_main_quest
    - hook: locked_chest_opened
      to: side_thread_vineyard_deed
    - hook: letter_read
      to: act_2_temple_lead

  npc_agendas_in_scene: # what each NPC is trying to do RIGHT NOW
    old_grim: "Keep an eye on the hooded man. Pretend he isn't worried.
      Get the party out before midnight."
    hooded_man: "Wait for his contact. Leave if anyone gets too close."
```

This is illustrative. Real authored scenes are bigger — atmosphere is many paragraphs, every NPC has a current beat, threads are richer, hooks branch deeper. **Authoring discipline is the contract.** The authored `npcs_present` + `npc_agendas_in_scene` are parsed and **merged** into the runtime `npcs_present` shape (`{npc_id, doing, attentive_to, agenda}`) at scene birth.

**Build (scene runtime state + storage):**

Hybrid storage on the `Scene` table — same pattern as Slice 7's NPC profile (hot/queryable fields as columns, structured payloads as JSONB):

```python
# Authored content — JSONB, parsed from the scene YAML, read-mostly:
authored: JSONB              # atmosphere, surface_details, hidden[],
                             # secrets[], threads_in_air[], hooks_out[]

# Runtime state — columns (hot-path, queryable):
beat_count: int              # default 0 — mechanical +1 per turn, no LLM
tension_level: int           # default 0, range 0-10
mood: SceneMood              # quiet | charged | hostile | intimate (default quiet)
last_revelation_at_turn: int # nullable — turn index of the last new discovery

# Runtime lists — JSONB (mutated per turn, never queried by value):
discovered_facts: JSONB      # list[str], default [] — the party's single
                             # source of truth for "what is known"
unresolved_threads: JSONB    # list[str], default []
npcs_present: JSONB          # list[{npc_id, doing, attentive_to, agenda}]
scene_progress_summary: text # nullable — mid-scene compression (below)
```

**How state is written — no mid-stream tools.** The SceneNarrator only *reads* state and narrates; it never mutates. Writes flow through seams that already exist:

| State | Written by | When |
| --- | --- | --- |
| `beat_count` | mechanical `+1` in the turn service | every turn in the scene |
| `discovered_facts` — check-gated `hidden` reveal | the **skill-check resolver** (runs before streaming) | the moment the check passes |
| `discovered_facts` — free-form (noticed without a roll) | **Scene Director post-pass** structured output | after the turn |
| `tension_level`, `mood` | **Scene Director post-pass** (`_PostDecision` gains `tension_delta` + `mood`) | after the turn |
| `unresolved_threads` add/resolve | **Scene Director post-pass** | after the turn |
| `npcs_present` mutations (NPC leaves/arrives, agenda shifts) | **Scene Director post-pass** | after the turn |
| `pacing_nudge` → SceneNarrator | **Scene Director pre-pass** (`_PreDecision.pacing_nudge`, already stubbed) | before streaming |

Free-form discoveries and tension/mood land one turn later (written after the turn, visible next turn) — imperceptible for pacing/memory. Check-gated discoveries are **not** delayed (the resolver writes them before narration). All writes are service-applied via `db/queries/scenes.py` helpers called from the resolver/post-pass — **not** LLM-callable tools.

**Scene-level NPC presence.** `npcs_present` is the subset of the location roster actually in *this* scene, plus each NPC's in-the-moment state (`doing`, `attentive_to`, in-scene `agenda`). Seeded from the authored YAML, or from the scene_builder, or — for a thin/unauthored scene — from `npc_queries.list_by_location`. Identity and depth of each NPC still come from Slice 7 (`narrative_profile`, `tier`, `find_by_name`); presence only references NPCs by id and layers situational state on top. **This closes the orphaned Slice 6 forward-reference** — scene-level presence is a Slice 8 concern, not Slice 7 (which kept NPCs at the location level).

**Narrator context assembly (leak-proof).** `scene_director_context.py` splits authored content into three buckets before injecting into the SceneNarrator:

- **Known** (`discovered_facts`, `atmosphere`, `surface_details`, present NPCs + agendas) → injected in full; narrate freely.
- **Hidden** → injected as a **stub only** — location + check hint ("something discoverable at the writing desk, Investigation"), **never the reveal text**. Lets the narrator foreshadow toward a check without being able to spoil it.
- **Secrets** → **not injected at all** until their unlock condition is in `discovered_facts`. The narrator cannot leak data it was never given.

When a check passes, the resolver moves that hidden detail's full reveal text into the known bucket and the narrator describes the discovery moment.

**Build (SceneNarrator pacing rewrite):**

`scene_narrator/v1.md` gets an explicit pacing section with hard rules:

```
PACING RULES:
- Reveal information in layers. First entry to a scene: atmosphere
  and at most 2-3 specific details from surface_details. Never the
  full list.
- End every response on an implicit or explicit "what do you do?" —
  the next move belongs to the player.
- If the player input is broad ("I look around"), respond atmospherically.
  Surface specific details only when they probe a specific feature.
- Hidden details MUST NOT appear in narrative unless the corresponding
  check has been passed (they only reach you once surfaced into
  discovered_facts — you are never given un-surfaced reveal text).
- Secrets MUST NOT appear unless their unlock condition is in
  discovered_facts (you are never given locked secret content).

WITHHOLDING:
- Use discovered_facts as your single source of truth for what the party
  knows. Do not describe what they have not yet engaged with or perceived.

NPC PRESENCE:
- NPCs in scene have an agenda (npcs_present). They push their own
  interest. They ask questions back. They deflect on sensitive topics.
- A scene with one NPC and a quiet PC should still produce 3-5 turns
  of natural conversation before resolution.

COMPANION PRESENCE:
- Companions react in 1-2 sentences when their approval/mood/
  personal_goal/prejudices are touched by the moment. Not every turn.
  Sparingly. Through behavior, not exposition.

WHAT NOT TO DO:
- Do not advance the plot for the player. Reveal what their actions reveal.
- Do not summarize what the party "decides to do next" unless the
  player said it.
- Do not have NPCs deliver bullet-point exposition. Show through
  behavior and partial answers.
- Do not list discoveries. Weave them into the moment.
```

**Build (Scene Director pacing hooks):**

The **pre-pass** (`run_pre`, before streaming) fills the existing `pacing_nudge` slot from `beat_count` + `tension_level` + turns-since-`last_revelation_at_turn`, and injects it into the SceneNarrator as **soft guidance the narrator may ignore**. It is never shown to the player and never forces an outcome. Nudge ladder:

- `beat_count < 5`, exploration → "stay descriptive, let them probe."
- `beat_count > 15` **and no discovery since `last_revelation_at_turn`** (keyed on *stalling*, not raw turn count — 15 engaged turns get no nudge) → "this scene's stalling — surface a hidden detail via environmental cue, advance an NPC's agenda, or drop a hook."
- `tension_level > 7` → "escalation point available — an NPC could turn, a threat could land, a revelation could break. Offer it; don't force it."

**Hard rule: nudges are always soft.** Only the player — or a genuine in-world consequence the player triggered — ends or escalates a scene. No hard beat cap; the player owns scene length. The **post-pass** (`run_post`) writes the resulting `tension_delta`, `mood`, thread, and `npcs_present` changes (see the state table above).

**Build (scene builder agent):**

`agents/scene_builder.py` + `prompts/scene_builder/v1.md` — for unauthored locations.

```
In:
  - Location (description, cultural context)
  - Act context (what's happening this act, what's recent)
  - Recent events (last N world bible entries)
  - NPCs known to inhabit this location (or generate via npc_builder)
  - Time of day, weather, atmosphere hints

Out:
  - Full authored-shape scene (all required keys: atmosphere,
    npcs_present with doing/attentive_to/agenda, surface_details,
    hidden[], secrets[], threads_in_air, hooks_out)
  - Persisted as a Scene row, returnable
```

**Timing (locked):** runs **synchronously in the scene-transition resolver, before narration streams** — the player waits once, like loading a new area. Uses the **stronger model tier** (generation quality shows here) but fires **only on first entry to a brand-new location**. Output is **permanent**: every return is instant and re-enters with mutated runtime state, no regeneration.

**Rejected (locked):** no LLM quality-review pass before persisting (doubles hot-path latency; a thin scene is a prompt-tuning signal, not a runtime gate); no speculative pre-generation of adjacent locations (burns tokens on places the party may never visit). Generate on actual entry, full stop.

**Build (mid-scene compression):**

Long scenes (30+ turns) would bloat the prompt if every turn rode along verbatim. Minimal, threshold-based:

- `beat_count ≤ 8`: feed all scene turns verbatim.
- `beat_count > 8`: feed the last ~6 turns verbatim **+** the `scene_progress_summary` string.
- The summary reuses the existing `scene_summarizer` (Slice 5/6), fired **mid-scene** instead of only at close: when `beat_count` crosses 8 and every ~N turns after, it regenerates `scene_progress_summary` from the turns falling out of the recent window. **Fire-and-forget in the post-turn slot** (same pattern as LoreKeeper — zero added turn latency).
- Sits in the memory hierarchy between `recent_turns` (verbatim) and `Scene.summary` (written at close). Fixed thresholds (8 / 6) for v1.

**Build (LoreKeeper extension for scene events):**

- When a scene reveals a hidden detail or secret → LoreKeeper writes an `EVENT` entry tagged with the scene and turn.
- When a thread resolves → LoreKeeper writes a `RELATIONSHIP` or `EVENT` entry describing the resolution.
- When a scene ends → `Scene.summary` written (already in Slice 5); LoreKeeper extracts canonical facts to the world bible.
- All scene events tagged with `revealed_at_turn_id` for the lore-book visibility filter (Slice 13).

**Build (authoring discipline — one fully authored example):**

- `seed/templates/tavern_v1/scenes/back_room_with_grim.yaml` — fully layered scene at the authoring bar. Many paragraphs of atmosphere, several hidden details with distinct DCs, multiple secrets with branching unlock conditions, NPCs with active beats and agendas, multiple hooks out.
- Tutorial section in the template authoring guide: "what a layered scene looks like."

#### Schema changes (single migration)

| Change | Reason |
| --- | --- |
| `Scene.authored` JSONB (new) | Parsed authored scene content (atmosphere, hidden, secrets, threads, hooks). |
| `Scene.beat_count` int (new, default 0, server_default) | Mechanical pacing counter. |
| `Scene.tension_level` int (new, default 0, server_default) | Pacing / escalation signal. |
| `Scene.mood` enum `quiet\|charged\|hostile\|intimate` (new, default `quiet`, server_default) | Hot-path pacing read. |
| `Scene.last_revelation_at_turn` int (new, nullable) | Stalling detection. |
| `Scene.discovered_facts` JSONB (new, default `[]`) | Party's known-facts source of truth. |
| `Scene.unresolved_threads` JSONB (new, default `[]`) | Open threads. |
| `Scene.npcs_present` JSONB (new, default `[]`) | Scene-level NPC presence + in-scene state. |
| `Scene.scene_progress_summary` text (new, nullable) | Mid-scene compression. |

Pre-launch nuke-and-reseed acceptable (no production data).

#### Files added / changed

- **New:** `agents/scene_builder.py`, `prompts/scene_builder/v1.md`; `seed/templates/tavern_v1/scenes/back_room_with_grim.yaml` (the authored bar).
- **Changed:** `db/models/scene.py` (the columns above); `db/queries/scenes.py` (state read/write helpers — `mark_discovered`, thread/tension/mood/presence mutators called from the resolver + post-pass, **not** LLM tools); `agents/scene_director.py` (`_PreDecision.pacing_nudge` activated; `_PostDecision` gains `tension_delta`, `mood`, discovered/thread/presence deltas); `prompts/scene_director_pre/v1.md` + `scene_director_post/v1.md`; `agents/scene_narrator.py` + `prompts/scene_narrator/v1.md` (pacing rules + three-bucket context); `domain/services/scene_director_context.py` (known/hidden-stub/secrets bucketing, `npcs_present` assembly, mid-scene window + `scene_progress_summary`); `domain/services/turns.py` (mechanical `beat_count`; schedule mid-scene `scene_summarizer` in the post-turn slot); the skill-check resolver (write check-gated discoveries); `agents/scene_summarizer.py` (mid-scene invocation); `agents/lore_keeper.py` (scene-event entries); `cairn/types.py` (`SceneMood`, `NpcPresence`, authored-scene shapes).
- **Tool registry:** no new LLM-callable tools (all scene-state writes are service-applied from the resolver / structured output).

#### Decisions locked (grilled 2026-07)

1. **State-writing** — no mid-stream tools; `beat_count` mechanical, check-gated discoveries via the skill-check resolver, everything else via the two Scene Director structured-output passes. SceneNarrator only reads.
2. **Storage** — hybrid: `beat_count`/`tension_level`/`mood`/`last_revelation_at_turn` as columns; `authored` + `discovered_facts` + `unresolved_threads` + `npcs_present` (+ `scene_progress_summary`) as JSONB/text.
3. **Narrator context** — known-in-full / hidden-as-stub / secrets-withheld. Structurally leak-proof; keeps the prompt lean.
4. **Scene-level NPC presence** — owned by Slice 8 as `npcs_present` JSONB on the Scene (closes the stale Slice 6 forward-reference); seeded from author/builder/location roster, mutated by the post-pass.
5. **Scene builder** — synchronous full build on first entry (stronger tier), permanent thereafter; **no** review pass, **no** speculative pre-gen.
6. **Pacing** — mechanical beat_count, soft-only nudges, no hard cap (player owns scene length), stalling-keyed nudge ladder; one free-text entry per discovered fact.
7. **Mid-scene compression** — minimal threshold-based (verbatim ≤8 turns; last ~6 + `scene_progress_summary` after), reusing `scene_summarizer` fire-and-forget; adaptive/semantic windowing deferred.

**Authored vs generated quality gap (accepted):** generated scenes are shallower than hand-authored ones — a scene authored over hours beats one generated in seconds. The builder prompt maximizes layering; v1 accepts the gap and reserves depth for authored major scenes.

**Verify:**

- Player enters Old Grim's back room. First response is atmospheric (smell, light, sound, mood). At most 2-3 specific details. Not a feature dump.
- Player asks Grim about his son. Grim deflects in-character — does not list facts about Maren even though they're in his profile. Conversation continues.
- Player rolls Insight, succeeds. SceneNarrator surfaces a partial read on Grim's deflection (hint, not full content). LoreKeeper records the insight.
- Player investigates the writing desk. Rolls Investigation 14. The **resolver** writes the false drawer to `discovered_facts` before narration; SceneNarrator describes the moment of discovery, not bullet-points.
- The SceneNarrator was **never given** the secret letter's content until `false_drawer_found` entered `discovered_facts` — verify the prompt payload, not just the output.
- Companion makes one quiet contextual comment about Grim's mood mid-scene. Not every turn.
- 15+ engaged turns elapse; no pacing nudge fires. Then the scene stalls (no discovery for several turns) and a nudge fires; Scene Director never forces resolution.
- Scene Builder generates a tavern in an unauthored town **synchronously on first entry**; the wait is a one-time area-load. Patron persists; party returns next session — instant, patron remembers prior turn.
- A scene crosses `beat_count` 8; `scene_progress_summary` is written fire-and-forget; subsequent turns feed last ~6 verbatim + the summary.

**Deferred to a later context-management pass:** adaptive/semantic windowing (window size as a function of tension/beat, embedding-based turn selection). The minimal fixed-threshold compression above is the v1; revisit only if a long scene actually feels like it lost the thread.

---

### Slice 9 — Tactical zones + AI movement — DONE

_Reimagined post-6 (grilled 2026-07). Depends on: Slice 6 (combat polish), Slice 7 (companion profile for ally_ai), Slice 8 (scene context feeds `zone_seeder`)._

Zones bridge theater-of-mind ("you're across the room") and grid combat: 3–6 **named regions** per combat, each combatant in one, distances as categories (`close` / `far` / `out_of_range`). Moving between zones is a tool that spends the mover's **real Speed**. Attack/spell range is a hard legality gate. This is a **node graph, not a grid** — the UI renders regions, not squares.

> **Locations rework (locked 2026-07, this slice owns it).** Today `locations.yaml` bakes a combat-zone grid (`Location.zones` with cover/terrain/adjacency) into every authored place — wrong. **A location is an *abstract* narrative place** (name + description + connections), nothing tactical. Combat zones are **generated by the engine** (`zone_seeder`) from the abstract location + scene context **when combat starts**, not hand-authored. This removes `Location.zones` authoring, drops the baked grid from `locations.yaml`, and makes the tactical map a native product of where the fight happens. Authors describe places; the engine derives the battlefield.

**Design stance (locked): block the impossible, allow the unwise.** The engine knows range/position as fact and enforces *legality* — an out-of-range action is rejected with a plain reason and control returned, **never** "so move closer." It does not nanny tactics or protect informed-but-bad choices (a Fireball that also catches your ally resolves; the friendly fire lands). The **same** enforcement path serves the human player (via `combat_resolver`) and AI combatants (via `combat_ai`) — range lives in the tool layer, checked once.

**Build — zone state in `combat_state`:**

- Combat init augments state with a `zones` list:
  ```
  "zones": [
    {"id": "tavern_front", "name": "Tavern Front", "description": "near the door",
     "cover": "none", "cover_ac_bonus": 0, "cover_save_bonus": 0,
     "difficult_terrain": false, "hazard": null,
     "distances": {"behind_bar": "close", "stairs": "far"}},
    ...
  ]
  ```
- Each combatant's existing `zone: str | None` is filled at init (never left None — see placement).
- `distances[other]` is a category (`close` / `far`); an absent entry ⇒ `out_of_range`. Feet cost of a hop: `close` = 30ft, `far` = 60ft (doubled if the destination has `difficult_terrain`).

**Build — zone seeding (generated per combat):**

- At `start_combat`, fire ONE structured-output pass, **`zone_seeder`** (new agent), reading the abstract location plus current Slice-8 scene context → returns 3–6 zones (distances / cover / terrain / hazard) **plus** a per-team starting placement.
- Parse-safe: on `AgentError` / parse failure, fall back to a single `open_ground` zone. Combat never blocks on seeding.
- Synchronous, before initiative. **No AI-callable `define_zones` tool** (dropped) — zones are seeded once at combat start and are otherwise immutable in v1.

**Build — initial placement:**

- `zone_seeder` supplies one starting zone per team; the single-zone fallback places both teams in `open_ground`.
- Hard guarantee: every combatant has a non-None `zone` after init.

**Build — speed fix (folded in; latent bug today):**

- `_character_combatant` / `_npc_combatant` / `_monster_combatant` now store `speed` (from `char.speed` / `npc.speed` / monster SRD `speed`).
- `advance_turn` seeds `movement_remaining` from that combatant's `speed`, **not** the hardcoded `30` (`state.py:220`).
- `spend_movement` / `spend_economy` defaults stop assuming 30 (seed from the combatant's stored speed).

**Build — zone tools (register in `COMBAT_TOOLS`):**

- `move_combatant(combatant_id, target_zone)`:
  - validates the target zone exists and is reachable (a `distances` category is present).
  - computes feet cost (`close` = 30 / `far` = 60, ×2 if destination `difficult_terrain`); rejects if `movement_remaining` can't cover it (factual reason — the player/AI re-decides: Dash, shorter hop, different action).
  - condition gate: `grappled` / `restrained` block movement. Other movement-affecting conditions (prone crawl-cost, etc.) stay prompt-level in v1.
  - **OA on exit (inline, auto-taken):** before leaving, for each ENEMY of the mover in the *current* zone with a melee weapon and an unused reaction → resolve an opportunity attack right there (roll to-hit, `apply_damage`, mark `reaction_used`, emit `opportunity_attack`). Auto-taken — a beneficial OA is ~always worth it. **This is the only reaction in v1.**
  - on success: update `zone`, `spend_movement`, emit `combatant_moved`.
- `get_combatants_in_zone(zone_id)` — occupants of a zone; for AoE targeting.
- `get_zones_in_range(from_zone, range_category)` — zones at `close` / `far` from the source; read-only, for range self-check.

**Build — range mapping + hard gate:**

- `services/combat/range.py::srd_range_to_category(srd_range_str) -> "self" | "touch" | "close" | "far" | "out_of_range"`:
  - `"Self"` → self; `"Touch"` / `"5 feet"` → touch (same zone); `"10"–"30 feet"` → close; `"60"–"120 feet"` → far; `>120` → far (no sniper-tier zones in v1).
- Effect tools gain **optional** range params; when present, the tool computes attacker/origin-zone → target-zone category and **rejects out-of-range** with a plain reason:
  - `apply_damage` += `attacker_id`, `weapon_range_ft` (single-target attack). Omitted (environmental / DoT) ⇒ ungated.
  - `apply_aoe_damage` += `origin_zone`, `spell_range_ft` (the AoE point must be within spell range of the caster; targets are `get_combatants_in_zone(origin_zone)`).
  - `cast_concentration_spell` += `spell_range_ft` (already has `caster_id` + `target_id`).
- **Subdue enforcement** (deferred from Slice 6): `apply_damage(subdue=True)` requires the attacker in melee range (same / touch zone) of the target.

**Build — cover & terrain (minimal):**

- **Cover-AC is advisory** (there is no engine to-hit): the roller (`combat_ai` / `combat_resolver`) is *told* the target's `cover_ac_bonus` ("half cover, +2 AC") in the zone block and applies it in its narrated to-hit. Hard-enforcing it would require building engine to-hit — out of scope, consistent with the range stance (block illegal, don't compute the roll).
- **Cover-save is hard**: `apply_aoe_damage` reads each target zone's `cover_save_bonus` and adds it to the save (it already rolls saves).
- `difficult_terrain` → doubles the hop feet cost (in `move_combatant`).
- `hazard` (lava / spikes) → DM-narrated only; no auto-damage in v1.

**Build — combat AI + resolver prompt updates:**

- `ally_ai/v1.md`, `enemy_ai/v1.md`, **and the `combat_resolver` prompt** (the human player's action path) get a zone-context block:
  ```
  ## Battle map
  You are at: tavern_front (cover: none)
  Allies at: behind_bar (close)
  Enemies at: stairs (far, half cover +2 AC)
  Your reach: melee = same zone; longbow = far
  ```
- AI / resolver use zone language ("I move to behind_bar and shove the guard"); range rejections come back as tool errors they re-plan around.

**Build — UI data contract (rendering deferred to the UI slice):**

- Slice 9's only UI obligation: expose `combat_state.zones` (all fields) + each combatant's `zone` as the source of truth for a battle map.
- **Captured for the UI slice:** when `combat_active`, show a **zone-region map** — blobs / nodes with distance-labeled links and cover / hazard icons, with mini combatant avatars pinned per region. **Not a grid** (the backend isn't one). Open (UI slice): combat-only map vs. a persistent map; note an *exploration* map is a separate feature built from `Location.connections`, not zones.

**Fix:**

- **`Location.zones` obsolete** — remove the static authored grid and its database column; zones now belong solely to an active combat state.
- **`combatant["zone"] = None`** — filled at init (placement above).
- **Speed hardcoded to 30** (`state.py:220`, `resources.py` defaults) — use real per-combatant speed (above).

**Decide (locked 2026-07):**

1. **Movement** — feet-mapped (not abstract hops), checked against real Speed.
2. **Zone seeding** — parse-safe `zone_seeder` pass from abstract location + scene context; single-zone fallback. Locations never author tactical grids.
3. **Placement** — deterministic team-split, fiction override, never None.
4. **Range** — hard-gate the existing effect tools; block the impossible, allow the unwise; **no** new `resolve_attack` tool.
5. **OA** — inline in `move_combatant`, auto-taken. **The general reaction engine — Counterspell / Shield / Absorb Elements / readied actions / interrupts / player-prompt round-trip / settings-gated `ai`/`suggest`/`player` — is its own dedicated slice** (sequenced after zones, since most reaction triggers are range/position-based). OA is generalized into it when it lands. Slice 9 builds **no reaction bus**.
6. **Cover** — AC advisory (surfaced to the roller), save hard (`apply_aoe_damage`).
7. **Distance granularity** — `close` / `far` / `out_of_range` only (no `medium`).
8. **Zone soft-cap** — 6 per combat.

**Schema changes:** drop obsolete `Location.zones` with an Alembic-generated migration; `combat_state` remains JSONB. New agent `zone_seeder` needs `prompts/zone_seeder/v1.md` + a `llm/models.yaml` entry.

**Files added / changed:**

- `agents/zone_seeder.py` + `prompts/zone_seeder/v1.md` + `llm/models.yaml` entry (new).
- `services/combat/range.py` (new) — `srd_range_to_category`.
- `services/combat/zones.py` (new) — seeding, placement, hop-cost, reachability, OA-on-exit helper.
- `services/combat/state.py` — store `speed` on combatants; seed `movement_remaining` from speed; fill `zone` at init.
- `db/models/location.py`, `locations.yaml`, and migration — retire the old static location-grid field.
- `services/characters.py` — apply Wood Elf's SRD Fleet of Foot speed bonus so the real-speed contract is correct.
- `tools/combat.py` — `move_combatant`, `get_combatants_in_zone`, `get_zones_in_range`; range params on `apply_damage` / `apply_aoe_damage` / `cast_concentration_spell`; subdue melee check.
- `tools/__init__.py` — register the three zone tools in `COMBAT_TOOLS`.
- `prompts/ally_ai/v1.md`, `prompts/enemy_ai/v1.md`, `combat_resolver` prompt — zone-context block.

**Verify:** Combat in a tavern seeds 3–6 generated zones (or `open_ground` on a parse failure); every combatant is placed, none `None`. A 25ft dwarf can't reach a 30ft `close` zone without Dashing; a 35ft wood elf can. Wizard at `stairs` casts Fireball (150ft) at `behind_bar` → in range, hits every occupant there. Wizard tries Cure Wounds (touch) on a PC two zones away → tool rejects with a plain reason, no turn wasted. Rogue leaves a zone holding a goblin with a scimitar + free reaction → auto OA resolves, goblin's reaction marked used, `opportunity_attack` emitted. Companion in a half-cover zone: AoE save gets +2; the AI is *told* +2 AC for to-hit.

**Completed 2026-07-10.** `make check` passes: 321 tests green.

**Deferred:** full reaction engine (own slice); OA-modifying feats (Sentinel); mid-combat zone edits; battle-map rendering + exploration map (UI slice).

---

### Slice 10 — Per-campaign settings + agency presets — DONE

_Reimagined post-6 (grilled 2026-07; model ownership corrected 2026-07-10). Depends on: Slice 5 (`Campaign.settings` JSONB column), Slice 7 (companion depth used by the sliders), Slice 9 (combat behaviour of the companion-combat slider)._

Campaign configuration, selected during campaign creation, editable any time in that campaign's Settings tab, and **resolved once per turn**. It has two groups:

1. **Agency** — who controls what (AI vs player): the preset + override system.
2. **Gameplay knobs** — death mode, passive checks, content/safety, narration verbosity.

**Account tier is a separate concern.** The user's current Free / Plus / Pro tier is bought and managed in Account/Billing and automatically selects the hosted model bundle for every campaign. Upgrading or downgrading changes model routing from the next turn onward. `Campaign.settings` never stores a model tier, provider, model id, or per-agent model override. Local Ollama/Qwen is a developer runtime profile, not a user tier. Slice 14.5 owns account-tier persistence, entitlements, and per-request selection; before then hosted runs default to Free, with an environment override for testing Plus/Pro.

**Design stance — settings are a merge, presets are never mutated.** A named preset supplies defaults; a **sparse override layer** sits on top; `resolve_settings` produces the effective dict everything reads. The preset tag stays put and overrides are stored separately (UI shows "Balanced · 3 custom") — there is no magic "custom" preset value. Agents/tools read only the *resolved* dict, never the raw stored one.

**Build — stored `Campaign.settings` JSONB (sparse):**

```json
{
  "preset": "narrative" | "balanced" | "tactical",
  "overrides": { ... any subset of the resolved shape below ... }
}
```

Example stored value: `{"preset": "balanced", "overrides": {"companion": {"combat": "player"}, "narration": {"verbosity": "terse"}}}`.

**Build — resolved shape (what `resolve_settings` returns, what agents read):**

```json
{
  "preset": "balanced",
  "companion": {
    "combat":    "ai" | "suggest" | "player",
    "dialogue":  "ai" | "suggest" | "player",
    "equipment": "ai" | "player",
    "leveling":  "ai" | "player",
    "checks":    "ai" | "player"
  },
  "checks": {
    "passive_perception": "silent" | "surfaced" | "on_demand",
    "passive_insight":    "silent" | "surfaced" | "on_demand"
  },
  "death_mode": "hardcore" | "narrative" | "pacifist",
  "content": {
    "violence":   "off" | "fade" | "on",
    "gore":       "off" | "fade" | "on",
    "sexual":     "off" | "fade" | "on",
    "romance":    "off" | "fade" | "on",
    "horror":     "off" | "fade" | "on",
    "substances": "off" | "fade" | "on",
    "lines":      ["<hard no-gos the categories don't cover>"],
    "tone_note":  "<freeform flavor, e.g. 'heroic, hopeful, occasional levity'>"
  },
  "narration": { "verbosity": "terse" | "normal" | "lush" }
}
```

**Build — preset resolver (`services/settings.py`):**

- `resolve_settings(campaign) -> dict` — start from base defaults for **all** blocks, overlay the preset (agency + death_mode + passive checks only), then apply `overrides` (sparse, deep-merged). Returns the resolved shape.
- **The preset only steers agency + `death_mode` + `checks`.** `content` and `narration` default independently of the preset and change only by explicit override.
- Agency presets:
  - **Narrative (default):** companion = AI everything; checks = silent; death_mode = narrative.
  - **Balanced:** companion combat = suggest, dialogue/equipment/leveling/checks = ai; checks = surfaced; death_mode = narrative.
  - **Tactical:** companion combat = player, dialogue = ai, equipment/leveling/checks = player; checks = surfaced; death_mode = hardcore.
- Independent defaults (all presets): `content` = every category `fade`, `lines: []`, `tone_note: ""`; `narration.verbosity` = `normal`.
- `validate_overrides(overrides) -> None | raises` — rejects unknown fields and enum-checks every value. Any model-related field is unknown campaign configuration and returns `422`.

**Build — model-policy configuration (separate from campaign settings):**

- `llm/models.yaml` has one developer profile plus three hosted account-tier bundles keyed `free | plus | pro`. `development` maps every agent to local Ollama/Qwen. **Free** uses Luna by default with Terra fallback. **Plus** uses Luna for latency-critical / structured / tool-loop work and Terra (with Luna fallback) for player-facing narration, dialogue, scene building, and NPC deepening. **Pro** adds Sol with Terra fallback for the narrator while retaining the task-tuned Plus map elsewhere.
- `llm/router.py::agent_setup(name, account_tier=...)` owns model selection. `LLM_ENV=local` always selects the developer profile. Hosted selection defaults to `free`; `LLM_TIER=plus|pro` is a Phase-A/test override. Slice 14.5 replaces that process-wide override with the authenticated user's current account tier per request/turn.
- Tier bundles are internal server policy. Users buy a tier; they do not select individual models or edit the per-agent map.

**Build — resolve once, thread through the turn:**

- `turns.service.prepare()` (and graph nodes that open their own session) call `resolve_settings(campaign)` once at turn start; the resolved dict rides in the turn context so every agent/tool/graph node reads the same snapshot (no re-resolving mid-turn, no drift if the row changes underneath).

**Build — routes:**

- `GET /v1/campaigns/{cid}/settings` — returns the **resolved** dict (plus the preset tag + the raw overrides so the UI can render "Balanced · N custom").
- `PATCH /v1/campaigns/{cid}/settings` — accepts a new `preset` and/or a sparse `overrides` patch; `validate_overrides` runs; deep-merges into stored `overrides`; returns the new resolved dict. Setting `preset` alone keeps existing overrides.

**Build — wire into agents/tools:**

- `combat_ai` runs a companion turn only when `companion.combat == "ai"`. `suggest` → server emits `companion_action_proposed` and waits for the player to confirm/override via the combat resolver path. `player` → companion is treated as a player-controlled combatant. (Enemy turns are unaffected — this slider is companion-only.)
- `dialogue` agent voices a companion only when `companion.dialogue == "ai"`; else the player types the companion's lines.
- `checks.passive_perception` / `passive_insight` control SceneNarrator's silent/surfaced/on-demand behaviour (Slice 8).
- `death_mode` controls the `apply_damage` death-path branch (Slice 6).
- `companion.leveling` decides who submits level-up choices (Slice 4 hook — resolves the orphaned forward-ref at roadmap line ~370).
- `companion.equipment` decides who may call equip/unequip tools on a companion.
- `content` block → injected into `scene_narrator` + `dialogue` prompts as an explicit instruction block (`off` = never, `fade` = off-screen only, `on` = allowed; `lines` verbatim; `tone_note` verbatim). **Prompt-level enforcement, not engine-hard** — an LLM can't be mechanically censored; clear `off`/`fade`/`on` phrasing is reliable in practice.
- `narration.verbosity` → `scene_narrator` prompt instruction **plus** a soft `max_tokens` hint per level (terse < normal < lush).

**Build — SSE event (define now):**

```
event: companion_action_proposed
data: { "combatant_id": "...", "proposed": {"tool": "...", "args": {...}, "narration": "..."} }
```

Client renders "Companion proposes: X — Confirm / Override." Confirm → execute `proposed` via the resolver path; Override → normal resolver input.

**Implementation note (locked during build):** the proposal is persisted against the current paused Turn and rendered as the combat proposal band; confirm/override resumes that same Turn through CombatResolver, so no tool mutation happens before the player chooses. Slice 10.5 replaces this interim resolver replay with its typed deterministic plan executor.

**Build — UI (rendering deferred to the UI slice):**

- Slice 10's UI obligation: expose resolved settings + preset tag + raw overrides via the routes above. **Captured for the UI slice:** a campaign settings tab with preset radios, death mode, per-category content toggles (`off`/`fade`/`on`) + `lines`/`tone_note`, verbosity, and a collapsible **advanced** section for per-companion agency sliders and passive-check modes. Account tier is shown and purchased only in Account/Billing. The older v4 mock's campaign model picker and per-agent model overrides are superseded by this correction.

**Decide (locked 2026-07):**

1. **Ownership** — `Campaign.settings` is gameplay-only. Account tier owns models and entitlements for all of a user's campaigns.
2. **Tier behaviour** — Free / Plus / Pro automatically selects a curated, task-tuned bundle in `models.yaml`; no campaign picker and no user-facing per-agent overrides.
3. **Development** — local Qwen is a separate runtime profile and never appears as a customer plan.
4. **Extra settings in v1** — content/safety + narration verbosity. Rules-strictness and a separate global roll-visibility toggle **deferred**.
5. **Content shape** — rich structured categories (`off`/`fade`/`on`) + `lines` escape hatch + `tone_note`. Prompt-level enforcement.
6. **Storage** — preset tag + sparse override layer; never a "custom" preset. `resolve_settings` = base + preset overlay + overrides.
7. **Validation** — `PATCH` rejects unknown or invalid gameplay fields (→ `422`), including any attempted model field.
8. **Mid-campaign changes apply going forward**, current state untouched (switch to hardcore at 0 HP does not retro-kill; the next death locks).

**Schema changes:** none (`Campaign.settings` JSONB exists from Slice 5). `models.yaml` gains developer profile + hosted account-tier bundles (config, not migration). No user-preference table is introduced here.

**Files added / changed:**

- `services/settings.py` (new) — `resolve_settings`, preset tables, base defaults, `validate_overrides`.
- `api/v1/routes/campaigns.py` (or new `settings.py`) — `GET`/`PATCH` settings routes.
- `llm/models.yaml` — developer profile + Free/Plus/Pro task-tuned bundles.
- `llm/router.py`, `config.py` — developer-vs-hosted routing and a temporary hosted-tier override for Phase A/testing.
- `pipelines/turn_graph.py`, `domain/services/turns/service.py` — resolve settings once per turn, thread into context.
- `prompts/scene_narrator/v1.md`, `prompts/dialogue/v1.md` — content block + verbosity instruction.
- Combat/companion wiring (`combat_ai` invocation gate, companion dialogue gate, leveling/equipment gates).

**Verify:** New campaign → Narrative preset resolves (companion all-AI, checks silent). `PATCH {"overrides": {"companion": {"combat": "player"}}}` → resolved companion.combat = player, preset still "balanced", `GET` shows "Balanced · 1 custom". Toggle Tactical → companion combat turns expect player input. Attempt `PATCH {"overrides": {"llm": ...}}` → `422`. Development always uses Qwen; hosted Free uses Luna; Plus task-routes prose to Terra; Pro routes narration to Sol. Set `content.gore = "off"` + `lines: ["self-harm"]` → narrator prompt carries the block; gore stays out of the fiction. Set `narration.verbosity = "terse"` → shorter narration + lower token cap. Switch to hardcore while PC at 0 HP → no retro-death; next lethal hit locks the campaign.


**Deferred:** authenticated per-user tier resolution, caps, and checkout (Slices 14/14.5); BYOK + per-user provider selection (Slice 14); rules-strictness knob; content categories beyond the fixed set (the `lines` escape hatch covers the gap); settings-tab rendering (UI slice).

**Ideas (later):**

- **BYOK** — encrypted per-user API keys unlock providers beyond the server's own (OpenAI/OpenRouter/Anthropic/user-hosted Ollama URL). This is account-owned and needs user identity → Slice 14, UI in the frontend slice.

---

### Slice 10.5 — Reaction engine

_Reimagined post-6 (grilled 2026-07). Depends on: Slice 9 (range/position triggers, the zone-exit OA it generalizes), Slice 10 (the `reaction_control` agency preset). **Revises Slice 9:** promotes cover-AC from advisory to a hard to-hit modifier (see engine to-hit)._

Generalizes Slice 9's single inline reaction (opportunity attack) into a real **reaction bus**: trigger detection, a per-creature reaction economy, deterministic AI decisions, and an interactive player round-trip. A reaction is an out-of-turn action fired by a specific event on someone else's turn — OA on movement, Shield on an incoming hit, Absorb Elements on elemental damage, Counterspell on a spell being cast, a readied action on a declared condition. One reaction per creature per round.

**Design stance (locked): engine-resolved, deterministic, interruptible.** Reactions are resolved by the engine — never invented by the narrating LLM. AI reaction decisions are deterministic heuristics (no extra LLM calls in an already-sequential combat loop). The human player's own reactions are interactive (settings-gated), reusing the skill-check pause/resume precedent. Consistent with **block the impossible, allow the unwise** — the engine offers the legal reaction and states the trigger as fact; it does not nag or auto-protect. [[feedback-engine-doesnt-nanny]]

**The pivotal enabler — engine owns to-hit (revises Slice 9):**

- New `roll_attack(attacker_id, target_id, to_hit_bonus, …)` in the combat engine: d20 (+ adv/disadv from conditions/flanking) + attacker bonus vs target AC → hit/miss, nat-20 crit. Attacks become deterministic like saves already are.
- Target AC sources: character AC (Slice 2.5 derivation), npc/monster AC, **plus the zone's `cover_ac_bonus` as a hard modifier** — Slice 9's advisory cover-AC is now enforced here.
- This is what makes Shield mechanically real: Shield's +5 AC recomputes hit→miss against a *known* attack roll. Attacks that previously let the LLM narrate the hit now go through `roll_attack`; narration describes the engine's result.

**Plan-then-execute combat (the major refactor):**

- `combat_ai` and `combat_resolver` become **planners**: the LLM emits an ordered **plan** — a list of typed engine operations (`move`, `attack`, `cast`, `apply_condition`, …) via structured output — instead of calling mutation tools directly in a live loop.
- A shared **executor** (`services/combat/executor.py`) runs the plan operation-by-operation, deterministically. Because no LLM sits in the execution loop, execution can pause cleanly and resume.
- Bonus: combat becomes deterministic, testable, and replayable from `combat_state` + plans.

**The reaction bus (`services/combat/reactions.py`):**

- A **registry** of reaction definitions. Each: `{ name, trigger predicate, eligibility (registered on the creature + unused reaction + resource available + valid range), should_react heuristic, resolver }`.
- v1 definitions: **opportunity_attack** (moved out of `move_combatant` into the registry), **shield**, **absorb_elements**, **counterspell**, **readied_action**, and **sentinel** (an OA modifier).
- The executor fires trigger events at defined **interception points**:
  - `move` op → on zone-exit: movement trigger → OA / Sentinel / readied(enters-zone / within-reach).
  - `attack` op → **attack-declared** trigger *before* hit/miss is finalized → Shield (defender bumps AC, then `roll_attack` computes).
  - `apply_damage` with a damage type → **damage-type** trigger → Absorb Elements (halve typed damage).
  - `cast` op → **spell-cast** trigger *before* the spell resolves → Counterspell.
  - after every op/event → re-check pending **readied** conditions.
- For each opportunity the dispatcher collects eligible reactors, then:
  - **AI reactors** (enemies + companions, always auto): run the deterministic `should_react` heuristic; if yes, resolve immediately.
  - **The human's own character:** governed by `reaction_control` (below). Under `suggest`/`player`, **suspend** and round-trip.

**AI reaction heuristics (deterministic, per definition):**

- OA → always take it (a free attack is ~always worth it); Sentinel rider drops the target's speed to 0 and fires even on Disengage.
- Shield → only if the attack would land *and* the damage matters.
- Absorb Elements → only above a damage threshold.
- Counterspell → only against spells at/above a threat threshold (level / AoE / control).
- Thresholds are tunable; any definition can later be upgraded to consult the AI.

**Control model — `reaction_control` (Slice 10 agency preset, per-player):**

- `suggest` (**default**): AI reactions auto; for the player's own reactions, suspend **only** when a reaction is available *and* `should_react` says it plausibly changes the outcome — show a prompt with a recommendation. Timeout auto-applies the recommendation.
- `player`: always prompt for the player's own reactions, even marginal ones.
- `ai`: engine decides the player's reactions too (auto-pilot) using the same heuristics — no round-trip.

**Player round-trip (mirrors the skill-check precedent):**

- On a player suspension the executor persists a **checkpoint** in `session.combat_state` (JSONB, no migration): `pending_reaction = { trigger, terse description, eligible options, recommendation, plan_queue, execution_cursor, reaction_stack, depth }`.
- Emit a **`reaction_prompt`** SSE event carrying the options + recommendation + countdown + a **terse, templated** trigger description (e.g. "Orc archer attacks you: to-hit 17 vs AC 15 — would hit. Cast Shield?") — deterministic, *not* LLM narration (mechanics aren't narrated until the round completes).
- The stream ends. Client resumes via **`POST /v1/sessions/{id}/reactions`** `{ decision, chosen_reaction }`. On **timeout**, the client auto-POSTs the recommendation so the round never blocks.
- Resume applies the decision and continues the executor from `execution_cursor`. A single round may suspend/resume **multiple times** (Shield on enemy 3, Counterspell on enemy 5) — falls out of the executor loop.
- Narration is unchanged: the whole round narrates at completion (after all round-trips), exactly as combat does today — reaction prompts are pre-narration mechanical interrupts like `check_required`.

**Nesting & simultaneity:**

- Full nesting via a **LIFO stack**: resolving a reaction is itself an operation that fires its own triggers (player Counterspell → enemy Counterspells it). Depth-capped at **4** as a safety valve.
- The **reaction economy** (one reaction per creature per round) naturally terminates chains — each nested reaction spends a reactor's only reaction.
- Simultaneous eligible reactors to one event resolve in **initiative order**.

**Readied actions (parse-once, match deterministically):**

- On the player's turn, declaring a readied action ("hold my attack until the goblin steps through the door") consumes the action and arms a pending reaction.
- New **`readied_parser`** structured-output agent: one LLM pass converts the sentence → a **structured trigger** (`creature`, `event` ∈ {enters-zone, casts-spell, moves-within-reach, attacks}, optional `zone`/`target`) mapped onto the **same event stream** the bus already emits. Stored structured in `combat_state`; matched **deterministically** on every event thereafter — zero extra LLM calls at runtime.
- One-shot economy; expires at the start of the readier's next turn. If the sentence can't map to a known trigger, **reject with a plain reason** (re-phrase or pick another action) — no fuzzy runtime guessing. [[feedback-engine-doesnt-nanny]]

**Economy & resources:**

- `reaction_used` (already on combatants) gates one reaction/round; refreshes at the start of the creature's turn.
- Spellcaster reactions consume their **resource** (Shield/Absorb 1st-level slot, Counterspell 3rd) via existing resource tracking; feat reactions (Sentinel) gate on the feat. Eligibility **fails closed** if the resource is unavailable.

**Decide (locked 2026-07):**

1. **Scope** — full: OA + Shield + Absorb Elements + Counterspell + readied actions + Sentinel.
2. **Engine to-hit** — introduce `roll_attack`; attacks deterministic like saves; **revises Slice 9** (cover-AC advisory → hard).
3. **Architecture** — central reaction bus + registry; OA moved into it (no more inline in `move_combatant`).
4. **AI decisions** — deterministic `should_react` heuristics, no LLM in the loop.
5. **Combat loop** — plan-then-execute; planners (LLM) + shared deterministic executor; combat becomes replayable.
6. **Control** — `reaction_control` = `suggest` (default) / `player` / `ai`, per-player via Slice 10; governs the human's own character; AI combatants always auto.
7. **Round-trip** — checkpoint in `combat_state`; `reaction_prompt` SSE + `POST /reactions` resume; timeout auto-applies recommendation; multiple suspends/round.
8. **Nesting** — full LIFO stack, depth cap 4, economy-bounded, initiative-ordered for simultaneous.
9. **Readied** — parse-once to a structured trigger (`readied_parser`), deterministic runtime match, reject-if-unmappable.

**Schema changes:** none new. `pending_reaction` + readied actions live in `session.combat_state` (JSONB); `reaction_control` lives in `campaign.settings` (JSONB, Slice 10). New agent `readied_parser` + the planner reshaping of `combat_ai`/`combat_resolver` need prompts + `llm/models.yaml` entries.

**Files added / changed:**

- `services/combat/reactions.py` (new) — dispatcher, registry, the six reaction definitions, `should_react` heuristics.
- `services/combat/executor.py` (new) — plan executor, interception points, checkpoint/suspend/resume, nesting stack.
- `services/combat/plan.py` (new) — typed combat-operation plan schema.
- `services/combat/rolls.py` — add `roll_attack` (d20 vs AC + cover, adv/disadv, crit).
- `agents/combat_ai.py`, `agents/combat_resolver.py` + prompts — become **planners** (emit a structured plan, not a live tool loop).
- `agents/readied_parser.py` + `prompts/readied_parser/v1.md` + `llm/models.yaml` entry (new).
- `tools/combat.py` — OA logic removed from `move_combatant` (now a reaction definition); `apply_damage`/attack path routed through `roll_attack`.
- `domain/services/turns.py` — combat path handles executor suspension; new `resume_reaction` streaming path.
- `api/v1/routes/turns.py` — `POST /v1/sessions/{id}/reactions` resume endpoint; `reaction_prompt` SSE event.
- `sse/events.py` — `reaction_prompt` event type.
- Slice 10 settings — register `reaction_control` (`ai`/`suggest`/`player`) as an agency preset.

**Verify:** Wizard (Shield prepared, slot free) is targeted by an orc's arrow: `roll_attack` = 17 vs AC 15 (would hit) → under `suggest`, `reaction_prompt` fires with the terse trigger + recommendation; player accepts → AC 20, the 17 misses, slot + reaction consumed. Player casts Fireball → enemy mage auto-Counterspells (deterministic, above threshold) → player Counterspells the counter (nested, LIFO, depth 2) → resolves correctly, both reactions + slots spent. Rogue readies "attack when the goblin enters the doorway" → `readied_parser` → `{creature: goblin, event: enters-zone, zone: doorway}`; two turns later the goblin enters → readied attack fires as a reaction, arm cleared. Fighter with Sentinel: enemy Disengages and leaves reach → OA still fires, enemy speed → 0. Player under `ai` preset: same orc arrow → engine auto-declines Shield (damage below threshold), no prompt, round doesn't pause. Timeout on a `reaction_prompt` → client auto-applies the recommendation, round completes. Combat round with no reactions → identical narration to today (plan-execute is transparent when nothing triggers).

**Deferred:** reactions beyond the v1 six (Hellish Rebuke, Riposte, Cutting Words, … — each is now just a registry entry + heuristic); LLM-judged readied conditions (structured parse covers combat triggers; flavor-only conditions rejected); per-reaction "save my reaction for a bigger threat" AI lookahead; server-side timeout timer (client-driven countdown for v1); battle-map rendering of reaction prompts (UI slice).

---

### Slice 10.7 — MCP server + tool registry

_Reimagined post-6 (grilled 2026-07). Depends on: Slice 9 + Slice 10.5 (the combat tool surface — incl. `roll_attack` and the plan-then-execute tools — should be final before we consolidate + register it). Foundational: replaces the two hand-maintained `ALL_TOOLS` / `COMBAT_TOOLS` lists._

**Design stance (locked): two problems, one foundation.** Today the tool layer has (1) two hand-curated lists — fragile (forget to append and a tool silently doesn't exist), and `ALL_TOOLS` has already rotted to **zero consumers** — and (2) no MCP surface at all, despite ~58 tools. A single **tagged auto-discovery registry** fixes both *and* feeds the MCP server. **MCP is a thin projection of internal tools, never a second definition.** The engine tools already take `session_id` / entity-UUIDs as params and open their own DB session per call — they are **already MCP-shaped** (context-by-param, self-contained transaction), which is why exposing them is cheap. **No internal dogfooding:** our agents keep calling tools directly in-process (a direct `await`); MCP is the *cross-process* boundary only — routing the hot combat loop through JSON-RPC would tax latency and add a failure surface for zero gain. Tools stay in `tools/` — **there is no `mcp/` tool folder** (CLAUDE.md preserved); the MCP code is a small surface in `api/mcp.py`.

**Build — the registry (`tools/registry.py`, new):**

- A decorator replaces bare `@tool`:
  ```python
  @register(tags=["combat", "mutation"], mcp=True)
  async def apply_damage(session_id: Annotated[str, "..."], ...): ...
  ```
  `register(*, tags, mcp=True)` applies LangChain's `tool()` to the fn and records `RegisteredTool(tool, tags: set[str], mcp: bool)` in a module-level `_REGISTRY`. Adding a tool = decorate it. No list to edit, ever.
- Accessors: `all() -> list[BaseTool]`; `select(include: set[str], exclude: set[str] = set()) -> list[BaseTool]` (tags ⊇ include, tags ∩ exclude = ∅); `mcp_tools() -> list[RegisteredTool]` (the `mcp=True` subset).
- **Auto-discovery:** `tools/__init__.py` imports each tool module for side effects (explicit import list — deterministic, no import-order surprises; the modules are few and stable), then derives the public names **from the registry** instead of hand-listing:
  - `ALL_TOOLS = registry.all()`
  - `COMBAT_TOOLS = registry.select(include={"combat"}, ...)` (or a union of the combat-relevant tags) — **derived, not hand-listed**
  - back-compat: the names `ALL_TOOLS` / `COMBAT_TOOLS` stay, so `combat_ai` / `combat_resolver` imports don't change.
- **Guard test** (`tests/test_tool_registry.py`) — asserts every `@tool`/`@register` callable found under `tools/` is present in the registry. This is the safety net that replaces "remember to edit the list": an unregistered tool fails CI.
- **Tag taxonomy (v1):** `dice`, `srd`, `readonly`, `combat`, `resource`, `rest`, `state`, `mutation`, `narrative`. `mcp` flag defaults `True` (default: expose the engine — the stateful surface *is* the differentiator per the scope decision).

**Build — consolidation (symmetric pairs only):**

- **Rule: collapse a pair only when the two share the same argument shape modulo a sign/bool.** Asymmetric pairs stay (see below). This keeps consolidation low-risk — consistent with the "surgical" restructure decision.
- Collapses (symmetric):
  - `use_action` / `use_bonus_action` / `use_reaction` → `use_economy(economy_type)`
  - `consume_spell_slot` / `restore_spell_slot` → `adjust_spell_slot(level, delta)`
  - `use_resource` / `restore_resource` → `adjust_resource(name, delta)`
  - `apply_condition` / `remove_condition` → `set_condition(condition, active)`
  - `add_exhaustion` / `remove_exhaustion` → `adjust_exhaustion(delta)`
- **Left as-is (asymmetric — collapsing would worsen them):** `apply_effect` / `remove_effect` (apply needs the full effect, remove needs an id); `set_concentration` / `drop_concentration` (set needs a target, drop takes none); `apply_damage` / `apply_healing` / `apply_temp_hp` (distinct semantics).
- Net: ~58 → ~40. Combat-agent prompts (`ally_ai`, `enemy_ai`, `combat_resolver`) reviewed for any **hardcoded tool names** touched by a merge; the existing combat integration tests are the gate.

**Build — the MCP server (`api/mcp.py`, new + mount):**

- `uv add "mcp[cli]"` (official SDK; FastMCP v2 merged upstream).
- `build_mcp_server() -> FastMCP`: `mcp = FastMCP("cairn")`; for each `rt` in `registry.mcp_tools()`: `mcp.add_tool(rt.tool.coroutine, name=rt.tool.name, description=rt.tool.description)`. LangChain's `.coroutine` is the original async fn with its `Annotated[...]` hints intact, so FastMCP builds the input schema straight from what already exists. ~15 lines. **One definition, two projections** (LangChain internal, MCP external — guaranteed no drift).
- **Mount:** in the app factory, `app.mount("/mcp", mcp.streamable_http_app())`. **The one integration subtlety:** the streamable-HTTP session manager needs its lifespan wired into the app lifespan (`async with mcp.session_manager.run(): yield` combined into the existing FastAPI lifespan) — miss this and the endpoint 500s on connect. Called out here so it isn't rediscovered painfully.
- **`MCP_ENABLED`** config flag (default on in dev). `MCP_ENABLED=false` → not mounted, internal agents unaffected.
- **No auth in Phase A** (single-user local). A prominent banner in `api/mcp.py` + this slice: **do not expose `/mcp` to the internet without Slice 14 auth** — a stateful engine open unauthenticated is a security hole. Gated to Phase B.
- **Known concurrency risk (flagged, not fixed):** an external MCP client and the internal agent can both mutate the same `session.combat_state` JSONB → lost update. Acceptable in single-user Phase A; the real fix (row lock / optimistic version on `combat_state`) is deferred to Phase B hardening.

**Decide (locked 2026-07):**

1. **Direction** — **server only**. Client (consume external MCP servers via `langchain-mcp-adapters`) is deferred: we have a complete engine and no concrete external server to eat; it's a few lines to add the day one is chosen.
2. **No internal dogfooding** — agents call tools directly in-process; MCP is the cross-process boundary only (hot-loop latency + failure surface).
3. **Scope** — full **stateful** engine; context via `session_id` / entity-UUID per call (already the tool contract); **no auth** (Phase A local) behind `MCP_ENABLED`; auth + internet exposure gated to Phase B / Slice 14.
4. **Framework** — **FastMCP** (`mcp` SDK), streamable-HTTP, **mounted at `/mcp`** on the FastAPI app; single process / container (fits the $5–15/mo budget).
5. **Parity** — one `@tool` def → two projections via the registry; **no `mcp/` tool folder**, tools stay in `tools/`.
6. **Registry** — `@register(tags=…, mcp=…)` auto-discovery replaces the hand lists; `ALL_TOOLS` / `COMBAT_TOOLS` become tag-derived; guard test forbids an unregistered tool.
7. **Consolidation** — symmetric pairs only (same arg shape ± sign/bool); asymmetric pairs stay; combat prompts reviewed, existing combat tests are the gate.
8. **Concurrency** — external+internal concurrent `combat_state` writes are a known lost-update risk; acceptable single-user Phase A; row-lock/version fix deferred to Phase B.

**Schema changes:** none (no DB changes; `MCP_ENABLED` is env/config).

**Files added / changed:**

- `tools/registry.py` (new) — `register` decorator, `_REGISTRY`, `all()`, `select()`, `mcp_tools()`.
- `tools/__init__.py` — import tool modules for side effects; derive `ALL_TOOLS` / `COMBAT_TOOLS` from the registry; drop the hand lists.
- `tools/combat.py`, `tools/resources.py`, `tools/srd.py`, `tools/dice.py`, `tools/game_state.py`, `tools/inspiration.py` — swap `@tool` → `@register(tags=[…])`; apply the symmetric-pair consolidations.
- `api/mcp.py` (new) — `build_mcp_server()` + the registry→FastMCP adapter + the no-auth banner.
- app factory (`main.py` / app setup) — mount `/mcp`, wire the session-manager lifespan, `MCP_ENABLED` gate.
- `prompts/ally_ai/v1.md`, `prompts/enemy_ai/v1.md`, `combat_resolver` prompt — update any hardcoded names for consolidated tools.
- config / settings — `MCP_ENABLED`.
- `pyproject.toml` — via `uv add "mcp[cli]"`.
- `tests/test_tool_registry.py` (new), `tests/test_mcp_server.py` (new).

**Verify:** A new `@register`-decorated tool appears in `ALL_TOOLS`, its tag subset, and (if `mcp=True`) the MCP server **with no list edit**; leaving a tool unregistered fails the guard test. `COMBAT_TOOLS` count drops after consolidation and the combat integration suite still passes. Boot the API → `/mcp` serves an MCP endpoint; an MCP client (the `mcp` CLI / Claude Desktop via URL / an in-process test client) lists Cairn's tools, calls `lookup_spell("Fireball")` (stateless) and a stateful `apply_damage(session_id=…, …)` that actually mutates `combat_state` in Postgres. `MCP_ENABLED=false` → `/mcp` absent, internal combat unaffected.

**Deferred:** MCP **client** (consume external servers) — add when a concrete server is chosen; **auth + internet exposure** of `/mcp` — Phase B / Slice 14; **combat_state concurrency hardening** (row lock / optimistic version) — Phase B; **narrator tool-use** (a read-only `NARRATOR_TOOLS` subset — the scene narrator currently binds no tools; `ALL_TOOLS` was dead) — optional gameplay follow-on, flagged not forced; **stdio transport** for local Claude Desktop — trivial to add later (`mcp.run(transport="stdio")`).

---

### Slice 11 — Operational hardening

_Depends on: nothing strict. Run before Slice 12 (events for evals); before Slice 15 (SSE for frontend)._

Single-purpose slice batching operational bugs and infra prep.

**Build / fix:**

- **LLM call timeout** — add `timeout=N` to litellm calls (60s streaming, 30s non-streaming). Translate timeout into LLMError → 504.
- **SSE stream graceful error path** — wrap stream loop in `turns.py::generate()` with try/except. On error: mark turn failed, emit `turn_failed` SSE, save what we have. Add `Turn.status: pending | complete | failed`.
- **`combat._emit` silently swallows event log failures** — currently log.warning only. Evals depend on complete events. Decide: fail the action or escalate. Document.
- **Tool loop budget rollback** — `complete_with_tools` raises after 15 iterations. Partially-mutated DB state from earlier tool calls is not rolled back. Wrap loop in transaction OR document partial-commit semantics.
- **LoreKeeper retry** — fire-and-forget via `asyncio.create_task`. Add 3-attempt retry with exponential backoff. Durable-queue version in Slice 15.
- **Pre-commit hooks** — ruff format, ruff check, mypy. Block bad commits from CI.
- **Langfuse decision** — local for dev (cheap, useful for long agent loops). Document.
- **Model fallbacks verified** — one test that fallback triggers on primary 429/503.

**Verify:** 70-second model hang produces a 504 with `turn_failed` SSE event. Combat tool failure mid-loop fully rolled back OR fully committed (per chosen strategy). LoreKeeper retries 3× before giving up.

**Ideas (not scoped yet — think about when we get here):**

- **Per-prompt token budget tracking + clipping** — before sending any LLM call, estimate assembled context tokens. If over per-agent budget, log a warning AND clip the lowest-priority layer (recent turns first, then day summaries, then world bible RAG). Per-agent budgets: Scene Director (~4k), IntentRouter (~2k), SceneNarrator (~40k), CombatResolver (~30k). Prevents silent context-window blowouts as campaigns grow long.

---

### Slice 12 — Eval suite + CI gate

_Depends on: Slice 8 (complete narrative + scene loop), Slice 11 (event log completeness)._

LLM-as-judge evals block merges on regression.

**Build:**

- `evals/golden/continuity.json` — does the DM recall earlier session facts?
- `evals/golden/npc_voice.json` — does the NPC stay in character?
- `evals/golden/rules_5e.json` — does RulesLawyer adjudicate correctly? (meaningful now that Slice 3 fixed character context)
- `evals/golden/scene_transition.json` — transitions feel narrative.
- `evals/golden/reaction_bus.json` — Sentinel / opportunity attacks fire.
- `evals/golden/companion_approval.json` — DM agent adjusts approval on value-aligned/violating actions.
- `evals/golden/zone_combat.json` — combat AI respects zone ranges and uses movement reasonably.
- `evals/golden/scene_pacing.json` — SceneNarrator withholds correctly, doesn't info-dump, surfaces details only on engagement.
- `evals/golden/npc_consistency.json` — NPC stays in character across a 10-turn dialogue, deflects appropriately, surfaces private facts only on earned trust.
- `evals/eval.yml` GitHub Actions — runs on PRs touching `prompts/` or `agents/`.
- Baseline scores committed.

**Test coverage gap (note):** unit tests for turn graph nodes — `tests/conftest.py` patches the entire graph at module level. Worth adding granular agent tests post-launch.

**Verify:** 9 suites pass locally. `eval.yml` blocks a PR that degrades any score.

---

### Slice 13 — World bible retrieval (RAG)

_Reimagined post-6 (grilled 2026-07). Depends on: Slice 5 (embedding columns + chunked lore + scene bounds), Slice 12 (eval baseline for tuning top-k / rerank)._

Wires the two RAG-shaped layers of the DM context that Slice 5 stubbed: **layer 1** (relevant world lore) and **layer 3 / 5** (relevant campaign memory — world-bible entries + older day summaries past the recent-N window). Retrieval runs **before `SceneNarrator`, in the turn hot path, every turn**.

**Design stance (locked): this is a small, hand-authored, structured corpus — not a big-document RAG problem.** `WorldLoreChunk` rows are chunked *at authoring time*, each already self-contained with a `title`, `category`, and `tags`. That authored `title + tags` **is** the "contextual header" that Anthropic's Contextual Retrieval adds with an LLM — so **no ingestion-time LLM contextualization** and **no fancy chunking** are needed; the corpus is already dressed for retrieval. A campaign's `WorldBibleEntry` set grows but stays small (hundreds of rows for a long campaign). Consequences that shaped every decision below:

- **No Qdrant, no separate vector service.** pgvector in the existing Postgres — Slice 5 already added the `embedding` columns. A whole extra service on a 1–2 GB VPS is unjustified for a corpus that fits in a table (deploy budget). Reference implementation for the mechanics is the user's own `doc-research-agent` (hybrid + RRF + cross-encoder), **ported down** to pgvector and scaled to this corpus.
- **No GraphRAG.** The build-a-graph rule (≥30% of retrieval *failures* are multi-hop across documents sharing no surface text) can't even be evaluated yet — no retrieval shipped, no failure data. Its real cost is a maintenance tail on a hobby budget. Cairn already has a **cheap manual graph** — `RELATIONSHIP` bible entries + faction/NPC links + `tags` — used as structured filter/boost signal, not an LLM-extracted graph. Escape hatch if evals later show multi-hop failures: the **graph-as-reranker** pattern (expand entities from top-k, 1–2 hops) — deferred, not built.
- **Linear RAG, not agentic RAG.** Retrieval is deterministic context-assembly, not a ReAct loop deciding *when* to retrieve. No re-retrieval, no tool-call loop — latency budget forbids it (`doc-research-agent`'s agentic loop exists because it answers arbitrary user questions; Cairn assembles a prompt).

**Build — storage & indexing (pgvector, all in Postgres):**

- Migration (Alembic): pin `WorldBibleEntry.embedding` and `WorldLoreChunk.embedding` to `vector(384)`; add `embedding_model_version: str | None` to both (stamp on write so we can bulk re-embed on a model swap); add a generated `tsvector` column (over `title` + `content`) with a **GIN** index for full-text; add an **HNSW** index on each `embedding` (cosine). No new SQL by hand — Alembic-generated, pgvector/tsvector DDL in the migration body.
- All vector + FTS access lives in `db/queries/` (hard rule) — a candidate-fetch function per table doing the pgvector `<=>` cosine query and the `tsvector @@` query, scoped by `world_id` (lore) / `campaign_id` (memory).

**Build — embedder (local, both envs — corrects the stale "SageMaker/S3 Vectors in prod"):**

- **FastEmbed `BAAI/bge-small-en-v1.5`, 384-dim, ONNX** — same library family as the reranker (no PyTorch; small image; fast on the VPS). Runs in **dev and prod** on the same box. `uv add fastembed`.
- Warm the model at startup (like the reranker) so the first turn doesn't pay the load.
- **When embeddings are computed:** `WorldLoreChunk` — embedded at **seed time** (one-shot in the seed loader) and **on edit**. `WorldBibleEntry` — embedded **inline inside the LoreKeeper fire-and-forget task** (already async/off the hot path, so the embed is free latency-wise). Every write stamps `embedding_model_version`.

**Build — hybrid search + RRF (`services/retrieval/`):**

- `hybrid_search(query, scope, top_k)`:
  1. **Dense** — embed the query (FastEmbed), pgvector cosine over the scoped rows → wide candidate pool (`fetch_k = min(top_k × multiplier, cap)`, mirroring `doc-research-agent`).
  2. **Lexical** — Postgres `tsvector` FTS over the same scope → its own ranked list. **Tags** (authored faction/place/NPC names) feed the lexical/boost side — this is where exact proper nouns ("Kaelen", "the Ashen Vow") get caught that dense misses.
  3. **RRF fusion** — merge the dense and lexical ranked lists (`score = Σ 1/(k + rank)`, `k=60`) into one candidate ordering.
- **No hard relevance pre-filter** beyond the mandatory scope (`world_id` / `campaign_id`): hybrid + RRF + rerank do the ranking. Avoids the "untagged ⇒ invisible" failure. `always_on_lore_keys` chunks are injected **unconditionally** (they bypass retrieval) and de-duped against retrieved hits.

**Build — reranker (`RERANK_ENABLED`, default ON):**

- Port `doc-research-agent`'s cross-encoder (FastEmbed `TextCrossEncoder`, local ONNX, warmed at startup). Re-scores the RRF candidate pool against the query, keeps `top_k`. Behind a config flag (`RERANK_ENABLED`, default **ON**); Slice 12 evals validate it earns its latency, flip off if not. Disabled ⇒ `fetch_k == top_k`, rerank is a no-op trim.

**Build — the two retrievals + hot-path orchestration (`services/retrieval/lore_retrieval.py`):**

- **(1) World-lore retrieval** — query text = **current location + NPCs in scene + active threads**; scope = `world_id`; returns `WorldLoreChunk` rows (faction/region/deity/figure/history), plus the template's `always_on_lore_keys` chunks.
- **(2) Campaign-memory retrieval** — query text = **player input + recent-turns window + active quest/thread titles** (richer query ⇒ old events tied to a running quest resurface even when the player doesn't name them — the continuity goal; the reranker trims the added noise); scope = `campaign_id`; returns `WorldBibleEntry` rows (campaign NPCs/events/quests + day summaries past the recent-N window).
- **Concurrency + caching (hot path):** run both retrievals **concurrently** (`asyncio.gather`). **Cache the world-lore result at scene scope** — in-memory, keyed by `scene_id` + NPC-roster hash; recompute only on scene change or roster shift (its query inputs are stable within a scene). The campaign-memory retrieval runs **every turn** (query changes each turn). ⇒ most turns pay for one live retrieval, not two.
- **Failure/latency guard (mirrors Slice 9's "combat never blocks on seeding"):** the whole retrieval is wrapped with a timeout + `try/except`; on error or timeout, **degrade gracefully** to `always_on_lore` + recent turns and narrate anyway. Retrieval never blocks the turn.
- **Cold start:** campaign turn 1 has no bible → memory retrieval returns empty, lore-only. Fine.

**Build — prompt stitching (`services/narrative_context.py::build_dm_context`):**

- Fill the layer-1 and layer-3/5 stubs. Stitch the two result sets under **distinct headers** so the LLM treats them differently:
  - `## Background lore` — reference only; **prompt discipline line**: "background reference; do not steer the scene toward these elements" (the context-pollution guard — chunked + retrieved precisely so the DM sees only what's relevant, and is told not to force-fit it).
  - `## Campaign memory` — history; things that actually happened, safe to reference and build on.

**Build — lore search endpoint (frontend lore panel):**

- `GET /v1/campaigns/{cid}/lore?q=guild` — reuses `hybrid_search` over the campaign's revealed lore/bible, **player-visibility filtered** by `revealed_at_turn_id` (Slice 5). For the UI lore-book; the no-`q` list endpoint already exists.

**Decide (locked 2026-07):**

1. **Vector store** — pgvector in the existing Postgres. No Qdrant, no separate service (budget). No GraphRAG.
2. **Hybrid shape** — pgvector dense + Postgres `tsvector` FTS + authored `tags` boost, fused with **RRF**. All inside Postgres.
3. **Reranker** — FastEmbed cross-encoder (local ONNX, warmed), `RERANK_ENABLED` flag, **default ON**, eval-validated.
4. **Embedder** — FastEmbed `bge-small-en-v1.5`, 384-dim ONNX, local in **both** dev and prod; `embedding_model_version` stamped.
5. **Hot path** — two retrievals concurrent; world-lore cached at scene scope (in-memory, `scene_id` + roster hash); campaign-memory every turn.
6. **Memory query** — player input + recent-turns window + active thread/quest titles (max continuity recall; reranker cleans noise).
7. **World echoes** — **deferred.** Ship isolated: (this world's lore) + (this campaign's memory) only. Cross-campaign `CAMPAIGN_CONCLUDED` retrieval is a later, setting-gated add (needs concluded campaigns to exist; complicates isolation).
8. **top-k** — start lore=4 / memory=4, `fetch_k` = `top_k × multiplier` capped; **tune against Slice 12 evals**.

**Schema changes:** pin both `embedding` columns to `vector(384)`; add `embedding_model_version` on `WorldBibleEntry` + `WorldLoreChunk`; add generated `tsvector` column + GIN index (both tables); add HNSW cosine index on both `embedding` columns. All Alembic-generated.

**Files added / changed:**

- `services/retrieval/` (new package): `embedder.py` (FastEmbed dense embed + warmup), `search.py` (hybrid dense + FTS + tag boost, RRF fuse, wide fetch), `rerank.py` (cross-encoder, `RERANK_ENABLED`, warmup — ported from `doc-research-agent`), `lore_retrieval.py` (the two retrieval entry points, scene cache, concurrent orchestration, failure guard).
- `db/queries/` — pgvector cosine + `tsvector` candidate-fetch functions, scoped by `world_id` / `campaign_id` (all DB access through here).
- `db/migrations/` — one Alembic revision: pin `vector(384)`, add `embedding_model_version`, generated `tsvector` + GIN, HNSW indexes.
- `agents/lore_keeper.py` — embed + stamp version on write (inside the existing fire-and-forget task).
- `services/narrative_context.py` — `build_dm_context` wires layers 1 + 3/5 (currently stubbed); stitches the two headers with the prompt-discipline line.
- `seed/` loader — embed `WorldLoreChunk`s at seed time (+ on edit).
- `api/v1/routes/campaigns.py` — `GET /{cid}/lore?q=` search variant (visibility-filtered).
- config — `RERANK_ENABLED`, `top_k` (lore/memory), `fetch_k` multiplier + cap, embedding model name + version.
- startup — warm embedder + reranker.
- `pyproject.toml` via `uv add fastembed`.

**Verify:** `SceneNarrator` prompt includes only lore relevant to the current scene (not the full world); lore chunks for unrelated regions/factions are absent. Exact proper-noun recall works — a query naming an NPC/faction that dense alone would miss is caught by the FTS+tag side. DM references a campaign-specific fact from 20+ turns ago (memory retrieval surfaces it via the enriched query). Prompt discipline holds — DM doesn't force-fit background lore into unrelated scenes. Within one scene, the lore retrieval is served from cache (not re-embedded every turn); it recomputes when the party moves scenes. Retrieval timeout/error ⇒ turn still narrates on `always_on` + recent turns. `RERANK_ENABLED=false` ⇒ pipeline still returns `top_k`, just RRF-ordered.

**Deferred:** cross-campaign world echoes (setting-gated, later); graph-as-reranker multi-hop (only if evals show graph-shaped failures); LLM contextual retrieval / HyDE / query-expansion (unneeded for an authored corpus — revisit only if eval recall stalls); prod vector-store swap (stays pgvector — no S3 Vectors / SageMaker).

---

### Slice 14 — Auth + cost controls

_Depends on: nothing strict. Must be done before Slice 15._

**Decide first:**

- Clerk vs manual JWT. Lean Clerk.
- Rate limiting placement — middleware (simpler).
- Cost tracking — LiteLLM callbacks vs `Turn.llm_cost_usd` field.

**Build (auth):**

- Auth middleware — validate JWT on all non-SRD routes, extract `user_id`.
- Replace `X-User-Id` dev shim.
- Campaign access control — verify routes validate `current_user_id ∈ campaign.member_ids`.
- SRD routes stay public.

**Build (cost controls):**

- Per-user rate limiting (e.g., 30 turns/hour).
- LLM cost tracking — `Turn.llm_cost_usd` populated from LiteLLM callbacks.

**Verify:** Unauthenticated request to non-SRD route → 401. User can't access another user's campaign. 31st turn in an hour → 429. `Turn.llm_cost_usd` totals match LiteLLM spend.

**Ideas (not scoped yet — think about when we get here):**

- **BYOK (bring-your-own-key) for per-user LLM provider choice** — encrypted per-user API key storage owned by the account. Backend reads the user's key before LLM calls. For Ollama: user supplies their own localhost URL; backend needs outbound config + clear-warning UX about local-only networking.
- **Per-provider cost tracking** — `Turn.llm_cost_usd` already populated from LiteLLM callbacks. Extend to also tag `Turn.llm_provider` so we can report cost per provider per user (matters for BYOK accounting and OpenRouter routing visibility).

---

### Slice 14.5 — Plans & entitlements

_Depends on: Slice 10 (`models.yaml` account-tier bundles), Slice 14 (Clerk `user_id`, per-user rate limiting, cost tracking, BYOK key storage). Must be done before the billing UI in Slice 15._

The **account-tier / entitlement layer**. A user has one current `free | plus | pro` tier; it directly selects the hosted model bundle for every campaign and supplies the feature caps. There is no second campaign-level model tier to pick or clamp. Developer-local Qwen is a separate runtime profile, not a plan. Nothing here invents new gameplay — it supplies account policy to existing runtime and creation seams. **Entitlement-first: this slice ships the tier model + enforcement only; real checkout is deferred (Phase B).** Tiers are assigned manually (admin/seed) until then.

**Two orthogonal axes (the mental model).** Keep these separate or the design collapses into confusion:

- **Axis A — who pays for inference.** *Hosted* (our API keys; usage capped by plan) vs *BYOK/local* (user's own key or Ollama URL from Slice 14; the user pays for tokens, so their **model quality is uncapped** and their **turns/day cap is lifted** — abuse-limiting only).
- **Axis B — account tier.** Free / Plus / Pro selects the hosted model bundle and gates **campaign count**, **image-gen**, and **turns/day** (hosted-only). BYOK changes Axis A but a BYOK user's feature caps (campaigns, image-gen) still follow their account tier.

**Naming:** "plan" and "account tier" refer to the same buyable Free / Plus / Pro ladder. Internal per-agent assignments are called **model bundles**, never another user-facing tier.

**Plan ladder (v1):**

| Account tier | Hosted model bundle | Campaigns | Turns/day (hosted) | Image-gen |
|---|---|---|---|---|
| **Free** | Luna default (Terra fallback) | 1 | ~20 | — |
| **Plus** | Luna fast/structured; Terra prose/builders | 3 | ~150 | ✓ |
| **Pro** | Plus bundle; Sol narrator | ∞-ish | high | ✓ |

BYOK (any plan): model uncapped on the user's key, turns/day lifted; campaign + image-gen caps still per-plan. Free never burns much of our budget (cheap floor model + tight cap); safety/content controls, verbosity, RAG, builders, and companion agency are **never gated** — paywalling safety or narrative quality is off the table.

**Build — plan catalog (config-as-code):**

- `llm/../plans.yaml` (or `config/plans.yaml`) maps `plan → {campaign_cap, turns_per_day, image_gen}`. Model bundles remain in `models.yaml` under the same `free | plus | pro` keys. Plans change rarely → config, **not** a DB table.

**Build — schema (`user_entitlements` table, Alembic):**

- Keyed by Clerk `user_id` (Slice 14). Columns: `user_id` (PK), `plan: enum(free|plus|pro)` default `free`, `plan_assigned_at`, `notes`. BYOK-configured state is **derived** from Slice 14's key storage, not duplicated here.
- Rows created lazily (missing row ⇒ treat as `free`). Manual assignment for now via admin route / seed.

**Build — entitlements service (`services/entitlements.py`):**

- `get_entitlements(user_id) -> Entitlements` — reads the account tier from `user_entitlements` (default `free`), looks up caps in `plans.yaml`, and overlays BYOK effects (has-own-key ⇒ hosted turns cap lifted). It returns the current tier so LLM routing selects the matching bundle. **Single source of truth**; every enforcement point reads it. `Entitlements` is a `cairn/types.py` TypedDict.

**Build — enforcement points (wire into existing seams):**

- **Model routing** — resolve entitlements once at turn start and bind `entitlements.plan` to the LLM routing context. Upgrade/downgrade automatically changes all campaigns from the next turn; no campaign row is rewritten.
- **Turns/day** — Slice 14's per-user rate limiter reads `entitlements.turns_per_day` instead of a hardcoded value; BYOK lifts it.
- **Campaign count** — `POST /v1/campaigns` counts the owner's campaigns vs `entitlements.campaign_cap` → **402** with `upgrade_hint` when over.
- **Image-gen** — the (Phase-B) generate-portrait endpoint checks `entitlements.image_gen`; gallery + upload stay free for all.

**Build — routes:**

- `GET /v1/me/entitlements` — resolved entitlements for the current user (UI reads this to gate pickers + show upgrade CTAs).
- `GET /v1/plans` — public plan catalog from `plans.yaml` (drives the pricing/billing screen).
- `PATCH /v1/admin/users/{user_id}/plan` — manual plan assignment, `is_admin`-gated (Slice 14 dep #8). Minimal; the self-serve upgrade flow is Phase B.

**Build — UI obligations (captured for Slice 15):**

- Campaign Settings has no model picker. Account/Billing renders the concrete `GET /v1/plans` ladder + current tier + model/feature improvements and owns the upgrade CTA.
- Campaign-create and generate-portrait affordances show cap state and surface the `upgrade_hint` on 402.

**Decide (locked 2026-07):**

1. **One buyable tier** selects both the hosted model bundle and feature limits; there is no second per-campaign quality tier.
2. **Free = hard-capped hosted** (cheapest hosted model, tight daily cap, 1 campaign) — zero setup to play, bounded spend.
3. **BYOK is orthogonal** — unlocks model quality on the user's dime; feature caps still follow the plan; turns/day cap is hosted-only.
4. **Entitlement-first** — ship the plan model + enforcement now; manual assignment; checkout deferred to Phase B (Lemon Squeezy / Paddle merchant-of-record when it lands, to offload VAT for a solo dev — not raw Stripe).
5. **3 account tiers — Free / Plus / Pro** per the ladder above.
6. **Never gate** safety/content, verbosity, RAG, builders, or companion agency.

**Verify:**

- Free, Plus, and Pro turns select their matching model bundles without reading Campaign.settings.
- Free user creating a 2nd campaign → 402; Plus user → 200 up to 3.
- Downgrade Pro→Free with active campaigns: their next turns use the Free bundle; campaign gameplay settings are unchanged.
- BYOK user runs on their own configured provider; hosted turns/day is not charged.
- `GET /v1/me/entitlements` matches the assigned plan + BYOK state; `GET /v1/plans` returns the catalog.

**Deferred / Phase B:** real checkout + self-serve upgrade (Lemon Squeezy/Paddle), proration, usage-based overages, per-provider cost accounting (Slice 14 idea).

**Schema changes:** new `user_entitlements` table (Alembic). `plans.yaml` is config, not a migration.

---

### Slice 15 — Frontend (UI reference rebuild)

_Grilled 2026-07 — **GRILL COMPLETE ✅. `Cairn App v4.html` is the current spec** — v3 built + user review (Decision 9) + consistency audit (Decision 10) + second review / pattern rework (Decision 11) + third review — landing rebuilt as "the page is a session", 12b the drop, the Drafting Room admin surface (Decision 12); v2/v3 kept as history. → **Self-contained build brief (tokens + interaction principles + flow map + 30-screen inventory + build order): `docs/ui-temp-reference/v4-build-brief.md` — open that first to build.** Phase A (core). Depends on: the playable engine (Slices 1–10.7). **Auth is NOT a hard dep** — Phase A is single-user (`X-User-Id` header); the login/tiers screens are drawn **visual-only**, real auth lands in Phase B / Slice 14 and tiers + billing in Slice 14.5._

**⚠️ Backend deps this slice surfaced (not pure-UI; track separately):**
1. **Weave agent** — concept prompt → structured `bio`/`personality`/`voice_traits` for the custom-forge identity step (new agent + prompt + `models.yaml` entry).
2. **Player-rolled death saves** — change `roll_death_save` (`domain/services/combat/rolls.py:65`) from server-side `rng.randint(1,20)` to the client-roll → `/resolve` pattern used by skill checks.
3. **Portrait image-gen (later / Phase B)** — no image-gen exists; "Generate" is a flagged affordance. Earmarked provider: Replicate FLUX-schnell (~$0.003/img).
4. **Template-browse endpoint** — `GET /v1/campaigns/templates` (premise · length · premades · teaser lore) for the home/browser; already in the retained surface checklist. Should return **worlds with scenarios nested** — the browser is two-level (Decision 9).
5. **Equipment slot taxonomy** (added 2026-07 review) — equipment today is a flat list + equipped flag; the redesigned sheet's drag-to-slot inventory (body / main hand / off hand / …) needs slot names on items. Supersedes the checklist line "simple list with equipped badge; drag-and-drop v2."
6. **`GET /v1/srd/alignments`** (added 2026-07 audit) — `srd/alignments.json` exists but no route serves it; the forge's alignment picker expects it alongside the other `/v1/srd/*` lists. Trivial.

**Goal / deliverable.** Grill the *design*, then **rewrite the temp reference mockup itself** — `docs/ui-temp-reference/project/Cairn App v2.html` → a new **`Cairn App v3.html`** (keep v2 as history). The rewritten mockup is the **replicable visual spec** any coder (human or LLM) builds from later. We are **NOT** grilling frameworks — which library it's finally built in (React SPA / Next / etc.) is a build/deploy concern, deferred out of this slice. The **functional analysis** below (SSE events, screens, Phase-B cuts) is aesthetic-independent and holds regardless.

**Why a rebuild:** v2 is a ~Slice-2 snapshot. It predates combat (6), zones (9), companions (7), death/recovery, inspiration, rests, the worlds/templates restructure, and the ~30-event SSE stream. The screens are beautiful shells whose *data contracts and interactions* no longer match the engine.

#### Engine grounding (facts the rebuild is derived from)

- **Hierarchy:** `World` (setting + its lore = the "Codex"; `world_bible_entry` + `world_lore_chunk` RAG) → `CampaignTemplate` (published scenario in a world, with `premade_characters` attached) → `Campaign` (owner's playthrough; `current_act_index`, `settings`, `member_ids`) → `Character` → `Session` → `Scene` (Act/Scene structure).
- **Turn interaction:** `POST /v1/sessions/{id}/turns` → **SSE stream**; skill checks come back as a `check_required` event → player rolls client-side → `POST /v1/sessions/{id}/turns/{turn_id}/resolve` with the submitted d20 (+ `inspiration_roll` for advantage = take max). Rests: `POST …/short-rest`, `…/long-rest`. Combat state: `GET …/combat`.
- **SSE event vocabulary (~30) the play screen must render:** `token`, `turn_start`, `turn_end`, `turn_advanced`, `check_required`, `roll_result`, `combat_started`, `combatant_added|removed|knocked_out`, `damage_applied`, `healing_applied`, `condition_applied|removed`, `effect_applied|removed`, `concentration_started|broken|check_passed`, `death_save_rolled`, `massive_damage_death`, `pc_death_recovered`, `campaign_ended`, `inspiration_granted|spent`, `time_advanced`, `character|monster|npc` (entity snapshots).
- **Auth reality:** just an `X-User-Id` header today. Real auth (Clerk/JWT) = Phase B / Slice 14; tiers + billing = Slice 14.5. The reference still *draws* login/tiers as visual-only.
- **Zone dependency:** `combatant_moved` / `opportunity_attack` / `zones` events **do not exist yet** — Slice 9 (tactical zones) is reimagined-but-unbuilt. The **zone battle-map component depends on Slice 9 landing.** Until then, combat renders initiative + action economy + enemy states without positioning.

#### LOCKED design decisions (grilled 2026-07)

1. **Scope — full ground-up rebuild.** New layouts *and* new visual language. The v2 "grimoire" direction is discarded. Every screen redesigned.

2. **Visual direction — "Cartographer's Table."** The app is a surveyor's kit for a world that remembers ("a cairn marks the trail; the world remembers, the trail extends"). Deliberately avoids the three AI-design tells (cream+terracotta serif / black+acid-green / broadsheet hairlines).
   - **Palette = 5 handcrafted themes, one kit** (decided 2026-07, after v3 mockup review). Structure, type, and the signature never change between themes — only the light. Every theme keeps the same two-accent semantics: **signal** (you-are-here / primary action / danger) and **trail** (known / positive / done). Signal is vermilion `#D6552B` in all dark themes; Daylight deepens it for contrast. All implemented as CSS-variable swaps (~15 vars).

     | theme | bg | panel | line | text | signal | trail | mood |
     |---|---|---|---|---|---|---|---|
     | **Slate survey** (default) | `#141A1E` | `#1B2329` | `#2E3A40` | `#E7E2D4` | `#D6552B` | `#7E8F6E` | moonlit, cool |
     | **Lamplight** | `#191510` | `#211B13` | `#3C3122` | `#EAE2CB` | `#D6552B` | `#8A9166` | field journal by lamplight |
     | **Blackwood** | `#121813` | `#19221B` | `#2E3C31` | `#E5E4D0` | `#D6552B` | `#94A47D` | night camp under firs |
     | **Gilt** | `#14100A` | `#1C1610` | `#3A2F1C` | `#E9DFC4` | `#D6552B` | `#C9A04C` | v2 homage — gold takes the *trail* role, never the signal |
     | **Daylight** | `#E8E3D2` | `#EFEBDC` | `#C8C0A8` | `#262218` (ink) | `#BC4720` | `#5C6B47` | survey paper, light mode |

   - **Theme switch placement:** canonical picker = **Account → Appearance** (swatch row). A duplicate compact swatch row sits at the bottom of the in-campaign **Settings tab under an explicit "this device, not this table" divider** — themes are a client-side per-device preference (localStorage now, user profile in Phase B), **never** part of campaign settings / the Slice 10 settings payload.
   - **Type:** **Space Grotesk** (labels/UI) · **Newsreader** (DM prose) · **Space Mono** (coords/data). Identical across all themes.
   - **Signature:** the campaign *is* a waymarked trail — cairns/waypoints down a contour-lined spine, topographic texture, signal-colored "you are here." Identical across all themes.

3. **Global shell — "Waymarked rail."** The left nav *is* the trail (signature == navigation). Top of rail = live campaign trail (acts → scenes as waypoints, current scene = vermilion "you are here"); campaign tabs (Character · Party · Lore · Map · …) dock below. Pre-campaign the rail shows top-level destinations (Campaigns · Codex · Account).

4. **Play screen (the hero) — "Reading column + field-notes margin."**

   ```
   [ trail | Aldric  HP 24/32  AC 16  (vitals strip) ]
   [ rail  |------------------+----------------------]
   [       |  DM prose,       |  FIELD NOTES         ]
   [   |   |  centered        |   - Present -        ]
   [   *   |  reading measure |   Old Grim           ]
   [   |   |                  |   The Stranger       ]
   [       |  > your action   |   - Known -          ]
   [ tabs  |                  |   Kael - Mill Rd     ]
   [       | [ input ........]|  (combat: fills rich)]
   ```
   DM prose is centered at a real reading measure; the persistent right **field-notes margin** (surveyor's marginalia) holds live state and **goes rich in combat**.

5. **Event rendering (exploration) — "Pure prose, mechanics to the margin."** The reading column stays *pure prose* (immersion). The ~30 mechanical events **tick in the field-notes margin** (HP deltas, conditions, concentration, time). **Baked-in refinements (not re-grilled):** (a) the margin **pulses subtly on change** so an off-to-the-side beat isn't missed; (b) **narratively-pivotal** events (`death_save_rolled`, PC `combatant_knocked_out`, `massive_damage_death`, `campaign_ended`) *also* get a brief **inline announcement** in the column — those are story, not bookkeeping.

6. **Dice / skill checks — "Modal moment."** `check_required` pops a single focused overlay (die · DC · mod) — the one sanctioned break from the quiet prose. **Inspiration** offered as "spend for advantage = roll two, take higher" (maps to `resolve` with `inspiration_roll`). Client animates/submits the roll; result logs to the margin, outcome streams in prose.

7. **Combat — "Mode-switch; map takes center-right."** On `combat_active` the screen re-proportions (mirroring the engine's own hard mode-switch):

   ```
   [ INIT: Aldric > Stranger > Guard          Round 1 ]
   [--------------------+-----------------------------]
   [  prose log         |   ZONE MAP  (Tavern Front)  ]
   [  (compressed)      |     o -----far----- o       ]
   [  Grim's blade..    |   Aldric          Guard     ]
   [                    |     (half cover +2)         ]
   [--------------------+-----------------------------]
   [ YOU: ○A ○B ●R  MOVE 30/30FT   ⌁hint ⌁hint       ]
   [ [ input ....................................... ]]
   ```
   Initiative strip on top · compressed prose log left · **zone node-map** center-right (**node graph, not a grid** — Slice 9) · **read-only economy readout** on the bottom (no action selectors, no End Turn — see Decision 9; this sketch originally drew `[Attack][Move][Dash]` buttons and was corrected 2026-07). Biggest build in the slice; **the zone map is gated on Slice 9.**

8. **Character creation — BOTH: premade fast-path + custom forge.** A choice screen: **left = pre-built**, **right = build your own.** _(Sub-forks grilled & LOCKED 2026-07.)_

   **The determinism line is already half-drawn by the backend schema** (`CharacterCreate` in `api/v1/schemas/characters.py`):
   - **Deterministic / engine-validated (the numbers):** `ability_scores` are **hard-locked to the standard array `[15,14,13,12,10,8]`** — the validator *rejects* anything else, so **no point-buy and no dice-rolling for stats in v1** (BG3 allows both; we do not — the UI must reflect standard-array-only). `race`/`subrace`, `character_class`/`subclass`, `background`, `skill_choices`, `spell_choices`, `alignment` are discrete picks validated against the live SRD endpoints (`/v1/srd/*`).
   - **Free-text (the story):** `name`, `bio`, `personality`, `voice_traits` are loose text columns, no validation.
   - **Portrait:** `portrait_url` exists on the model but is **not** in `CharacterCreate` — set *after* creation. **No image-gen anywhere in the backend today.**

   **LOCKED — Premade fast-path:** 4–5 character cards in a row (from the template's `premade_characters`; each `sheet` is a full `CharacterCreate` shape + bio prose — real content: name, race/class/background, alignment, ability scores, skills, personality, voice, bio). Interaction: **expand-in-place dossier** — click a card and it grows into a full field-dossier (portrait · stat block · bio prose) while the others shrink to a **thumbnail rail** down the side; click any thumbnail to swap the open dossier; **"Take this one"** confirms (clones the sheet into a `Character`, stamps `created_from_premade_id`).

   **LOCKED — Custom forge (deep, "Baldur's-Gate-3-grade"):** full video-game-quality flow — race, class, subclass, background, **alignment**, abilities (standard-array assignment), skills — everything choosable/trackable via the SRD endpoints. The numbers are **locked pickers**; the identity fields are **free text + optional AI assist**:
   - **"Weave from a prompt"** — the player writes a short concept (*"grizzled ex-soldier, haunted by a siege"*); an LLM fills `bio` + `personality` + `voice_traits`; the player **edits the result**. Mechanics are never touched by the Weave. → **NEW backend dependency: a "Weave" agent** (concept prompt → structured `bio`/`personality`/`voice_traits`). Player may also just type the fields themselves; AI assist is optional, not mandatory.

   **LOCKED — Portrait slot:** the frame shows three affordances — **Gallery** (curated art pack) and **Upload** (your own image) both **work in v1**; a **"Generate portrait"** button is **designed but flagged** as a later capability. _Earmarked cheap path when enabled:_ **Replicate FLUX-schnell (~$0.003/img)** (vs. OpenAI `gpt-image-1` ~$0.04/img; local SD needs a GPU → kills the cheap-VPS plan). Generation itself is a **from-scratch backend capability** (new provider + key + image agent) and stays out of v1 build to protect the $5–15/mo cap.

9. **Review round (2026-07, after the first v3 build — user feedback pass, synced against the roadmap so the UI renders *planned* engine truth, not just current code).** Full detail lives in the build brief; the decisions:
   - **Flow map is part of the spec.** Every screen must be reachable in-app (the mockup's buttons now actually navigate); the brief carries the canonical flow diagram. **Recap (20) is the threshold** — resuming a campaign always lands there first, never mid-session; first-ever session skips it. Billing is reached from Account (canonical) + a Settings model-tier upsell link.
   - **Landing page (new screen 0)** — public first-visit page, separate from the logged-in campaign browser. Hero = the signature made literal (a trail inks itself across contours to a vermilion "you are here").
   - **World browser is two-level** (was a flat template list) — honors `World → CampaignTemplate`: world cards (mood + canon stats) → rich scenario detail (2-para premise, lore quote, **act-teaser trail with later acts veiled**, world-canon figure chips, premades). Teaser only, never the lore.
   - **Combat interaction synced to the engine:** the typed message IS the whole turn — `combat_resolver` spends the economy and calls `advance_turn` itself. **No End-turn button, no Attack/Move/Dash selectors**; the bar is a read-only A/B/R + feet readout with optional text-insert chips. **Zone map = the DM's napkin sketch**: irregular regions carrying Slice-9 anatomy (cover / difficult ×2 / hazard) with distance-labeled edges. **Suggest-mode proposal band** renders `companion_action_proposed` (confirm/override).
   - **Character sheet redesigned as "the dossier, grown up"** — big portrait + bio prose header, **slot-based inventory** (carried-on-the-body slots + pack grid, drag-to-equip; dep #5) + **spellcasting section for casters** (slot pips, prepared rows, long-rest re-prep). Party cards/drawer got the same soul pass (epithets in prose, reason-log leads, voice line; numbers demoted).
   - **Forge mocks all 8 steps** as clickable panels (race/class/background = flavor-prose pickers, alignment 3×3, abilities array, skills chips, identity + Weave, portrait).
   - **New "moments" screens for already-planned engine features that had no UI:** **level-up** (21 — `level_up_pending` → band chip → HP roll/average + ASI/feat, `POST …/level-up`), **epilogue** (22 — `campaign_ended` / completed-card entry; record stays open read-only; hardcore `ended_dead` variant), **loot** (23 — veil overlay, per-item `POST …/loot` + take-all loop). These render Slice 4/6 features — no new backend scope beyond deps #4–5.

10. **Consistency audit (2026-07, second review round — every screen re-diffed against the backend code + the grilled slices).** Gaps found and fixed in the mockup + brief:
   - **Casters were unbuildable.** The forge now carries three **conditional steps** (dimmed on the trail until the road calls): **Subrace** (9 SRD subraces), **Subclass** — the creation service *hard-rejects* a cleric/sorcerer/warlock without one (`SUBCLASS_LEVEL` = 1; wizard/druid 2, rest 3; SRD ships one subclass per class), and **Spells** (`spell_choices` — cantrips + day-one list). The old "subclass is chosen later" copy was factually wrong for three classes.
   - **Pickers are SRD-complete:** 9 races / 12 classes / 13 backgrounds (were 6/6/4 samples).
   - **Spell-prep overlay (new screen 24)** — the long-rest re-prep prompt (`POST …/prepare-spells`) Slice 4 promised; known-spell casters never see it.
   - **Reaction prompt (new screen 25)** — renders the planned reaction engine's interactive round-trip (`reaction_prompt` SSE → recommendation + countdown → `POST …/reactions`, timeout auto-applies); `reaction_control` (ai/suggest/player) added to the Settings Advanced list.
   - **Codex gained the Days tab** (the `GET …/calendar` "calendar sidebar" this slice owed) **+ a search field** (`GET …/lore?q=`).
   - **Combat gained the inspiration-spend chip** (the combat-path `use_inspiration` toggle Slice 6 explicitly punted to this slice); level-up gained the **caster knobs** (new spells + subclass-at-level); rest screen notes the **`rest_blocked` / risky-gate** states.
   - **Sample-data + contract fixes:** XP corrected to 2890/2700 (940 couldn't trigger `level_up_pending`); the combat sketch's "???" blob became a seeded zone (zones are all known at init — `???` stubs belong to the exploration map only); verbosity labels aligned to `terse|normal|lush`.
   - New backend dep **#6: `GET /v1/srd/alignments`**. Doc fixes landed in the same pass: Slice 7 locked-decision #5 (stale "raw number in drawer"), Slice 4 short-rest hit-dice bullet (superseded by the one-click auto rest), the Decision-7 ASCII action bar (predates Decision 9), and route-name drift (`/short-rest`, `/long-rest`, `/resolve`).

11. **Second review round (2026-07 — the v4 revision).** The user re-reviewed the audited v3; the verdict was a *pattern* critique, not a content one — three habits were over-used (card grids, terse unexplained chips, veil modals). **`Cairn App v4.html` + `docs/ui-temp-reference/v4-build-brief.md` supersede the v3 files** (kept as history). Four **interaction principles** now govern the whole spec (brief → "Interaction principles"):
   - **Every rules noun is inspectable** — a popover with its SRD text opens on hover/tap of any spell, condition, item or feature (answers "what does Mage Armor do" everywhere; text from `/v1/srd`, zero new backend).
   - **Pickers are a list + a reading pane**, not a card grid — forge race/subrace/class/subclass/background rebuilt (terse rows to scan, a full SRD page + granted traits + "what this choice asks next" box to understand); spells keep multi-select chips but gain the same pane ("first click reads, the check commits").
   - **Modal policy: a veil only when the game can't continue without the answer AND the answer doesn't need the table.** Dice (11) keeps its veil. **Loot (23) became an inline spoils card riding the log** — a result, not a decision; it never blocks the story. **Reaction (25) became an interrupt bar over the fully visible board** — you must see the aisle and the stair to decide, so a curtain was self-defeating. **Spell prep (24) became the last page of the long rest** — a rest-morning play screen, not a popup ambush.
   - **Mode changes happen under the narration, never as a cut** — new screen **12a "into-combat"** designs the explore→combat moment: the prose continues past a "steel is drawn" pivot, the light drops a step, the initiative ribbon slides in, the DM's sketch **unfurls complete** where the field notes stood (all zones seeded at init), the economy bar rises; the same moves run in reverse when the last foe falls. Combat begins *inside* a turn — no page swap exists to cut to.
   - Other v4 reworks: **landing (0) is a scrollable page whose spine is the trail** — waypoints are real product moments (a rendered turn exchange with streaming tokens + field-note chips, a codex card + self-drawing mini-map, the your-rules cards, a closing CTA); the abstract "set out → choose → you are here" hero dropped. **Codex left the global rail** (it is campaign memory; pre-campaign rail = Campaigns · Account only). **Party (16) = fireside roster + the same full sheet component as the PC** — the lossy dossier drawer is gone; companion-only additions ride the sheet (leash band Directed/Suggest/Free-rein, "how she holds you" reason-log, voice chips). **Level-up (21) walks exactly the asks the preview names** (step strip ①HP ②improve ③seal; a card states what is NOT asked; ASI allocator = 2 points each +1/+2, engine-validated; caster asks join the same walk, slots appear unasked). **Inventory = the carried ledger** (STEEL / HANDS / WORN groups whose AC arithmetic visibly sums; sample corrected to chain shirt 13 + DEX 1 + shield 2 + Defense 1 = AC 17 — the old chain-mail sample never added up) — **dep #5 (slot taxonomy) retired**: grouping needs only `equipped` + SRD item data, and equipping stays a *sentence to the DM*, not a drag.
   - New backend dep **#7: subrace spell grants** — the creation service applies subrace ability bonuses + proficiencies but not racial spells (high-elf cantrip); grant it server-side or the forge pane drops the claim.

12. **Third review round (2026-07 — landing rebuilt, the drop, the Drafting Room).** The user's verdict on v4: the homepage was still the biggest drag ("upper part is good… everything below is questionable at max, also no footer, not visual or unique enough"), plus two asks — an alive→dying transition ("some red skull somewhere") and an admin surface for authoring worlds/scenarios. All three built into `Cairn App v4.html` (now **30 screens, s00–s29**):
   - **Landing (0) rebuilt on the thesis "the page is a session."** Diagnosis of the failure: below the hero the old page *explained* the app with shrunken components — a landing must *perform*. Now one continuous played campaign ("eleven days at a river ford, in four turns") reveals at reading pace down the trail spine: DM prose streams in when each beat scrolls into view, and **the margin writes itself the way the codex does in play** — Ilse Marrow's card inks in when the prose names her (day 3), field notes record the player's own d20, combat brushes the page under a dusk gradient (day 9), and the closing beat is **the callback**: the player asks what they have on Marrow and the DM answers from eleven days of ledger while the margin shows *the same card, eleven days on*, grown by two dated lines. The spine terminates in the sign-up button; a real colophon footer follows (brand, links, SRD CC-BY-4.0 credit, working theme dots). Scroll reveal = IntersectionObserver + `.lit`; JS-off degrades to fully visible.
   - **New screen 12b "the drop" (s27)** — alive→dying as 12a's dark twin, same principle (a mode change under the narration, never a cut): the hit lands in the log, "Ser Aldric falls — 0 HP," **the board drains to grey while the story keeps its ink**, a **cartographer's hazard stamp** (red skull in a stamped ring — a map marker, not a game-over splash) presses onto the sketch corner, the ribbon keeps moving, and the death ledger (3 hold-dots / 3 skull-fails) rises where the action bar stood. Settles into 14 · downed; runs in reverse at 1 HP. Backend already supports it (death recovery in the turn pipeline; saves roll through the dice veil, dep #2).
   - **The Drafting Room (s28–s29)** — the admin authoring surface that replaces `cli/seed.py` with a door; a third pre-campaign rail tab marked ADMIN. Grounded in the real tables: `campaign_templates.status` (draft|published) already exists — "players browse only published" is enforcement, not new modeling; `world_lore_chunks` carries category/tags/`always_on`/nullable `embedding`, so the editor shows per-chunk embedding state and puts the cost of always-on **on the toggle itself** ("rides every prompt — spend it on almost nothing"). Worlds list + per-world canon editor + scenario acts card.
   - New backend dep **#8: auth + `is_admin`** — there is no users table at all yet; the Account tab already presumed auth, and the Drafting Room adds the admin flag to the same dep. Until then `cli/seed.py` remains the only writer.

#### Forks — ALL RESOLVED 2026-07 ✅ (grill complete; v3 built + review round applied — see Decision 9)

- ~~**Character creation**~~ — **RESOLVED 2026-07** (see Decision 8): premade = expand-in-place dossier + thumbnail rail; custom = locked-picker numbers + free-text identity with optional "Weave from prompt" agent; portrait = gallery+upload in v1, Generate flagged (FLUX-schnell). New backend deps recorded: Weave agent + (later) image-gen provider.
- ~~**Death / recovery / rests / concentration**~~ — **RESOLVED 2026-07.** Persistent character state lives in a **slim character band** (thin always-visible strip at the reading column's edge: portrait · HP bar · condition chips · inspiration token · concentration chip · **Rest** button). Rests are **one-click narrated streams** (`rest_applied`/`rest_blocked` mechanical event → SceneNarrator prose → `rest_end`; short-rest takes no body, hit-dice spend auto). Concentration = a persistent chip in the band ("holding Bless"), `concentration_broken` also surfaces inline (pivotal). **Downed state takes over the band** with the 3-successes / 3-failures death-save track; `massive_damage_death` = instant, no track. Death/recovery beats are pivotal → inline prose + band takeover.
  - ⚠️ **BACKEND TWEAK NEEDED (player-rolled death saves):** death saves must be **player-rolled**, not auto-rolled. Today `roll_death_save` (`domain/services/combat/rolls.py:65`) rolls server-side via `rng.randint(1,20)`. Change it to route through the **same client-roll → `/resolve` pattern as skill checks**: emit a `check_required`-style prompt for the death save, the client rolls the d20 in the dice modal (or a band affordance) and submits it, the server applies the submitted roll to the 3/3 track. Keep the same outcome logic (≥10 success, nat 20 → 1 HP, nat 1 → 2 failures). _Tracked as an engine tweak this slice surfaces — not a pure-UI change._
- ~~**Pre-play screens**~~ — **RESOLVED 2026-07.**
  - **Codex = in-play discovery journal.** Keyed off the existing `GET /v1/campaigns/{id}/lore` (WorldBibleEntry, filterable by type: people/places/factions/history). Starts sparse, fills as LoreKeeper writes entries for what the player actually encounters — **spoiler-safe by construction**. **No new endpoint.** Pre-play, a template card shows only a **short authored teaser blurb**, never the full lore. (Honors discovery + no-context-pollution ethos.)
  - **Home / browser:** `GET /v1/campaigns` lists your playthroughs; starting a new one needs a **template-browse endpoint** (`GET /v1/campaigns/templates` — still to build; already in the retained surface checklist). Template detail shows premise · length · premades · teaser lore.
  - **Campaign creation — foregrounded framing vs. Settings-tab.** Slice 10 makes **all campaign settings** editable anytime (`PATCH …/settings`, resolved-per-turn merge) — nothing is technically locked at creation. The create flow is `POST /campaigns` (name+template) → immediately `PATCH …/settings` with the chosen framing values (no new endpoint). The **creation screen foregrounds three framing choices** (all still editable later in Settings): **① Agency preset** (Narrative/Balanced/Tactical) · **② Death mode** (pacifist/narrative/hardcore) · **③ Content & tone** (violence/gore/sexual/romance/horror/substances off·fade·on + hard-no `lines` + `tone_note`). Passive-check modes and narration verbosity live only in the Settings tab. Account tier is managed separately in Account/Billing.
- ~~**Party / companions**~~ (Slice 7) — **RESOLVED 2026-07.**
  - **Approval surfacing:** vague **bands only** at a glance ("cold"/"warming up"/"loyal"); **the raw integer is never shown** (meta-info — decided with the user, resolving the Slice-7 line-1086 contradiction). Drawer's Approval section = band + the **colored reason-log** (green delta>0 / red delta<0, each with its reason string like "Burned the village down") **without numeric deltas/total**. Integer stays server-side.
  - **Party at a glance:** companions ride in the **slim character band** (the Decision-8/vitals band) as mini-avatars — mood-tinted, vague band label under each — beside the PC. Mirrors how combat's initiative strip already lists them.
  - **Companion drawer** (click an avatar): full sheet (companions are real `Character` rows, `is_companion=True`) + Approval section (above) + `mood` + `personal_goal`. **`secret` is never shown to the player.**
- ~~**Settings tab**~~ (Slice 10) — **RESOLVED 2026-07; model ownership corrected 2026-07-10.** One tab, editable anytime, backed by `GET/PATCH /v1/campaigns/{cid}/settings`: **agency preset radios** (Narrative/Balanced/Tactical) · **death-mode** · **content toggles** (per-category off/fade/on) + `lines`/`tone_note` box · **narration verbosity** · a collapsible **Advanced** section for per-companion agency sliders + passive-check modes (+ reaction control after Slice 10.5). Header shows the merge state as **"Balanced · N custom"** (preset tag + count of sparse overrides — never a magic "custom" preset). The three creation framing knobs (agency/death/content) reappear here as the canonical home; the create screen is just an up-front subset. The v4 mock's model picker/per-agent model overrides are stale and must not be rebuilt.
- ~~**Session summary · cheatsheet · exploration map**~~ — **RESOLVED 2026-07.**
  - **Recap** — "previously on…" on resume, from `Session.summary` + `/calendar` day-summaries. Render existing data, no new endpoint.
  - **Cheatsheet** — UI-side "current state at a glance" aggregation: active threads (Scene `unresolved_threads`, Slice 8), current objective, reachable exits. Composed from data already on the wire.
  - **Exploration map (signature payoff of "Cartographer's Table"):** an **auto-laid-out node graph of *discovered* locations** — nodes = places visited, edges from `Location.connections` (adjacency-only, **no coordinates** → frontend lays it out), current location highlighted, unvisited-but-known exits shown as `???` stubs; click a node to inspect / travel. **Reuses the same node-graph visual language as the combat zone-map** (Decision 7) for consistency — the two maps are the visual through-line of the whole direction. Grows as you explore. This is the thematic core, not just polish; it earns the "Cartographer's Table" name. _(Real layout work — the biggest non-combat component; a force-directed / dagre-style auto-layout over the adjacency graph.)_
- ~~**Phase-B visual-only**~~ — **RESOLVED 2026-07: draw the full set** (login · account/security · **tiers/billing**), all in the Cartographer's Table language, **clearly flagged "Phase B — not wired."** Purely design-language completeness. **The billing model is specified in Slice 14.5:** one Free / Plus / Pro account tier automatically controls the hosted model bundle and feature caps for every campaign. Free = Luna + 1 campaign + tight cap; Plus adds task-routed Terra + more campaigns + image-gen; Pro adds Sol narration. Local Qwen is developer-only; BYOK is a separate future account feature. The tiers/billing screen renders `GET /v1/plans`; campaign Settings has no model controls. Prices are placeholder. These screens sit outside the playable path and are the last thing built.
- ~~**Deliverable mechanics**~~ — **RESOLVED 2026-07.** Deliverable = a new **`Cairn App v3.html`** in `docs/ui-temp-reference/project/`, keeping `Cairn App v2.html` alongside as history. **DM "thinking" = diegetic only:** during agent latency the field-notes margin shows an in-world shimmer ("the DM considers…", quill/dice motifs) with **no agent names and no pipeline exposed** — the v2 "DM Thinking" agent-status panel is **dropped**. The machinery stays invisible; the margin is field notes, not a debug console. (No dev-trace toggle in v3; not a Slice-10 setting.)

---

**Below: the pre-grill surface checklist (retained).** Still valid as *what* each screen must expose (API surface / data contracts); the locked design above governs *how* it looks and lays out. The original `_Depends on: … Slice 14 (auth)_` framing is superseded by the Phase-A framing above.

Implement the UI from the Claude Design handoff (`cairn-ui-light-reference` in repo root).

**Decide first (UI-design questions that change API surface):**

- Campaign discovery — `GET /v1/campaigns/templates` shape: premise, length estimate, premade characters, teaser lore?
- SSE reconnect — partial response replay from `Turn.id`?
- Combat tracker — read `combat_state` JSONB or add structured combat-state endpoints? Lean JSONB; frontend renders.
- World bible visibility — players see discovered lore (filtered by `revealed_at_turn_id`).
- Companion sheet — same view as PC, read-only.
- Inventory UX — ~~simple list with equipped badge; drag-and-drop v2~~ ~~slot-based inventory (Decision 9)~~ **superseded again 2026-07 (Decision 11): the carried ledger — STEEL/HANDS/WORN groups from `equipped` + SRD data, AC arithmetic visibly summed, equipping is a sentence to the DM. Slot-taxonomy dep retired.**
- Loot UX — ~~"Loot body" button… opens a modal~~ **superseded 2026-07 (Decision 11): an inline spoils card riding the narration log, never a modal.** Per-item take (POST `/v1/sessions/{id}/loot`), "Take the rest" loop, actionable while the fallen foe lies in scene. Looted items appear in the player's inventory unequipped.
- Level-up flow — multi-step form (HP / ASI-feat / spells / subclass).
- Prepared-caster spell flow — daily prep prompt after long rest.
- Campaign end UX — "campaign complete" screen with epilogue + `CAMPAIGN_CONCLUDED` content.
- Settings tab — preset radios + advanced gameplay/agency overrides per Slice 10; no model controls.
- Suggest-mode combat — proposal modal with Confirm / Override.
- Approval indicator — vague band ("very upset" / "warming up" / "loyal") per Slice 7 decision.
- NPC profile drawer — when player asks "tell me about Old Grim" or hovers/opens NPC card, show what's been revealed (filtered by `revealed_at_turn_id` like the lore book).
- Scene state visualization — small UI hint when a thread is unresolved or a hidden detail exists (no spoilers, just "something here you haven't fully explored"). Decide whether to surface this at all in v1.
- In-game time display — show on session UI.

**Build:**

- Landing + auth → campaign browse → character creation/pick → game UI.
- Game UI: SSE rendering, character sheet, combat tracker (with zones), world bible panel, companion sheet (with approval band), settings tab, inventory, level-up flow.
- Character creation form (race, class, background, abilities = standard array picker, skills, name/bio/alignment).
- Death-mode and preset selection at campaign creation.

**Ideas (not scoped yet — think about when we get here):**

- **BYOK UI in Account** — provider/key configuration belongs to the account surface from Slice 14, never Campaign Settings.

---

### Slice 15.5 — Frontend architecture & build (Phase A)

_Grilled 2026-07. The **engineering companion to Slice 15**: Slice 15 locks **what the app looks like** (the "Cartographer's Table" visual spec — 30 screens, ~30 SSE events, 5 themes, the node-graph maps); this slice locks **how it's built** (framework, state, data flow, folder structure, production floor). It does not re-open any Slice-15 design decision. Depends on: the playable engine (Slices 1–10.7) for the REST + SSE surface; Slice 15 for the visual spec. **Auth is NOT a dependency** — Phase A runs on the `X-User-Id` shim (see decision 6)._

**Deliverable.** A `frontend/` app (sibling to `backend/` in the same repo) rendering the Slice-15 spec against the live engine, such that **a full session is playable end-to-end** (pick/forge a character → play turns with streaming prose + margin ticks → combat → rest → level-up), verified by a Playwright e2e run.

#### Locked stack (grilled 2026-07)

| Concern | Choice | Rationale |
|---|---|---|
| Build / runtime | **Vite + React 19 + TypeScript**, pnpm, Node 22 LTS | Fast, standard, no meta-framework tax |
| Routing | **TanStack Router** (SPA) | Type-safe routes; the "not Next" modern path; no SSR server to pay RAM for on the VPS |
| Server state | **TanStack Query** | Cache/invalidation for all REST; pairs natively with the router |
| Client state | **Zustand** | Thin store for session/streaming/theme — no Redux ceremony |
| Styling | **Tailwind v4** | The 5 themes become `@theme` + `data-theme` CSS-var swaps — keeps the exact mockup tokens, zero hand-rolled CSS |
| Primitives | **React Aria Components** (Adobe), skinned 100% in Tailwind | Unstyled → **no default look to read as "shadcn slop"**; best-in-class a11y/keyboard. No uniform component kit. |
| Distinctive UI | Character-ful components cherry-picked **per-component** + **soundcn** for sound | Avoids the flat one-kit look; sound layer (fallback howler.js / use-sound) |
| Forms | **React Hook Form + Zod** | The 8-step forge; Zod mirrors backend validation |
| API types | **openapi-typescript** off FastAPI `/openapi.json` | Typed REST client generated from the backend — no drift |
| Maps | **React Flow** (`@xyflow/react`) + custom node components + dagre/elk layout (d3-force optional) | Dedicated library, not hand-SVG; nodes are our React components → napkin/cartographer look, pan/zoom free |
| Animation | **Motion** (Framer) | Mode-changes-under-narration, the drop, streaming reveals; `prefers-reduced-motion` honored |
| Test | **Vitest + RTL + MSW + Playwright** | Playwright = the playable-session gate; MSW mocks REST *and* SSE |
| Lint / format | **Biome** | One fast tool, replaces ESLint + Prettier |

#### Locked decisions (the grill)

1. **Rendering — Vite SPA, client-rendered.** The backend is a separate FastAPI service and the app is 100% behind-login + SSE-streaming, so Next / TanStack-Start SSR buys nothing and costs a Node server against the $5–10/mo cap. The one page wanting SEO — the "page is a session" landing — is **statically pre-rendered at build**.

2. **SSE client — `fetch` + `ReadableStream`.** Turns are `POST`, so `EventSource` (GET-only) is out; a `fetch()` + `ReadableStream` reader parses SSE frames into **one typed discriminated union** over the ~30 event kinds. `token` events append to an ephemeral streaming buffer in Zustand; the ~29 structured events (`damage_applied`, `condition_applied`, `combatant_moved`, …) reduce into the **Query cache** (combat / character / scene), so the field-notes margin and combat board simply read Query data.
   - **Reconnect = refetch, drop tokens.** On a mid-turn drop, Query refetches `/combat` `/character` `/scene` — mechanical truth never desyncs; the in-flight prose paragraph is lost. **No backend dependency.** (This resolves the roadmap's open *"SSE reconnect — replay from Turn.id?"* — full replay is **deferred**, not built.)

3. **State split.** Query owns all server/persistent state; Zustand owns the ephemeral (streaming token buffer, active-turn status, theme, transient UI). Theme persists to `localStorage` (as the mockup already does — a per-device preference, never in the campaign settings payload).

4. **Components — headless + our skin, no kit.** React Aria Components for behavior/a11y, skinned 100% in Tailwind from the mockup tokens; distinctive components cherry-picked per-component; sound via soundcn. Deliberately avoids the shadcn-default "LLM slop" look (we may reuse shadcn's *theming/registry plumbing*, never its component styles).

5. **Maps — React Flow, custom nodes.** Both the combat **zone map** (3–6 nodes, static per fight, the DM's napkin sketch with cover/hazard icons + distance-labeled edges) and the **exploration map** (grows, needs pan/zoom, laid out from `Location.connections`) use React Flow with bespoke node components + auto-layout (dagre/elk; d3-force optional for organic drift). Backend sends **adjacency only, no coordinates** → the frontend lays out. The live zone-map data depends on **Slice 9** landing (`zones` / `combatant_moved` / `opportunity_attack` events); until then combat renders initiative + economy + states **without positioning**.

6. **Auth — deferred to Phase B, seam built now.** Phase A: an `authProvider` returns the `X-User-Id` dev header → a playable session with **no users table**. Phase B (Slice 14): the same provider returns `Bearer <clerk-jwt>` → real login + `is_admin` (dep #8) as a **one-module swap**. The admin Drafting Room waits for Phase B.

7. **Hosting — Vercel (Hobby) for now.** Static SPA on Vercel, API on the VPS. Split-origin, but header-auth (no cookies) reduces it to **a single CORS allowlist** on the API; SSE works cross-origin. Fully reversible in an afternoon to **Cloudflare Pages** (budget-safe: no non-commercial / $20-Pro catch) or **Caddy-on-VPS** (same-origin, no CORS). _A budget-correct deploy slice (single VPS + docker-compose + Caddy fronting the API, spend caps, eval-in-prod) **replaces the retired AWS deploy slice** and is still to be written._

8. **API layer.** `openapi-typescript` generates types from the backend spec → a thin typed `fetch` client → hand-written TanStack Query hooks per feature. The SSE event union is **hand-typed** (SSE is not in OpenAPI).

#### Folder structure

```
frontend/
  src/
    routes/            TanStack Router tree (lazy → route-level code-split)
    features/
      play/            reading column + field-notes margin, SSE turn loop
      combat/          initiative, economy readout, React Flow zone map
      character/       sheet, carried-ledger inventory, spellcasting
      forge/           8-step creation (RHF + Zod), Weave assist, premade fast-path
      codex/           discovery journal, days tab, search
      party/           roster, companion sheet, approval band
      campaign/        world/scenario browser, creation framing, recap
      settings/        agency / death / content / model-tier
      admin/           Drafting Room (visual in A; live in Phase B)
    shared/
      ui/              React Aria + Tailwind primitives (our skin)
      api/             generated types, fetch client, SSE reader, Query hooks, authProvider
      lib/             theme, sound, motion, formatting
    styles/            Tailwind v4 config + the 5 theme CSS-var definitions
  tests/e2e/           Playwright (playable-session gate)
```

#### Build order

1. **Scaffold** — Vite + TS + Tailwind v4 + Biome + pnpm; the 5-theme CSS-var system from the mockup; the React Aria primitive skin in `shared/ui`.
2. **API layer** — openapi-typescript codegen, typed fetch client, SSE reader + event union, Query setup, the `authProvider` seam (`X-User-Id`).
3. **Shell** — TanStack Router tree, the waymarked rail, the statically pre-rendered landing.
4. **Play** — reading column + margin, the SSE turn loop, dice modal, rules-noun inspect popovers.
5. **Character** — forge (RHF + Zod), premade fast-path, the grown-up dossier sheet.
6. **Combat** — the mode-switch, initiative, economy readout, React Flow zone map (live positions gated on Slice 9).
7. **The rest** — codex, party, settings, campaign browser/recap, and the moments (level-up, epilogue, loot, spell-prep, reaction).
8. **Admin** — the Drafting Room (visual; wired in Phase B).
9. **Test + ship** — Vitest/RTL components, MSW fixtures, the Playwright playable-session e2e; CI gate; Sentry + source maps; deploy to Vercel.

#### Verify

- `pnpm build` → static bundle deploys to Vercel; the SPA loads against the VPS API with **one** CORS allowlist entry.
- **Playable-session Playwright e2e (the definition of done):** pick a premade → start a campaign → submit a turn → prose streams token-by-token while mechanical ticks land in the margin → a skill check pops the dice modal, the roll submits, the outcome streams → combat begins (mode-switch, initiative, economy) → win → short rest → margin state correct throughout.
- Simulated SSE drop mid-turn → board + margin refetch correct, no desync.
- `tsc --noEmit`, Biome, and Vitest green in CI; route bundles code-split; `prefers-reduced-motion` disables Motion; keyboard-only navigation works (React Aria).

#### Deferred (Phase B / later)

- Real auth (Clerk) + users table + `is_admin` → the Drafting Room goes live (Slice 14 / dep #8).
- Billing / tiers screens wired to a real model (visual-only in Phase A).
- SSE full replay-from-`Turn.id` (backend per-turn event log + replay endpoint).
- The Slice-15 backend deps #1–7 (Weave agent, player-rolled death saves, portrait image-gen, `GET /v1/campaigns/templates`, `GET /v1/srd/alignments`, subrace spell grants).
- **A budget-correct deploy slice** (single VPS + docker-compose + Caddy fronting the API, spend caps, eval-in-prod) — replaces the retired AWS deploy slice.

#### Backend-deps checklist (Slices 15 / 15.5)

Consolidates every backend gap the UI grill surfaced, so the frontend isn't blocked mid-build. Build the **Phase-A blockers** before/alongside the frontend; the rest are Phase B or retired.

| # | Dep | For | Status | Where / effort |
|---|---|---|---|---|
| 4 | **`GET /v1/campaigns/templates`** — worlds with scenarios nested (premise · length · premades · teaser lore) | Campaign browser / new-campaign flow | **Phase A — blocker** (can't start a campaign from the UI without it; dev can bootstrap via `make seed` in the meantime) | new route in `api/v1/routes/campaigns.py` |
| 6 | **`GET /v1/srd/alignments`** — serve the existing `srd/alignments.json` | Forge alignment picker | **Phase A — trivial** | new route in `api/v1/routes/srd.py` |
| 7 | **Subrace spell grants** — creation service applies subrace ability/prof bonuses but not racial spells (high-elf cantrip) | Forge correctness for spell-granting subraces | **Phase A — small** | character creation service in `domain/services/` |
| 1 | **Weave agent** — concept prompt → structured `bio` / `personality` / `voice_traits` | Custom-forge AI assist | **Phase A — soft** (forge works with manual text; can land in parallel) | new `agents/weave.py` + `prompts/weave/v1.md` + `models.yaml` entry |
| 2 | **Player-rolled death saves** — route `roll_death_save` through the client-roll → `/resolve` pattern (keep outcome logic) | Dice-modal death-save UX | **Phase A — soft** (auto-roll works today, but it's the wrong UX) | `domain/services/combat/rolls.py:65` + a `check_required`-style prompt |
| 3 | **Portrait image-gen** — Replicate FLUX-schnell (~$0.003/img) | "Generate portrait" button | **Phase B** — flagged affordance; Gallery + Upload work in Phase A | new provider + key + image agent (from scratch) |
| 8 | **Auth + `is_admin`** — no users table exists at all yet | Real login + the Drafting Room admin gate | **Phase B** (Slice 14) — Phase A runs on the `X-User-Id` shim | users table + Clerk + `is_admin` flag |
| 5 | ~~Equipment slot taxonomy~~ | (drag-to-slot inventory) | **RETIRED** (Decision 11 — the carried ledger needs only `equipped` + SRD data) | — |

**"Green light to build the frontend" = #4 done** (or bootstrap via seed for now); **#6 / #7** are quick wins; **#1 / #2** land in parallel with the forge / combat features that consume them. **#3 / #8** are Phase B; **#5** is dead.

---

## Future / out of scope for v1

### Advanced combat mechanics

- **Readied actions** — needs `readied_action: {action, trigger}` state.
- **Legendary actions / lair actions / legendary resistance** — boss mechanics, post-turn hooks.
- **Summoned creatures** — Conjure Animals, Find Familiar. Temporary combatants linked to summoner.
- **Wild Shape / Polymorph** — full stat-block replacement.
- **Two-weapon fighting** — bonus attack with light weapons. Needs equipped-weapon awareness.
- **Grapple / Shove** — `resolve_contest` covers mechanic; LLM needs prompting.
- **Darkness and invisibility** — disadvantage vs unseen. Needs spatial visibility model.

### Game systems

- **Multiclassing logic** — schema is multi-ready in v1 (`Character.classes`); v1 enforces single class. v2 unlocks: ASI per-class, multiclass spell-slot table, prerequisites.
- **Inter-companion relationships** — companion-to-companion approval matrix. v1 is PC-to-companion only.
- **Romance arcs** — full BG3-style romance. Contentious, defer.
- **Faction reputation** — numerical standing for social checks / pricing.
- **Economy** — shops, prices, enforced transactions.
- **Crafting** — out of scope.
- **Weather and seasons** — environmental effects on travel and checks. (Time-of-day is in v1 via `in_game_datetime`.)

### Platform features

- **Save slots** — multiple manual saves per campaign. v1 has implicit auto-save (session persists in DB).
- **Portrait generation** — Replicate / Bedrock image gen. `portrait_url` field exists.
- **True multiplayer** — shared live consequences in one campaign. Schema is multi-ready (`Campaign.member_ids`); routing + concurrency design deferred.
- **Mobile / Unity / Discord clients** — v1 is web-only. The MCP server (Slice 10.7) already exposes the engine, so a second client can drive Cairn over MCP without new backend surface.
- **Go rules-engine port** — defer until v1 is stable + a non-Python client is committed. Python is the source of truth for v1.
- **Standalone / Go seeding CLI** — the current seed runner (`cli/seed.py`, run via `make seed`) lives in the backend and reuses the Python ORM models and `db/queries`, which is why it's cheap. A separate CLI (Go or otherwise, outside `backend/`) only makes sense once authoring is exposed as an HTTP admin API — then any client can drive it without duplicating schema knowledge or talking to Postgres directly. Sequence: build the authoring admin endpoints first (likely alongside the admin UI), then a thin external CLI becomes trivial. Until then, keep seeding in Python where the schema lives.
- **Lore book search and visualization** — basic lore listing in v1; rich graph visualization later.
- **Group skill checks** — "everyone roll stealth" with half-or-more pass rule. v1 handles individual checks + Help action; group is v2.

### Test coverage

- Unit tests for turn graph nodes (conftest patches the entire graph).
- Load testing — none planned for v1.

---

## Decisions resolved 2026-05

Log of design questions that were open before this revision, with the resolution and the slice the work landed in. Kept here so the rationale isn't lost.

| #   | Question                                                | Resolution                                                                                                                                                                                                                                                                                            | Slice                                       |
| --- | ------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 1   | Player agency: pure character-driven vs hybrid vs meta? | Hybrid — both explicit and implicit roll requests valid; same intent.                                                                                                                                                                                                                                 | Locked design; Slice 3 already supports.    |
| 2   | Combat spatial model: theater / zones / grid?           | Zones with close/far/out_of_range categories; 3–6 per scene.                                                                                                                                                                                                                                          | Slice 9.                                    |
| 3   | World model: curated single world + templates?          | Confirmed. World = canon, template = scenario, campaign state diverges per playthrough.                                                                                                                                                                                                               | Slice 5.                                    |
| 4   | Companion combat control default?                       | Per-campaign settings slider. Default = AI (Narrative preset).                                                                                                                                                                                                                                        | Slice 10.                                   |
| 5   | Companion non-combat agency?                            | Preset (Narrative/Balanced/Tactical) + per-system overrides (combat, dialogue, equipment, leveling, checks).                                                                                                                                                                                          | Slice 10.                                   |
| 6   | Passive Perception trigger?                             | Eligibility-based per noticing event (DM decides who can notice); roll against eligible character's passive. Silent on success, weave into narration. Per-campaign override.                                                                                                                          | Slice 6.                                    |
| 7   | Rest mechanics in v1?                                   | Both short and long rests; safety-level gate.                                                                                                                                                                                                                                                         | Slice 4.                                    |
| 8   | Concentration enforcement?                              | System-enforced in `apply_damage`. DC = max(10, dmg//2).                                                                                                                                                                                                                                              | Slice 6.                                    |
| 9   | Death and revival?                                      | PC death → death save → mode-dependent. Companion death → death save → status=dead, story revival only. No items.                                                                                                                                                                                     | Slice 6.                                    |
| 10  | TPK / death handling?                                   | Per-campaign mode: hardcore / narrative / pacifist. Default narrative. No save slots in v1.                                                                                                                                                                                                           | Slices 6 + 10.                              |
| 11  | Multiclassing in v1?                                    | Schema multi-ready (`classes` array); single-class enforced. v2 lifts.                                                                                                                                                                                                                                | Slice 5.                                    |
| 12  | Spell preparation modeled?                              | Yes — `prepared_spells` distinct from `spells_known`; daily prep on long rest.                                                                                                                                                                                                                        | Slices 4 + 5.                               |
| 13  | Inspiration mechanic?                                   | v1, binary flag, system-enforced advantage.                                                                                                                                                                                                                                                           | Slice 6.                                    |
| 14  | In-game time?                                           | `Session.in_game_datetime`; advanced by travel/rest/scenes; long rest needs 8h elapsed + safe location.                                                                                                                                                                                               | Slices 5 + 4.                               |
| 15  | Multiplayer in v1?                                      | Single-player. Schema multi-ready (`Campaign.member_ids`).                                                                                                                                                                                                                                            | Slice 5.                                    |
| 16  | RulesLawyer context payload?                            | Subject character full sheet + thin party manifest (names, classes, key skill mods). "Subject" = character making the check; PC by default, companion if delegated. RulesLawyer is non-combat only; combat uses tools directly.                                                                       | Slice 3.                                    |
| 17  | Help action in v1?                                      | Yes — RulesLawyer can return a `helper` suggestion. Group checks are v2.                                                                                                                                                                                                                              | Slice 3.                                    |
| 18  | Context compression strategy?                           | Scene summaries (already locked) + last-N turn window + RAG over world bible. Implementation lands across Slices 5, 6, 13.                                                                                                                                                                            | Slices 5/6/13.                              |
| 19  | Seedable RNG?                                           | Yes — `Session.rng_seed`; services read from `random.Random(seed)`.                                                                                                                                                                                                                                   | Slice 5.                                    |
| 20  | Companion depth in v1?                                  | Merged into NPC narrative depth: companions use the same rich `NarrativeProfile` schema, plus a `companion_meta` layer (approval / mood / personal_goal / secret). `adjust_approval` tool, injected into dialogue and ally_ai. Inter-companion relationships, romance = v2.                           | Slice 7.                                    |
| 21  | Ability score generation?                               | Standard array only for v1. Point-buy / rolled = v2.                                                                                                                                                                                                                                                  | Locked.                                     |
| 22  | Ship template?                                          | Future content; tracked in template ideas roadmap, not a code slice.                                                                                                                                                                                                                                  | —                                           |
| 23  | Go / MCP port?                                          | **MCP resolved** → server locked as Slice 10.7 (FastMCP, `/mcp` on FastAPI, registry-driven). **Go** port stays deferred through v1 — revisit when v1 ships + a non-Python client commits.                                                                                                             | Slice 10.7 (MCP); Go —                       |
| 24  | Pre-commit hooks?                                       | Slice 11 (operational hardening).                                                                                                                                                                                                                                                                     | Slice 11.                                   |
| 25  | RulesLawyer combat vs non-combat — same agent?          | Non-combat only. Combat uses `roll_skill_check` / `roll_saving_throw` tools directly; no agent. No separate prompts needed.                                                                                                                                                                           | Slice 3 clarifies.                          |
| 26  | Passive Perception scope — PC only, or party?           | Eligibility-based per noticing event. DM agent receives full party perception profile (passives, languages, profs, backstory tags) and decides who can perceive what. Some things universal (highest passive wins), some class/race/knowledge gated, some PC-only. No blind whole-party-max.          | Slice 6.                                    |
| 27  | NPC depth: thin fields vs rich profiles?                | Rich `NarrativeProfile` schema replaces thin fields. Multi-page authored backstory, goals, prejudices, relationships, private facts. Same schema for premade NPCs, builder-generated NPCs, and companions. No mechanical dialogue gating — LLM holds the facts in prose and reveals through behavior. | Slice 7.                                    |
| 28  | Builder agents for unauthored content?                  | NPC builder (3-tier: background/recurring/major) and Scene builder. No act builder in v1 — acts are authored only.                                                                                                                                                                                    | Slices 7 (NPC builder) + 8 (Scene builder). |
| 29  | Scene depth and pacing?                                 | Layered authoring (atmosphere / surface / hidden / secrets / NPCs with current beats / threads / hooks). Runtime state (discovered_facts, threads, beat_count, tension, mood). SceneNarrator pacing rules; Scene Director nudges. One fully authored example per template as the bar.                 | Slice 8.                                    |
| 30  | Authoring discipline expectations?                      | Major NPCs and authored scenes are many-page documents, not stubs. Template authoring is real work owned by us in v1. Player-authored templates v2. Templates that ship thin will play thin no matter how good the prompts.                                                                           | Locked.                                     |
