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

**Reactions are system-detected, not LLM-detected.** Reaction bus fires deterministically. (Slice 6.)

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
- `POST /v1/sessions/{id}/short_rest` route.

**Build (long rest):**

- `apply_long_rest(session_id)` tool — full HP, all slots, all resources, half max HD restored, exhaustion -1, **re-prepare spells** (for prepared casters), advance `in_game_datetime` by 8 hours.
- `POST /v1/sessions/{id}/long_rest` route.

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
- **Short rest hit dice** — PHB allows multiple HD per short rest. Keep one-at-a-time via repeated `roll_hit_die` calls; player decides when to stop.

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

`npcs_present` source for Slice 6: `npc_queries.list_by_location(campaign_id, location_id)`. Slice 7 will introduce per-scene NPC presence and we will switch the source then.

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
  - `POST /v1/sessions/{id}/turns/{turn_id}/resolve-check` body grows `use_inspiration: bool = False`.
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
  - PHB constraint (subdue only valid for melee attacks) honored via prompt instruction in Slice 6; mechanical enforcement deferred to Slice 9 with weapon-range awareness.
- **Combatant cap fix**: replace `range(20)` in combat_resolver with `range(len(combat_state["combatants"]))`. One-liner.
- **Combat resolver inner-loop failure** (Slice 11 owns the full fix; Slice 6 only adds the event): wrap the resolver tool loop in `try/except`. On any exception, emit `combat_step_failed` event with `last_successful_step`, `error_class`, `error_msg`; re-raise so the route layer can return 500 + partial state in the SSE stream. No transactional wrapping in Slice 6 — Slice 11 chooses rollback vs document.

#### Routes — added, changed, removed

- **Removed**: `POST /v1/sessions/{id}/combat/start`, `POST /v1/sessions/{id}/combat/end`. Delete cold — no deprecation period (no frontend consumes them yet; Slice 15 will use the natural-language path). Drop `CombatStartRequest` and `CombatEndRequest` schemas. Tests rewritten to drive the full graph (preferred) or call `combat_service.state.start/end` directly (unit-level coverage).
- **Kept**: `GET /v1/sessions/{id}/combat` — needed by the Slice 15 combat tracker UI.
- **Changed**: `POST /v1/sessions/{id}/turns/{turn_id}/resolve-check` body grows `use_inspiration: bool = False`. Existing behavior preserved when omitted.
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
| Reaction bus infrastructure                                                          | Slice 9               | Nothing in Slice 6. Slice 9 designs alongside its first real consumer (OA on zone exit). Concentration auto-save does NOT use the bus — direct branch in apply_damage. |
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
7. DM grants inspiration during a roleplay moment: `grant_inspiration` tool call → `Character.has_inspiration=True`. Player POSTs to resolve-check with `use_inspiration=true` → spend service flips flag false, roll uses advantage.
8. Pacifist-mode PC takes 1000 damage at HP=5: HP clamped to 1; no death save, no events for instant death.
9. Hardcore-mode PC takes lethal damage and fails death saves: combat ends, `resolve_pc_death` sets `Campaign.status="ended_dead"`, `campaign_ended` event emitted. Next mutation request returns 409 / `campaign_ended_dead`. GET routes still work.
10. Narrative-mode PC death: HP=1 at combat end, `pending_recovery` set, world bible consequence written. Next turn's SceneNarrator narrates the wake-up.
11. Subdue attack on enemy with melee weapon: enemy unconscious + stable + alive; `combatant_knocked_out` event.
12. Massive damage instant-kill: PC at HP=5 takes 60 damage (max_hp=50). HP=0, `excess=55 >= max_hp=50`, instant death, no save sequence (modulo death_mode in pacifist where clamp fires first).
13. Failed pickpocket on alive NPC: resolve-check sets NPC.disposition=hostile deterministically; no auto-combat.
14. Currency loot: `POST /loot` with `{"currency": {"gp": 5}}` moves 5 gp from NPC to character; insufficient balance returns 400.
15. New campaign + custom character: first 3 turns render with `intro_mode=true` (SceneNarrator weaves in backstory); turn 4+ resumes normal play silently.
16. Companion speaks via dialogue: player addresses companion by name, IntentRouter routes to npc_dialogue intent, \_resolve_dialogue finds companion via fallback, dialogue agent responds.
17. Combat-resolver tool failure mid-loop: `combat_step_failed` event emitted; 500 returned with partial state in SSE stream.
18. Long rest happens, post-response pass tries to also advance time: `time_advanced` event already in `Turn.events` from rest service → post-response skips, logs.
19. Time advancement: Scene Director only sets `time_advance_hours > 0` when also setting `scene_transition_push`. Mid-scene narration does not advance time.
20. `POST /v1/sessions/{id}/combat/start` returns 404 (route deleted); `GET /v1/sessions/{id}/combat` still returns combat state for the Slice 15 tracker.

