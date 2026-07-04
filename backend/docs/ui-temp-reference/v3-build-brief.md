# Cairn App v3 — Build Brief (self-contained)

**Purpose:** everything needed to build `docs/ui-temp-reference/project/Cairn App v3.html` in one place, so a post-compaction session can build without reconstructing decisions. Full rationale lives in `docs/roadmap.md` → **Slice 15**; this file is the executable summary.

**Deliverable:** a single static `Cairn App v3.html` (keep `Cairn App v2.html` as history) with a screen-switcher (like v2's ~15-screen nav) so the user can click through every screen. Static/mock data — this is a *viewable visual spec*, not a wired app. Apply the `frontend-design` skill. Direction = **"Cartographer's Table."**

---

## Design tokens (EXACT — from Slice 15 Decision 2)

**Palette = 5 handcrafted themes, one kit** (decided post-review). Only the light changes between themes; structure/type/signature are constant. Two-accent semantics everywhere: **signal** (you-are-here / primary action / danger) and **trail** (known / positive / done). Implemented as CSS-variable swaps on `body[data-theme]` (default = slate, no attribute).

| theme | bg | panel | line | text | signal | trail |
|---|---|---|---|---|---|---|
| **Slate survey** (default) | `#141A1E` | `#1B2329` | `#2E3A40` | `#E7E2D4` | `#D6552B` | `#7E8F6E` |
| **Lamplight** | `#191510` | `#211B13` | `#3C3122` | `#EAE2CB` | `#D6552B` | `#8A9166` |
| **Blackwood** | `#121813` | `#19221B` | `#2E3C31` | `#E5E4D0` | `#D6552B` | `#94A47D` |
| **Gilt** (v2 homage) | `#14100A` | `#1C1610` | `#3A2F1C` | `#E9DFC4` | `#D6552B` | `#C9A04C` (gold = trail role, never signal) |
| **Daylight** (light) | `#E8E3D2` | `#EFEBDC` | `#C8C0A8` | `#262218` ink | `#BC4720` | `#5C6B47` |

Derive muted variants (text at 70/45/28/12%) — don't introduce new hues. Signal is the ONE bold accent; spend it only on "you are here" + primary action + critical beats.

**Theme switch placement:** canonical = **Account → Appearance** swatch row; duplicate compact row at the bottom of the in-campaign **Settings tab** under a "this device, not this table" divider. Client-side preference (localStorage → Phase-B user profile); never part of campaign settings.

**Type**
- **Space Grotesk** — labels, UI, nav, buttons, data headers.
- **Newsreader** — DM prose / all narrative reading text (the reading column).
- **Space Mono** — coordinates, dice, HP/AC numerals, timestamps, data ticks.

(Load via Google Fonts CDN in the HTML.)

**Signature:** the campaign *is* a **waymarked trail** — cairns/waypoints down a contour-lined spine, faint topographic texture, vermilion "you are here." The left nav-rail IS this trail (signature == navigation). Reuse the **node-graph visual language** for BOTH the combat zone-map and the exploration map — they are the visual through-line.

**Avoid the three AI-design tells:** no cream+terracotta serif, no black+acid-green, no broadsheet hairlines. (Our slate+vermilion+survey-paper + Grotesk/Newsreader/Mono is deliberately off all three.)

---

## Global shell — "Waymarked rail" (Decision 3)

Left nav-rail = the trail. **In-campaign:** top of rail = live campaign trail (acts → scenes as waypoints; current scene = vermilion "you are here"); campaign tabs dock below: **Play · Character · Party · Codex · Map · Settings**. **Pre-campaign:** rail shows top-level destinations: **Campaigns · Codex · Account**.

---

## Flow map (added 2026-07 review — every screen must be reachable in-app, not just via the dev strip)

```
LANDING (0, public)
  └─ Sign in → LOGIN (1) → HOME (4)
HOME (4)                                  rail: Campaigns · Codex · Account
  ├─ campaign card "Continue" → RECAP (20) → "Return to the trail" → PLAY (10)
  ├─ completed card "Read the record" → EPILOGUE (22)
  ├─ "+ Begin a new expedition" → WORLDS (5) → pick world → pick scenario → "Begin here" → NEW-CAMPAIGN (6)
  │     → "Create campaign" → CHOICE (7) → PREMADE (8) "Take this one" → PLAY (10)
  │                                      └→ FORGE (9) …8 steps… "Walk the trail" → PLAY (10)
  └─ Account tab → ACCOUNT (2) → "Manage plan" → BILLING (3)   (also: Settings model-tier → BILLING)
PLAY (10)                                 rail: trail + Play·Character·Party·Codex·Map·Settings
  ├─ check_required → DICE (11, overlay) — also serves death saves from DOWNED (14)
  ├─ combat_started → COMBAT (12, same screen re-proportions) → combat end + fallen foe → LOOT (23, overlay)
  │     └─ reaction_prompt → REACTION (25, overlay — may fire mid-round, more than once)
  ├─ band "Rest" → REST (13) — a LONG rest, for a prepared caster → SPELL-PREP (24, overlay)
  ├─ band "▲ level N waits" → LEVEL-UP (21) → back to SHEET (15)
  └─ campaign_ended → EPILOGUE (22)
RECAP (20) is a threshold: shown on resume only, never mid-session. First session ever skips it.
```

Rules: **recap is the doorway back in**; **dice/loot are overlays on the frozen play screen, never separate places**; **billing is reached from Account (canonical) and the Settings model-tier row (upsell)**; theme picker lives in Account → Appearance (canonical) + bottom of Settings (per-device duplicate).

## Screen inventory (build all of these)

### A. Shell / pre-play
0. **Landing (public)** — first-visit page, added 2026-07. Hero = the signature made literal: a trail that inks itself across contours (stroke-dashoffset draw, waypoints fade in, vermilion "you are here" pulse at the end), pitch line ("Play D&D with a DM who never forgets"), CTA → login. Three quiet claims: your table your rules / dice you roll yourself / a map drawn from memory.
1. **Login** — Phase-B *visual-only*, flagged "not wired."
2. **Account + security** — Phase-B visual-only (name, appearance/theme, plan → billing, sign out, danger zone).
3. **Billing / tiers** — Phase-B visual-only, speculative. Tiers map to Slice 10 model tiers: Free→`local` (Ollama), paid→`balanced`/`premium`. Placeholder names/prices.
4. **Home / campaign browser** — your playthroughs (`GET /campaigns`) + "start new." NOT the public home — that's Landing (0).
5. **World browser → scenario detail** (reworked 2026-07 — was a flat template list). Two levels, honoring `World → CampaignTemplate`: pick a **World** card first (name, mood line, canon stats — "3 scenarios · 214 canon entries · gods"), then a scenario within it. Scenario detail is **rich**: 2-para premise, lore quote, tone line, **act teaser trail** (Act I named; later acts veiled as "— — —" — the trail knows, you don't yet), **world-canon figure chips** ("names you may hear"), premades, session/level estimates. Teaser only, never the lore (spoiler-safe). (Needs `GET /campaigns/templates`, a surfaced backend dep.)
6. **New-campaign creation** — name + chosen template + **three framing knobs**: ① agency preset (Narrative/Balanced/Tactical) · ② death mode (pacifist/narrative/hardcore) · ③ content & tone (violence/gore/sexual/romance/horror/substances off·fade·on + hard-no `lines` + `tone_note`). Flow = `POST /campaigns` then `PATCH …/settings`.

### B. Character creation
7. **Creation choice** — split screen: **left = premade**, **right = build your own.**
8. **Premade fast-path** — 4–5 dossier cards in a row; **expand-in-place**: click → card grows to full field-dossier (portrait · stat block · bio prose), others shrink to a **thumbnail rail**; click a thumbnail to swap; **"Take this one"** confirms.
9. **Custom forge** ("BG3-grade", multi-step): race/subrace · class/subclass · background · **alignment** · **abilities (standard-array assignment only — `[15,14,13,12,10,8]`, no point-buy/rolling)** · skills · spells — all locked SRD pickers. Then **identity (free text)**: name, bio, personality, voice — with an optional **"Weave from prompt"** button (concept → LLM fills bio/personality/voice, user edits; surfaced backend dep = Weave agent). Then **portrait**: frame with **Gallery** + **Upload** (both live) + **Generate** (designed but flagged — FLUX-schnell earmarked).
   **All steps are mocked as clickable panels; the pickers are SRD-complete** (consistency audit 2026-07): **9 races, 12 classes, 13 backgrounds** as flavor-prose picker cards; alignment = 3×3 grid; abilities = array assignment; skills = choose-N chips off the class list; identity = free text + Weave; portrait = gallery/upload/generate. Three steps are **conditional** and render dimmed on the step-trail until the road calls for them ("dim steps wake"): **Subrace** (9 SRD subraces — humans etc. skip it), **Subclass** (`CharacterCreate.subclass` — the engine *hard-rejects* a cleric/sorcerer/warlock without one at creation, `SUBCLASS_LEVEL` 1; wizard/druid choose at 2, the rest at 3 via level-up; the SRD carries one subclass per class), **Spells** (`spell_choices` — cantrips + day-one list from `/v1/srd/spells` filtered by class; non-casters march past). Conditional panels are mocked with "shown for an elf / a cleric / a wizard, for the spec" tags. Left step-trail (same waymark language as the rail) switches panels.

### C. Play (the hero)
10. **Play — exploration:** vitals strip on top → **reading column** (centered Newsreader prose at a real reading measure) + persistent **field-notes margin** (right; surveyor's marginalia holding live state) → **slim character band** at the column's edge (portrait · HP bar · condition chips · inspiration token · concentration chip · **Rest** button; **companions ride here as mood-tinted mini-avatars** with vague band labels). Input bar at bottom.
    - **Event rendering:** reading column = **pure prose**; the ~30 mechanical SSE events **tick in the field-notes margin** (margin **pulses subtly on change**). **Pivotal** events (`death_save_rolled`, PC `combatant_knocked_out`, `massive_damage_death`, `campaign_ended`) *also* get a brief **inline** announcement in the column.
    - **DM "thinking"** = **diegetic shimmer only** in the margin ("the DM considers…", quill/dice) — NO agent names, NO pipeline. (v2's "DM Thinking" panel dropped.)
11. **Dice modal** — `check_required` → single focused overlay (die · DC · mod). **Inspiration = "spend for advantage: roll two, take higher"** (→ `resolve` with `inspiration_roll`). Client animates/submits; result logs to margin, outcome streams as prose. **Death saves also use this modal** (surfaced backend dep: make death saves player-rolled).
12. **Play — combat mode:** on `combat_active` the screen re-proportions → **initiative strip** on top · **compressed prose log** left · **zone sketch-map** center-right · **economy readout bar** bottom. Biggest build.
    - **Interaction truth (corrected 2026-07 against the engine):** the player's typed message **is their whole turn** — `combat_resolver` parses it, spends the economy (`action_used` / `bonus_action_used` / `reaction_used` / `movement_remaining` in real feet), and **calls `advance_turn` itself**. Therefore: **NO "End turn" button, NO Attack/Move/Dash selector buttons.** The bar is a **read-only economy readout** (A/B/R pips + "MOVE 30/30 FT") plus optional **insert-chips** ("⌁ attack the warden") that only prepend text to the input. Caption on the bar says it: "your message is your whole turn."
    - **Zone map = the DM's napkin sketch** (not abstract circles): 3–6 irregular hand-drawn **regions**, each carrying its Slice-9 anatomy — occupants (◉ YOU vermilion), **cover** ("HALF COVER +2", lichen), **difficult terrain** ("DIFFICULT ×2"), **hazard** ("⚠ ROTTEN BEAM", vermilion) — with **distance-labeled dashed edges** ("CLOSE · 30FT", "×2" into difficult ground; absent edge = out of range). **All zones are drawn from the start** — the engine seeds every zone at combat init and they're immutable; there is no hidden-zone/fog concept (audit 2026-07 removed a "???" blob here; `???` stubs belong to the exploration map only). Gated on Slice 9; until then combat renders initiative + economy + enemy states, no positioning.
    - **Inspiration in combat** (the toggle Slice 6 punted to the UI): a vermilion "◈ spend inspiration" chip in the action bar — arms `use_inspiration` for the turn's roll. The dice modal handles the non-combat path.
    - **Suggest-mode proposal band** (`companion_action_proposed`, Slice 10 `companion.combat = "suggest"`): a slim lichen band above the bar — companion's proposed action in their voice + **"Let her" / "Direct her"** (confirm / override via the resolver path).
13. **Rest moment** — one-click from the band → narrated stream (`rest_applied`/`rest_blocked` tick + prose). No form; hit-dice spend is automatic (the route takes no body). **Blocked/risky states are part of the screen:** a hostile scene returns `rest_blocked` with a reason the DM narrates; a risky one gets the "are you sure?" narrative gate first (mocked as a field-note spec line). After a **long** rest, prepared casters get the re-prep prompt — now its own overlay, screen 24.
14. **Downed / death-save takeover** — the character band becomes the **3-successes / 3-failures track**; `massive_damage_death` = instant, no track.

### D. Panels / drawers (rail tabs)
15. **Character sheet** (PC) — **redesigned 2026-07: the dossier, grown up** (the form-like grid was rejected). Layout: big portrait (≈160×190) + Newsreader name + bio prose + live condition/inspiration/level-up chips as the header; ability tiles + AC/HP/HD/SPD compacted to the right; then attacks+features and saves+skills cards; then **inventory** — **"carried on the body" slot list** (BODY/MAIN HAND/OFF HAND/CLOAK/HEAD/NECK; filled slots solid, empty dashed; AC and attacks derive from slots) + **"in the pack" item-tile grid** (quest items vermilion-tinted), **drag-from-pack-to-equip** as the target interaction; then **spellcasting section for casters** — slot pips per level, prepared-spell rows (● = prepared), known-not-prepared dimmed, "prepared casters re-choose after every long rest." ⚠ backend dep: **equipment slot taxonomy** (today equipment is a flat list + equipped flag; drag-to-slot needs slot names on items).
16. **Party + companion drawer** — cards read like people, not stat blocks (2026-07): portrait band, **epithet in italic prose** ("Reads water the way other people read letters"), vague approval chip ("holds you — guarded"), "walks with you since Day 2." Drawer: **Approval** section = **vague band + colored reason-log (green/red lines with reason strings), NO raw number** + mood + personal_goal + **voice line** ("how she sounds"). Stat block demoted to the drawer's bottom. `secret` never shown.
17. **Codex** — in-play **discovery journal** (`GET /campaigns/{id}/lore`), grouped People/Places/Factions/History/**Days**; grows as you play; undiscovered categories shown empty. Spoiler-safe. **Days tab** (audit 2026-07) = the calendar surface the roadmap promised: one row per in-game day from `GET …/calendar`, click a day → its summary. **Search field** in the tab row → the `GET …/lore?q=` hybrid-search variant (planned; visibility-filtered).
18. **Exploration map** (SIGNATURE payoff) — **auto-laid-out node graph of discovered locations**; nodes = visited places, edges from `Location.connections` (adjacency-only, no coords → frontend lays out), current = vermilion "you are here", known-but-unvisited = `???` stubs; click node → inspect/travel. **Same node-graph vocabulary as the combat zone-map.**
19. **Settings tab** — mirrors Slice 10: agency preset radios · death-mode · content toggles + `lines`/`tone_note` · **model-tier picker (anytime swap)** · narration verbosity (terse/normal/lush) · collapsible **Advanced** (per-agent `model_overrides` + per-companion agency sliders + **your reactions: ai/suggest/player** `reaction_control` + passive-check modes). Header shows **"Balanced · N custom."**
20. **Recap + cheatsheet** — "previously on…" (`Session.summary` + `/calendar` day-summaries) + at-a-glance cheatsheet (active threads, objective, reachable exits). **This is the threshold screen** (2026-07): campaign card "Continue" always lands here first; "Return to the trail →" enters play. Never shown mid-session; first-ever session skips it.

### E. Moments (added 2026-07 review — planned engine features that had no screen)
21. **Level-up** — entry: `level_up_pending` event → vermilion "▲ level N waits" chip in the character band and on the sheet. Screen: "what level N grants" preview card (`GET …/level-up`), then knobs in creation-screen language: ① HP = **roll the d10 (dice modal) vs take the average** · ② **ASI vs feat** (SRD-validated) · **③ caster knobs** (mocked "from Isolde's wizard 2→3"): new-spell chips (`spells_to_choose`) + subclass choice when the level asks (`available_subclasses` — wizard/druid at 2, most at 3). "Seal it" → `POST …/level-up {hp_method, hp_roll?, asi|feat, new_spells?, subclass?}` → back to the sheet. Allowed mid-combat (RAW). Under Tactical agency (`companion.leveling = "player"`) companions level through this same screen.
22. **Epilogue / campaign concluded** — entry: `campaign_ended` event, or "Read the record" on a completed campaign card. Epilogue prose (the `CAMPAIGN_CONCLUDED` content) + expedition stats line (acts/days/sessions/companions lost) + fully-lichen minitrail. **The record stays open** — codex/map/sheets readable forever, nothing writable. Hardcore-death variant = same screen, darker heading (`status: ended_dead`, "the trail keeps your cairn").
23. **Loot** — overlay on the frozen play screen (same veil pattern as dice). Surfaces only while a defeated NPC lies in the scene. Item rows (name + flavor mono line) each with **Take** (`POST …/loot` per item), currency row, **Take all** (loops items + one currency call), **Leave it**. Spec shows post-combat entry; also reachable whenever `dead_npcs_with_inventory` is non-empty.
24. **Spell prep** (added — consistency audit 2026-07) — overlay, same veil pattern. Entry: a **long rest** completes and the active character is a **prepared caster** (cleric/druid/paladin/wizard): the server clears `prepared_spells` and the UI prompts. Row list of the book/known spells with ● prepared marks, "PREPARE N — mod + level" count, **Seal the day's prayers** → `POST …/prepare-spells` (count + class-legality validated) · **Keep yesterday's** re-submits the old list. Known-spell casters never see it.
25. **Reaction prompt** (added — consistency audit 2026-07; renders the planned reaction engine) — overlay, may interrupt a combat round **more than once**. A **terse, templated mechanical trigger** (never narration — the round's prose lands after resolution): "thrall-warden moves, your longsword can catch it," a **recommendation chip**, a **countdown** ("silence takes the recommendation" — timeout auto-applies), **take / let it go** → `POST …/reactions`. Frequency governed by `reaction_control` (ai = never asked / suggest = asked when it matters / player = always asked); AI allies and enemies always decide for themselves. Flagged as a planned-engine dep in the mockup.

---

## Build order (post-compaction)

1. **Tokens + shell** — CSS variables, fonts, the waymarked-rail, the topographic/contour texture + node-graph primitive (shared by map + zones). Get the visual language right FIRST; screenshot-critique against the three AI tells.
2. **Play — exploration (#10)** + **dice modal (#11)** — the hero; nail this before anything else.
3. **Combat (#12)** + **exploration map (#18)** — the two node-graph payoffs (reuse the shared primitive).
4. **Character creation (#7–9)** — choice + premade dossier + custom forge.
5. **Panels (#15–17, #19–20)** — sheet, party/approval, codex, settings, recap.
6. **Pre-play + Phase-B (#1–6)** — browser, creation, login/account/billing (visual-only).

Wire a top screen-switcher so all 26 are clickable in one file.

---

## Surfaced backend deps (NOT UI — track in Slice 15)
1. **Weave agent** — concept → `bio`/`personality`/`voice_traits`.
2. **Player-rolled death saves** — `roll_death_save` (`combat/rolls.py:65`) → client-roll/`resolve` pattern.
3. **Portrait image-gen** (later/Phase B) — FLUX-schnell earmarked; "Generate" is a flagged affordance only.
4. **`GET /v1/campaigns/templates`** — template/world-browse endpoint for the world browser (should return worlds with their scenarios nested, per screen 5).
5. **Equipment slot taxonomy** (added 2026-07) — inventory is a flat list + equipped flag today; the sheet's drag-to-slot inventory needs slot names (body/main hand/off hand/…) on items. Supersedes the old "simple list with equipped badge; drag-and-drop v2" checklist line.
6. **`GET /v1/srd/alignments`** (added — consistency audit 2026-07) — `alignments.json` ships in the SRD data but no route serves it; the forge's alignment grid claims everything loads from `/v1/srd`. Trivial route, same pattern as the others.

_Not new deps, but engine features (Slices 4/6/9/10/10.5) the UI now renders instead of omitting: caster creation (subrace/subclass-at-1/spell_choices — creation-service contract), level-up flow incl. caster knobs + spell re-prep overlay (Slice 4), loot modal + death modes/epilogue + combat inspiration toggle + rest_blocked states (Slice 6), zone anatomy + OA (Slice 9), suggest-mode proposals (Slice 10), reaction prompt + `reaction_control` (Slice 10.5), codex Days tab (`/calendar`, Slice 5) + codex search (`/lore?q=`, Slice 13)._
