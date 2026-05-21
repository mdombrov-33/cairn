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

### Slice 5 — World restructure + auxiliary schema

_Depends on: Slice 4._

Restructures `Campaign → Session → Turn` to `World → CampaignTemplate → Campaign → Adventure → Scene → Turn`. Also bundles the v1 schema additions that don't fit elsewhere: multiclass-ready schema, in-game time, RNG seed, multi-user-ready membership, campaign settings JSONB, inspiration flag.

This is the biggest schema slice. Done once, alembic migration is heavy but contained.

**Decide first:**

- **Session lifecycle** — `POST /sessions/{id}/end` route + `Session.ended_at` + `Session.summary` conflict with locked design ("sessions are technical"). Resolution: drop the route, treat sessions as auto-managed play blocks, repurpose `summary` for an internal play-block summary used in context assembly. Lock here.
- **Act length** — aim 20+ hours of play per act, under 200 total. Needs playtesting.
- **Act advancement detection** — explicit `advance_act()` tool. Auditable, no auto-guessing.
- **World bible visibility** — players can see discovered lore via `GET /v1/campaigns/{cid}/lore`. Filtered by what the DM has mentioned (LoreKeeper tags entries with `revealed_at_turn_id`).
- **Adventure layer** — fold into Scene or keep as separate layer. Lean Scene-only (Adventure is bookkeeping over scenes within an act); decide during build.

**Build (data model):**

- `World` model — `name`, `lore` JSONB (factions, geography, history, deities). Seeded by us.
- `CampaignTemplate` model — `world_id` FK, `title`, `premise`, `acts` JSONB (`[{title, premise, core_events: [str]}]`), `status: draft | published`.
- `PremadeCharacter` model — `template_id` FK, full character sheet JSONB.
- `Campaign` updates:
  - Replace string `template_id` with FK to `CampaignTemplate`.
  - Add `status: active | completed | abandoned | ended_dead`.
  - Add `current_act_index: int`.
  - Add `settings: JSONB` (default `{}`, structure defined in Slice 10).
  - Add `death_mode: hardcore | narrative | pacifist` (in `settings` or top-level — decide).
  - Add `member_ids: list[str]` (single-player v1, multi-ready for v2).
- `Scene` model — `campaign_id`, `act_index`, `location_id`, `started_at`, `ended_at`, `summary`, `scene_mode: exploration | combat | social`, `safety_level: safe | risky | hostile`.
- `Turn.scene_id` FK.
- `Session` updates:
  - Add `in_game_datetime: timestamp` (campaign-local fictional time).
  - Add `rng_seed: int`.
- `Character` updates:
  - **Replace `character_class: str` with `classes: list[{name: str, level: int, hit_dice_spent: int, subclass: str | None}]`.** v1 enforces `len(classes) == 1` at creation/level-up; v2 lifts.
  - Add `has_inspiration: bool` (default false).
  - Add `companion_meta: JSONB` (default null; populated for `is_companion=True` in Slice 7 — `approval`, `mood`, `personal_goal`, `secret`).
- `WorldBibleEntry`:
  - Add `embedding: vector` column (nullable; populated in Slice 13 RAG).
  - Add `revealed_at_turn_id: int | None` (player lore-book visibility filter).

**Build (admin tooling):**

- Seed runner — load `seed/templates/{name}/` YAML into DB. `tavern_v1/` already has `locations.yaml` and `npcs.yaml`. Add a campaign template file (premise, acts, core events).
- `make seed TEMPLATE=tavern_v1` command.

**Build (scene hierarchy logic):**

- `SceneNarrator` context updated: current act premise → current scene summary → last N turns within scene + current `in_game_datetime`.
- When scene ends: write summary to `Scene.summary`, advance `in_game_datetime` by scene duration.
- When campaign concludes: LoreKeeper writes `CAMPAIGN_CONCLUDED` world bible entry.

**Build (world bible updates):**

- Add `FACTION`, `SESSION_END`, `CAMPAIGN_CONCLUDED`, `RELATIONSHIP` to `_VALID_TYPES` in `agents/lore_keeper.py`.

**Build (multiclass migration mechanics):**

- Data migration: for each existing character, write `classes = [{name: character_class, level: level, hit_dice_spent: 0, subclass: subclass}]`.
- Update `character_to_dict`, `CharacterCreate`, `CharacterResponse`, all leveling code, all references.
- Validation rule in service: `if len(classes) != 1: raise ValueError("multiclass not supported in v1")` until v2 lifts it.