---

### Slice 7 — NPC + companion narrative depth

_Depends on: Slice 5 (schema, scene model), Slice 6 (dialogue rename)._

Today an NPC has thin narrative fields (`bio`, `personality`, `disposition`) and a companion is a `Character` with `is_companion=True` and nothing else. This slice replaces both with one rich, prose-driven profile schema that applies uniformly to authored NPCs, builder-generated NPCs, and companions. **This is the foundation slice for narrative quality.** Without depth here, dialogue plays thin, companions feel like followers, and scenes have nothing to riff on.

The mental model: every NPC and every companion is a **real person**. Authored ones are written as many-page documents. Builder-generated ones come out lighter but follow the same shape. The dialogue agent never sees a stat block — it sees a person.

**Build (schema — `NarrativeProfile`):**

A `NarrativeProfile` is a JSONB blob attached to NPCs and (for `is_companion=True`) characters. Schema:

```yaml
name: str
race: str
age: int
profession: str

physical: str # multi-paragraph: build, features, posture, scars, dress

personality:
  str # multi-paragraph: observed behaviors, not labels.
  # "Watches before he speaks" not "introverted".

voice:
  accent: str
  pace: str
  vocabulary: str
  speech_quirks: list[str]

backstory:
  str # multi-page prose: 5+ years of past, key events,
  # losses, formative incidents

goals:
  immediate: str # what they're doing today / this week
  midterm: str # this season, this year
  life: str # the thing that drives them

prejudices:
  list[str] # specific, justified — "Distrusts wizards
  # because a battlemage at Crown's Reach hesitated
  # on a cast and the line broke."

relationships: # named individuals — alive, dead, missing, estranged
  - { name, relation, status, notes }

private_facts:
  list[str] # things they know but don't volunteer.
  # NOT mechanically gated. LLM judges when to surface.

disposition_toward_party: enum # mutates via play, recorded via LoreKeeper

# For is_companion=True, layer on top:
companion_meta:
  approval: int # -100 to 100, starts at 0
  mood: enum # content | happy | upset | scared | angry | inspired | dejected
  personal_goal:
    str # what this companion specifically wants from the
    # journey — drives their behavior and reactions
  secret: str | None # something they hold close. Surfaces in trust.
  approval_log: list[{turn_id, delta, reason, total}] # last 20 entries
```

The schema is the same for premade and generated. Tier determines depth, not shape.

**Build (storage):**

- `NPC.narrative_profile: JSONB` replaces the existing thin fields (or augments them — decide during build whether to migrate `bio`/`personality`/`disposition` data into the new shape and drop the columns, vs. keep them populated alongside). Lean toward migration + drop.
- `Character.narrative_profile: JSONB` for `is_companion=True`. `companion_meta` lives inside it.
- Schema validation at write time. Allow incomplete profiles (background NPCs) but enforce required top-level fields (`name`, `personality`, `voice`).

**Build (NPC tier system):**

- `NPC.tier: enum (major | recurring | background)`.
- Authoring rule: authored NPCs are typically `major` or `recurring`. Generated ones default to `background`; promote to `recurring` once engaged in >2 dialogue turns. Promotion triggers an LLM pass to deepen the profile.

**Build (NPC builder agent):**

`agents/npc_builder.py` + `prompts/npc_builder/v1.md` — heavy agent, called rarely.

```
In:
  - World lore relevant to the location
  - Location (cultural context, factions present)
  - Role in scene (innkeeper / patron / guard / informant / ...)
  - Tier requested (background / recurring / major)
  - Existing NPCs in the area (avoid duplicates and conflicts)
  - Scene atmosphere

Out:
  - Full NarrativeProfile (depth scaled to tier — background NPCs get
    a 3-sentence personality and a paragraph of backstory; recurring
    NPCs get multi-paragraph everything; major is rare and basically
    template-author territory)

Persistence:
  - LoreKeeper writes the new NPC to the world bible
  - On re-encounter, prior interactions retrievable via RAG (Slice 13)
```

The builder is a slow, deliberate agent. Frontier tier model. Called once per new NPC, not per turn. Output is permanent.

**Build (dialogue agent rewrite — replaces the gated_share mistake):**

`prompts/dialogue/v1.md` is rewritten to consume `NarrativeProfile`. The prompt explicitly forbids the failure modes that gating was trying to prevent:

```
The character below is a real person. You have their full profile —
backstory, prejudices, relationships, private facts. Roleplay them.

RULES:
- Stay in character. Behavior is your roleplay output.
- Do not list facts. Reveal through behavior, partial answers,
  deflections, body language, silences.
- Surface private_facts only when the player has earned it in the
  scene — through trust, persistence, leverage, or shared vulnerability.
  Use your judgment. Some scenes warrant disclosure quickly; most don't.
- Never invent facts not in the profile. If asked something not in
  your knowledge, say so or evade in character.
- Pursue your goals. NPCs don't just answer questions — they have
  their own conversation goals. Push them.
- Honor your prejudices. They shape your reactions.
- Companion-specific: your approval and mood color every reaction.
  Low approval → curt, withdrawn, sarcastic. High approval → open,
  protective, supportive.
```

The dialogue agent receives the full `NarrativeProfile` of the entity speaking, plus the active PC's profile for context, plus the last N turns of the current scene.

**Build (`adjust_approval` tool + service):**

- `services/companions.py::adjust_approval(db, *, character_id, delta, reason, turn_id)` — clamps to [-100, 100], appends to log, recomputes mood via `derive_mood(approval, recent_events)`.
- `adjust_approval(character_id, delta, reason)` tool — DM-callable. Returns new approval, new mood, threshold crossings.

**Build (`scene_narrator` and `ally_ai` integration):**

- `scene_narrator/v1.md` rewrite — receives profiles of all NPCs and companions in scene. Drops companion reactions (1–2 sentences) in narrative turns when their approval/mood/personal_goal/prejudices are touched by the moment. Sparingly, but meaningfully.
- `ally_ai/v1.md` rewrite — receives companion's full profile + current approval/mood. Low-approval companions in combat hesitate, refuse risky support, drop sarcasm. High-approval companions take risks for the PC. Behavior emerges from profile, not from `if approval < 0: refuse_help`.

**Build (templates — authoring discipline):**

- `seed/templates/tavern_v1/npcs/old_grim.yaml` — fully authored, many-page profile as the bar. Edrik, Anneth, Maren, Captain Vell, Tomas the smith all referenced. Backstory written as continuous prose, not bulleted facts.
- All other tavern_v1 NPCs upgraded to at least `recurring` tier depth.
- `seed/templates/tavern_v1/companions/<name>.yaml` for each premade companion at the same authoring bar.

**Fix:**