**Build (RNG plumbing):**

- `domain/services/rng.py::session_rng(session) -> random.Random` returns a seeded instance.
- Refactor combat service callsites to use `session_rng(...)` instead of module-level `random.*`.
- Tests can pass an explicit seed for deterministic assertions.

**Fix:**

- **`Campaign.template_id` string with no FK** — migrate to FK.
- **`PartyMember` is per-session, not per-campaign** — drop the table; derive party from `Character.campaign_id`.
- **`scene_narrator` has no campaign context** — fix in the context update above.
- **`lore_keeper` key generation inconsistent** — inject existing entry keys into the LoreKeeper prompt for match-or-create.
- **`NPC.disposition` never read** — fix in Slice 6 dialogue rewrite + `scene_narrator` context update here.
- **Session lifecycle conflict** — drop the route, document.

**Verify:** Turns have `scene_id`. `SceneNarrator` context bounded to current act + scene. Campaign conclusion writes `CAMPAIGN_CONCLUDED`. `make seed TEMPLATE=tavern_v1` creates a playable campaign. Existing characters migrated to `classes` array without data loss. Same session with same seed produces same dice sequence (RNG determinism test).

---

### Slice 6 — Scene Director + Dialogue rename + Combat polish

_Depends on: Slice 5._

The "make the DM smart" slice. Adds meta-routing, fixes dialogue, lands the combat-polish backlog, ships system-enforced mechanics: concentration, inspiration, passive checks, death modes.

**Build (Scene Director):**

- `agents/scene_director.py` + `prompts/scene_director/v1.md` — new agent, runs before `IntentRouter`.
- Detects: combat triggers (hostile action/NPC), scene transitions, act progression, combat end, in-game-time advancement (travel/rest).
- Tags new scenes with `safety_level: safe | risky | hostile` (used by rest gating, Slice 4).
- `Session.scene_mode` transitions: `exploration → combat` auto-calls `start_combat`; `combat → exploration` on combat end.

**Build (DM persona — foundation; depth comes in Slices 7 + 8):**

- `scene_narrator/v1.md` rewrite — strong DM persona: tone, pacing, style, awareness of campaign genre and current act. Provisional companion context (name, bio, personality, voice_traits) — replaced by full `NarrativeProfile` injection in Slice 7. Layered scene rules and pacing instrumentation come in Slice 8.
- **Passive Perception silent roll on scene entry — provisional implementation.** SceneNarrator calls `_silent_passive_check(subject_char, scene)`; on success, prompt includes "the character noticed: X" → DM weaves it into prose. Per-campaign override: `settings.checks.passive_perception ∈ {silent, surfaced, on_demand}`. The full eligibility-based model (DM receives whole party perception profile + class/race/knowledge gating) lands in Slice 8 when scene depth gives it a proper home.

**Build (`npc_dialogue` → `dialogue` rename + plumbing only — content rewrite is Slice 7):**

- Rename files, agent, prompt; update `models.yaml`, `turn_graph.py`, routes, tests.
- Provisional `DialogueEntity` struct (`name`, `bio`, `personality`, `voice_traits`, `disposition`) — temporary shape, replaced by the full `NarrativeProfile` in Slice 7. Two-step because Slice 6 unblocks dialogue for both NPCs and companions (the existing crippling bug); Slice 7 lands the depth.
- Fix companion lookup — `_resolve_npc_dialogue` falls back to `character_queries.find_companion_by_name` when NPC lookup returns None.
- Fix context plumbing — inject last N turns of current scene + relevant world bible entries (rich profile injection comes in Slice 7).

**Build (custom character onboarding):**

- Detect new campaign + custom character on first turn.
- Run 2–3 turn intro scene via `scene_narrator` with campaign premise + character class/background injected.

**Build (reaction bus):**

- Event types: `creature_moves` (Sentinel, opportunity attacks), `creature_takes_damage_while_concentrating`.
- Subscribed feats/features fan out deterministically. Resolver narrates outcome.

**Build (concentration enforcement — system):**

- `apply_damage` (already in mutations) checks: if target is concentrating (`concentration: {spell_id, level} | None`), auto-roll CON save (DC = `max(10, damage_taken // 2)`). On fail, drop concentration and remove the linked effect from `combat_state.effects`. Emit `concentration_broken` event.
- Removes the LLM's responsibility to remember concentration rules.