- **`NPC.find_by_name` fuzzy match risk** — first alphabetical match by substring. Replace with ranked match + scene-aware filter (current scene's NPCs first). Was on Slice 6 list; fits better here once profiles exist.
- **`NPC.disposition` writes to world bible on change** — captured via LoreKeeper. "old_grim_disposition: neutral → hostile after party refused payment." Was on Slice 6 list; lands here.

**Decide:**

- **Migration strategy** — drop `bio`/`personality`/`disposition` columns vs. keep alongside `narrative_profile` for transition? Lean drop + migration script; cleaner long term.
- **Approval scope** — PC-to-companion axis only in v1 (decided). Inter-companion matrix = v2.
- **Auto-triggered approval changes** — codify ~5 obvious ones (PC heals companion → +5; PC violates companion's stated value → -10) that fire via reaction bus. Rest is LLM judgment via tool. Confirm the 5.
- **Approval surfaced to player** — vague band UI ("very upset" / "warming up" / "loyal"), not numbers. Confirm.
- **Builder tier depth caps** — exactly how long is a `background` profile vs. `recurring` vs. `major`? Set rough word-count targets so the builder doesn't drift. Lean: background ≈ 200 words, recurring ≈ 800, major = authored only (>2000).
- **Generated NPC promotion** — exact trigger for `background → recurring` (>2 dialogue turns)? Or DM-judged? Lean trigger-based for predictability.
- **Backstory consistency across builder calls** — when builder generates an NPC, it should not contradict world bible. Inject relevant bible entries at build time. Spec the retrieval here.

**Verify:**

- Authored Old Grim, when played, behaves consistently: refuses to volunteer about Maren on first ask, may share after the player demonstrates earned trust within the scene. Speech matches voice profile. Reacts to mage characters with measured distrust.
- A scene with one NPC and a quiet PC produces 3–5 turns of natural conversation before resolution — the NPC pushes their agenda, asks back, deflects.
- Builder generates a `background` tier patron when the party enters an unauthored tavern. Patron is persisted; party returns next session, patron remembers prior conversation.
- Companion with approval -40 in combat refuses to spend their daily ability on the PC. Same companion at +60 volunteers it.
- Approval log shows last 20 changes with reasons.
- No dialogue agent response ever lists facts as bullets or exposition dumps.

---

### Slice 8 — Scene depth + pacing

_Depends on: Slice 5 (Scene model), Slice 6 (Scene Director, DM persona), Slice 7 (rich NPCs to populate scenes)._

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

This is illustrative. Real authored scenes are bigger — atmosphere is many paragraphs, every NPC has a current beat, threads are richer, hooks branch deeper. **Authoring discipline is the contract.**

**Build (scene runtime state):**

On the `Scene` table:

```python
discovered_facts: list[str]     # what the party has actually learned
                                # in this scene. SceneNarrator MUST NOT
                                # describe anything outside this list as
                                # known to the party.
unresolved_threads: list[str]   # threads_in_air that haven't been resolved
                                # — locked drawer, evasive NPC, missing smith
beat_count: int                 # number of player turns spent in this scene
tension_level: int              # 0-10, escalates with conflict, decompresses
                                # with rest and resolution
mood: enum                      # quiet | charged | hostile | intimate
last_revelation_at_turn: int    # for pacing — when did something new happen?
```

Updated by tools called by SceneNarrator and Scene Director:

- `mark_discovered(fact)` — append to discovered_facts, update last_revelation_at_turn
- `add_thread(thread)`, `resolve_thread(thread)` — mutate unresolved_threads
- `set_tension(value, reason)` — Scene Director sets based on events
- `set_mood(mood)` — DM-callable

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
  check has been passed (use the discovered_facts list as source of truth).
- Secrets MUST NOT appear unless their unlock condition is in
  discovered_facts.

WITHHOLDING:
- You are given the full scene authoring. You MUST NOT describe what
  the party has not yet engaged with or perceived. Use discovered_facts
  as your single source of truth for what the party knows.

NPC PRESENCE:
- NPCs in scene have an agenda (npc_agendas_in_scene). They push their
  own interest. They ask questions back. They deflect on sensitive topics.
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

Scene Director (built in Slice 6) reads `beat_count` and `tension_level` and injects pacing nudges into the SceneNarrator context:

- `beat_count < 5` and exploration mode → "stay descriptive, let them probe"
- `beat_count > 15` with no new discoveries since `last_revelation_at_turn` → "this scene needs a beat — drop a hook, advance an NPC's agenda, or let a hidden detail surface through environmental cue"
- `tension_level > 7` → "escalation point; consider combat trigger, NPC turn hostile, or major revelation"
- Tension and beat soft-nudges only; never force resolution. Player owns scene length.

**Build (scene builder agent):**

`agents/scene_builder.py` + `prompts/scene_builder/v1.md` — for unauthored locations.

```
In:
  - Location (description, cultural context)
  - Act context (what's happening this act, what's recent)
  - Recent events (last N world bible entries)
  - NPCs known to inhabit this location (or generate via npc_builder)
  - Time of day, weather, atmosphere hints
  - Tier (light fill / fuller fill — most are light)

Out:
  - Full authored-shape scene YAML (lighter than a major authored scene
    but with all required keys: atmosphere, npcs_present with doing/
    attentive_to, surface_details, threads_in_air, hooks_out, npc_agendas)
  - Persisted as a Scene row, can be returned to
```

Heavy agent. Slow. Called when the DM moves the party somewhere new without an authored scene. Output is permanent — once a generated scene exists, future returns use the same scene with mutated state.

**Build (LoreKeeper extension for scene events):**

- When a scene reveals a hidden detail or secret → LoreKeeper writes an `EVENT` entry tagged with the scene and turn.
- When a thread resolves → LoreKeeper writes a `RELATIONSHIP` or `EVENT` entry describing the resolution.
- When a scene ends → `Scene.summary` written (already in Slice 5); LoreKeeper extracts canonical facts to the world bible.
- All scene events tagged with `revealed_at_turn_id` for the lore-book visibility filter (Slice 13).

**Build (authoring discipline — one fully authored example):**

- `seed/templates/tavern_v1/scenes/back_room_with_grim.yaml` — fully layered scene at the authoring bar. Many paragraphs of atmosphere, several hidden details with distinct DCs, multiple secrets with branching unlock conditions, NPCs with active beats and agendas, multiple hooks out.
- Tutorial section in the template authoring guide: "what a layered scene looks like."

**Decide:**

- **Where scene state lives** — direct columns on `Scene` table vs. `Scene.runtime: JSONB`. Lean direct columns for queryability and migration discipline.
- **Beat count hard cap?** — if a player spends 50 turns in one room, does Scene Director start forcing escalation, or trust the player? Lean soft nudges, never hard limits. Player owns scene length.
- **Scene builder output review** — generated scenes get LLM-reviewed for quality before persisting? Or trust the builder? Lean trust + flag for player feedback ("this scene felt thin" → log for prompt-tuning).
- **discovered_facts granularity** — one entry per discovered detail, or grouped? Lean one entry per detail, free-text content. Easier to dedupe and reference.
- **Authored vs generated scene quality gap** — how do we keep generated scenes from feeling shallow vs. authored? Honest answer: they will be shallower. Builder prompt should be tuned to maximize layering, but a scene authored over 3 hours of human effort will always beat one generated in 30 seconds. v1 accepts this; major scenes are authored.

**Verify:**

- Player enters Old Grim's back room. First response is atmospheric (smell, light, sound, mood). At most 2-3 specific details. Not a feature dump.
- Player asks Grim about his son. Grim deflects in-character — does not list facts about Maren even though they're in his profile. Conversation continues.
- Player rolls Insight, succeeds. SceneNarrator surfaces a partial read on Grim's deflection (hint, not full content). LoreKeeper records the insight.
- Player investigates the writing desk. Rolls Investigation 14. False drawer surfaced and added to discovered_facts. SceneNarrator describes the moment of discovery, not bullet-points.
- Companion makes one quiet contextual comment about Grim's mood mid-scene. Not every turn.
- 15+ turns elapse in the scene. Beat count tracked. Scene Director hasn't forced a resolution. Pacing nudges fired twice based on state.
- Scene Builder generates a tavern in an unauthored town. Atmosphere is sensory, NPCs have current beats, threads are in the air. Patron persists; party returns next session, patron remembers prior turn.
- SceneNarrator never describes a hidden detail or secret that hasn't been unlocked.

**Ideas (not scoped yet — think about when we get here):**

- **Adaptive sliding window for "last N turns in scene"** — N tunable based on `beat_count`. Short scenes (≤5 turns) get the whole scene; long scenes get a smaller recent window so older turns compress into a mid-scene checkpoint.
- **Mid-scene checkpoint summaries** — for scenes that run 30+ turns, write a rolling "scene midpoint" summary that compresses the first half. Prevents context bloat without waiting for scene close. Scene-aware compression layer between `recent_turns` and `Scene.summary`.

---

### Slice 9 — Tactical zones + AI movement

_Depends on: Slice 6 (combat polish), Slice 7 (companion profile for ally_ai prompt)._

Zones are the bridge between theater-of-mind ("you're across the room") and grid combat. Zone state lives in `combat_state`. Movement is a tool. Combat AI gets zone context in its prompt. Spells/attacks use SRD ranges mapped to category.

**Build (zone state in `combat_state`):**

- Combat init augments state with:
  ```
  "zones": [
    {"id": "tavern_front", "name": "Tavern Front", "description": "near the door",
     "cover": "none", "difficult_terrain": false, "hazard": null,
     "distances": {"behind_bar": "close", "stairs": "far"}},
    ...
  ]
  ```
- Each combatant's `zone: str | None` set to a zone id when combat starts.
- Zone data sourced from `Location.zones` (already in model). For ad-hoc scenes (e.g., LLM-generated tavern), Scene Director seeds 3–6 zones via a `define_zones` tool.

**Build (zone tools):**

- `move_combatant(combatant_id, target_zone)` — checks: target zone exists, movement budget covers it (close = 30ft, far = 60ft+, depending on `distances`), no condition blocks movement (prone halves, grappled blocks). Updates combatant's zone, decrements movement budget, emits `combatant_moved` event.
- `get_combatants_in_zone(zone_id)` — for AoE targeting; lists combatants currently in zone.
- `get_zones_in_range(from_zone, range_category)` — returns zones at `close` or `far` from the source zone; used by spell/attack range checking.
- `define_zones(session_id, zones: list[{name, description, ...}])` — Scene Director seeds zones when combat starts in a location without predefined zones.

**Build (range mapping for spells/attacks):**

- `services/combat/range.py::srd_range_to_category(srd_range_str) -> "self" | "touch" | "close" | "far" | "out_of_range"`:
  - `"Self"` → self.
  - `"Touch"` or `"5 feet"` → touch (same zone, adjacent combatant).
  - `"15 feet"` to `"30 feet"` → close (same zone or `close`-distance zone).
  - `"60 feet"` to `"120 feet"` → far (any non-`out_of_range` zone).
  - `> 120 feet` → far for v1 (no sniper-tier zones).
- Attack tool (when added) validates `target_zone` reachable from `attacker_zone` by weapon range.
- Spell-casting tool validates `target_zone` reachable from `caster_zone` by spell range.

**Build (cover and terrain — minimal):**

- `apply_damage`/saving-throw tools read target zone's `cover` and apply +2/+5 AC or `+2`/`+5` save bonus (`cover_ac_bonus`, `cover_save_bonus` already in seed).
- `difficult_terrain` doubles movement cost when entering that zone.
- `hazard` (lava, spikes) triggers DM narration (no auto-damage in v1 — DM decides when to trigger).

**Build (combat AI prompt updates):**

- `ally_ai/v1.md` and `enemy_ai/v1.md` rewrites include zone context block:
  ```
  ## Battle map
  You are at: tavern_front (cover: none)
  Allies at: behind_bar (close)
  Enemies at: stairs (far, half cover)
  ```
- AI uses zone language: "I move from tavern_front to behind_bar and shove the guard."
- Spell-range checking is automatic — AI calls `cast_spell(target_zone=X)`, system rejects if out of range with a clear error message the AI can react to.

**Build (UI signal):**

- `combat_state.zones` exposed in combat tracker (Slice 15). Player sees a zone list with combatant icons.

**Fix:**

- **`Locations.zones` data unused** — currently set in seed (`cover`, `cover_ac_bonus`, etc.) but no code reads it. Wire it up.
- **`combatant["zone"] = None`** — fix on combat init: assign a zone based on Scene Director context or fall back to a single default zone.

**Decide:**

- **Distance granularity** — `close` / `far` / `out_of_range` only (decided) vs. adding `medium` for 30–60ft. Stick with three categories for v1.
- **Zone count limit** — soft cap 6 per combat. Beyond that the AI loses track.
- **NPC scene movement (non-combat)** — does it also track zones? **No.** Zones are combat-only in v1; narrative movement is freeform.
- **Opportunity attacks** — when a combatant moves out of an enemy zone, does it trigger an OA? **Yes** if the enemy has a melee weapon and a reaction available. Reaction bus handles via Slice 6 infrastructure.

**Verify:** Combat in tavern initializes with 4 zones, each combatant in a zone. Wizard at `stairs` casts Fireball at `behind_bar` (far distance → in range). Wizard at `stairs` tries to cast Cure Wounds (touch range) on PC at `tavern_front` → tool rejects, AI moves to PC first. Companion in `tavern_front` with half cover takes ranged attack at +2 AC. Sentinel triggers when enemy moves out of melee zone.

---

### Slice 10 — Per-campaign settings + agency presets

_Depends on: Slice 7 (companion depth used by sliders), Slice 9 (combat behavior of sliders)._

Players configure how much agency the AI gets. Per-campaign, set at creation, editable mid-campaign.

**Build (schema is done in Slice 5):**

- `Campaign.settings: JSONB`:
  ```json
  {
    "preset": "narrative" | "balanced" | "tactical",
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
    "death_mode": "hardcore" | "narrative" | "pacifist"
  }
  ```

**Build (preset resolver):**

- `services/settings.py::resolve_settings(campaign) -> dict` — applies preset defaults, then per-system overrides.
- Presets:
  - **Narrative (default)**: companion = AI everything, checks = silent, death_mode = narrative.
  - **Balanced**: companion combat = suggest, dialogue = ai, equipment/leveling = ai, checks = ai. Checks = surfaced. death_mode = narrative.
  - **Tactical**: companion combat = player, dialogue = ai, equipment = player, leveling = player, checks = player. Checks = surfaced. death_mode = hardcore.

**Build (routes):**

- `GET /v1/campaigns/{cid}/settings` — returns resolved settings.
- `PATCH /v1/campaigns/{cid}/settings` — accepts preset OR per-system overrides; merges with current.

**Build (wire into agents/tools):**

- `combat_ai` is only invoked for companion turns when `settings.companion.combat == "ai"`. If `suggest`, server emits `companion_action_proposed` SSE event; player confirms or overrides via existing combat resolver path. If `player`, treats companion as a player-controlled combatant.
- `dialogue` agent invoked for companion only when `settings.companion.dialogue == "ai"`. Else player types companion's lines.
- `passive_perception` setting controls SceneNarrator behavior (Slice 6).
- `death_mode` setting controls `apply_damage` death-path branch (Slice 6).
- `companion.leveling` setting decides who submits level-up choices (Slice 4 hook).
- `companion.equipment` setting decides who can call equip/unequip tools on a companion (defer to Slice 15 if UI not ready).

**Build (UI — Slice 15 dependency):**

- Settings tab in campaign view. Preset radio buttons + collapsible advanced overrides. Slider model per the UI reference in repo.

**Decide:**

- **Mid-campaign change consequences** — if player switches from `narrative` to `hardcore` mid-campaign and PC is at 0 HP, what happens? **Pragmatic:** changes apply going forward; current state unchanged. Document this.
- **Suggest mode UX** — server sends companion's proposed action; client renders "Companion proposes: X. Confirm / Override." Define the SSE event shape now.

**Verify:** New campaign defaults to Narrative preset. Toggle to Tactical: companion combat turns now expect player input. Toggle death_mode hardcore: PC dies → campaign locks. Toggle passive_perception to surfaced: scene entry rolls visible to player. Override single field without losing preset (preset becomes "custom" or remains tagged + overrides logged).

**Ideas (not scoped yet — think about when we get here):**

- **Per-user LLM provider choice** — extend `settings` JSONB with `llm: {provider: "anthropic" | "openai" | "openrouter" | "ollama", model_overrides: {agent_name: model_id}}`. Per-agent overrides are essential (a user picking Ollama as default shouldn't have it drive `scene_narrator` — quality cliff). Preset resolver picks sensible per-provider defaults. BYOK key storage + Ollama localhost URL handling lands in Slice 14; UI in Slice 15.

---

### Slice 11 — Operational hardening

_Depends on: nothing strict. Run before Slice 12 (events for evals); before Slice 15 (SSE for frontend); before Slice 16 (cost controls in prod)._

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

_Depends on: Slice 5 (embedding column + scene bounds), Slice 12 (eval baseline)._

**Decide first:**

- Top-k value — tune against evals.
- Embedding model version — add `embedding_model_version` column on `WorldBibleEntry`.
- Lore search endpoint — `GET /v1/campaigns/{cid}/lore?q=guild` for frontend lore panel. Useful in Slice 15.

**Build:**

- Embedder — sentence-transformers locally, SageMaker in prod.
- Populate `WorldBibleEntry.embedding` on every LoreKeeper write.
- Populate `WorldLoreChunk.embedding` once per chunk (one-shot at seed time and on edit).
- Vector store — pgvector in Postgres locally, S3 Vectors in prod.
- Retrieval before `SceneNarrator` — **two separate retrievals** stitched into the same prompt:
  1. **World lore retrieval** — query = current location + NPCs in scene + active threads; pulls relevant `WorldLoreChunk` rows (faction, region, deity, figure, history). Filters out chunks unrelated to the scenario. Combined with the template's `always_on_lore_keys`.
  2. **World bible retrieval** — query = player input + recent turns; pulls relevant `WorldBibleEntry` rows (campaign-specific NPCs, events, quests, day summaries past the recent-N window). The campaign's own memory.
- Both retrievals tagged in the prompt under distinct headers ("Background lore", "Campaign memory") so the LLM treats them differently — lore is reference, bible is history.
- World echoes — `CAMPAIGN_CONCLUDED` entries from other campaigns retrievable as world history (cross-campaign retrieval, opt-in via setting).

**Verify:** SceneNarrator prompt includes only lore relevant to the current scene (not the full world). DM references a campaign-specific fact from 20+ turns ago. Lore chunks for unrelated regions/factions are absent from the prompt. Prompt discipline holds — DM doesn't force-fit world lore into unrelated scenes.

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

- **BYOK (bring-your-own-key) for per-user LLM provider choice** — encrypted per-user API key storage for the providers picked in Slice 10's `settings.llm`. Backend reads user's keys before LLM calls. For Ollama: user supplies their own localhost URL; backend needs outbound config + clear-warning UX about local-only networking.
- **Per-provider cost tracking** — `Turn.llm_cost_usd` already populated from LiteLLM callbacks. Extend to also tag `Turn.llm_provider` so we can report cost per provider per user (matters for BYOK accounting and OpenRouter routing visibility).

---

### Slice 15 — Frontend

_Depends on: Slices 1–10 (game loop + narrative depth + settings), Slice 14 (auth)._

Implement the UI from the Claude Design handoff (`cairn-ui-light-reference` in repo root).

**Decide first (UI-design questions that change API surface):**

- Campaign discovery — `GET /v1/campaigns/templates` shape: premise, length estimate, premade characters, teaser lore?
- SSE reconnect — partial response replay from `Turn.id`?
- Combat tracker — read `combat_state` JSONB or add structured combat-state endpoints? Lean JSONB; frontend renders.
- World bible visibility — players see discovered lore (filtered by `revealed_at_turn_id`).
- Companion sheet — same view as PC, read-only.
- Inventory UX — simple list with equipped badge; drag-and-drop v2.
- Loot UX — "Loot body" button surfaces when a defeated NPC is in scene. Opens a modal showing the NPC's inventory + currency (read via `GET /v1/npcs/{id}`); player clicks items to take (POST `/v1/sessions/{id}/loot` per item). "Take all" convenience button calls the route in a loop. Looted items appear in the player's inventory list with an unequipped badge.
- Level-up flow — multi-step form (HP / ASI-feat / spells / subclass).
- Prepared-caster spell flow — daily prep prompt after long rest.
- Campaign end UX — "campaign complete" screen with epilogue + `CAMPAIGN_CONCLUDED` content.
- Settings tab — preset radios + advanced overrides per Slice 10.
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

- **Model picker UI in settings** — surfaces Slice 10's `settings.llm` shape (provider + per-agent overrides) + Slice 14's BYOK key entry. Includes a quality-warning band when user assigns a weak model (e.g., Ollama 7B) to a frontier-tier agent (scene_narrator, combat_resolver): "This model may degrade narrative quality — recommended: frontier tier for storytelling agents."

---

### Slice 16 — AWS deploy

_Depends on: Slice 15._

**Build:**

- App Runner or ECS Fargate, Lambda, RDS Postgres, pgvector or S3 Vectors.
- Eval suite runs against deployed env.
- Spend caps + CloudWatch alarms before opening.
- LoreKeeper durable queue (SQS) upgrade from in-process retry.

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
- **Mobile / Unity / Discord clients** — v1 is web-only. Backend is shaped to allow MCP-server wrap when a second client lands.
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
| 23  | Go / MCP port?                                          | Stay Python through v1. Revisit when v1 ships + Unity/mobile commits.                                                                                                                                                                                                                                 | —                                           |
| 24  | Pre-commit hooks?                                       | Slice 11 (operational hardening).                                                                                                                                                                                                                                                                     | Slice 11.                                   |
| 25  | RulesLawyer combat vs non-combat — same agent?          | Non-combat only. Combat uses `roll_skill_check` / `roll_saving_throw` tools directly; no agent. No separate prompts needed.                                                                                                                                                                           | Slice 3 clarifies.                          |
| 26  | Passive Perception scope — PC only, or party?           | Eligibility-based per noticing event. DM agent receives full party perception profile (passives, languages, profs, backstory tags) and decides who can perceive what. Some things universal (highest passive wins), some class/race/knowledge gated, some PC-only. No blind whole-party-max.          | Slice 6.                                    |
| 27  | NPC depth: thin fields vs rich profiles?                | Rich `NarrativeProfile` schema replaces thin fields. Multi-page authored backstory, goals, prejudices, relationships, private facts. Same schema for premade NPCs, builder-generated NPCs, and companions. No mechanical dialogue gating — LLM holds the facts in prose and reveals through behavior. | Slice 7.                                    |
| 28  | Builder agents for unauthored content?                  | NPC builder (3-tier: background/recurring/major) and Scene builder. No act builder in v1 — acts are authored only.                                                                                                                                                                                    | Slices 7 (NPC builder) + 8 (Scene builder). |
| 29  | Scene depth and pacing?                                 | Layered authoring (atmosphere / surface / hidden / secrets / NPCs with current beats / threads / hooks). Runtime state (discovered_facts, threads, beat_count, tension, mood). SceneNarrator pacing rules; Scene Director nudges. One fully authored example per template as the bar.                 | Slice 8.                                    |
| 30  | Authoring discipline expectations?                      | Major NPCs and authored scenes are many-page documents, not stubs. Template authoring is real work owned by us in v1. Player-authored templates v2. Templates that ship thin will play thin no matter how good the prompts.                                                                           | Locked.                                     |