**Build (inspiration mechanic):**

- `grant_inspiration(character_id, reason)` tool — DM-callable. Sets `has_inspiration=True` (idempotent — no stacking). Emits `inspiration_granted` event.
- `spend_inspiration(character_id)` tool — player-callable via UI. Sets `has_inspiration=False`. Next d20 roll for that character uses advantage. Emits `inspiration_spent` event.
- RulesLawyer reads `has_inspiration` and applies advantage when spent.

**Build (death model handling):**

- Read `Campaign.death_mode` (or `settings.death_mode`).
- In `apply_damage` → `hp == 0` path:
  - `pacifist` mode: clamp `hp = max(1, hp)`. PC never goes unconscious.
  - `hardcore`: PC death = run death save sequence; on full failure, set `Campaign.status = "ended_dead"`, emit `campaign_ended` event, freeze further turns.
  - `narrative` (default): PC death = death save sequence; on full failure, DM narrates recovery (DM prompt receives `death_recovery: true` flag), HP set to 1, story continues with a consequence tag in the world bible.
- Companion death always runs the death save sequence regardless of mode; on failure, `is_dead=True`, removed from combat. Story-driven revival possible.

**Build (loot enhancements — extends Slice 3 loot foundation):**

- **Search narrative** — when player input is "I search the body / chest / corpse" classified as a `narrative_action`, SceneNarrator receives the target NPC's inventory in its context block. Narrator describes what the character finds in prose ("on the guard's belt, a ring of three keys; under his cloak, a sealed letter"). Does NOT auto-loot — player still calls the loot route to take items. Requires SceneNarrator context assembly work in this slice.
- **Pickpocket flow** — when player input is "I pickpocket / steal X from Y" and target NPC is alive/conscious, IntentRouter routes to `skill_check`; RulesLawyer picks Sleight of Hand and flags `loot_intent: {npc_id, item_name}` on the CheckDecision. On successful resolve, the resolve route calls the loot service. On failure, narrate the failed attempt; NPC may turn hostile (Scene Director decides).
- **Currency loot** — extend the loot route to accept `{currency: {gp, sp, cp}}` instead of (or alongside) `item_name`. Validates NPC has enough, decrements NPC currency, increments character currency. No state validation beyond balance.

**Fix (combat polish):**

- **Massive damage instant-kill missing** — `apply_damage` doesn't check: 0 HP + damage ≥ max HP = instant death.
- **No knockout blow option** — `apply_damage` gets optional `subdue: bool`.
- **Combat resolver hardcoded combatant cap of 20** — replace `range(20)` with a count derived from `combat_state.combatants`.
- **Combat resolver inner-loop failure leaves inconsistent state** — surface partial state to the player; emit `combat_step_failed` event.

**Fix (long-pending dialogue bugs — most move to Slice 7 once profiles exist):**

- (Slice 7 owns the `NPC.find_by_name` fix and `NPC.disposition`-to-world-bible — they need the new profile schema in place to be meaningful.)

**Decide:**

- **Combat lifecycle paths** — `routes/combat.py` user-facing `/combat/start` and `/combat/end` vs. tools vs. scene_director auto-detect. Drop user-facing routes; scene_director + tools own it.
- **Scene transition pacing** — tension level concept (after 3 combat scenes, push toward social). Track turn-type history in `Scene` or compute on the fly. Lean compute-on-the-fly to avoid brittleness.
- **Massive damage threshold for monsters** — apply same rule as PCs? Probably yes.

**Verify:** "I attack the guard" starts combat without a client REST call. Sentinel triggers on enemy movement. Companion makes a contextual comment during a narrative turn. Concentrating wizard rolls CON save automatically when struck. Inspiration grant → spend → advantage on next roll. Pacifist mode PC takes 1000 damage → stays at 1 HP. Hardcore mode PC death → campaign locks. Narrative mode PC death → DM narrates wake-up scene.

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
- Vector store — pgvector in Postgres locally, S3 Vectors in prod.
- Retrieval before `SceneNarrator` — embed player input → top-k lore entries → inject.
- World echoes — `CAMPAIGN_CONCLUDED` from other campaigns retrievable as world history.

**Verify:** SceneNarrator prompt includes relevant lore. DM references a fact from 20 turns ago.

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
