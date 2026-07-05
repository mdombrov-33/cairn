# Cairn App v4 — Build Brief (self-contained)

**Purpose:** everything needed to build `docs/ui-temp-reference/project/Cairn App v4.html` in one place, so a post-compaction session can build without reconstructing decisions. Full rationale lives in `docs/roadmap.md` → **Slice 15** (Decisions 9–11); this file is the executable summary. v4 supersedes `v3-build-brief.md` (kept as history) after the second user review round: same tokens, same signature, revised interaction patterns.

**Deliverable:** a single static `Cairn App v4.html` (keep v2/v3 as history) with a screen-switcher so every screen is clickable. Static/mock data — a *viewable visual spec*, not a wired app. Apply the `frontend-design` skill. Direction = **"Cartographer's Table."**

---

## Design tokens (EXACT — unchanged from v3 / Slice 15 Decision 2)

**Palette = 5 handcrafted themes, one kit.** Only the light changes between themes; structure/type/signature are constant. Two-accent semantics everywhere: **signal** (you-are-here / primary action / danger) and **trail** (known / positive / done). CSS-variable swaps on `body[data-theme]` (default = slate, no attribute).

| theme | bg | panel | line | text | signal | trail |
|---|---|---|---|---|---|---|
| **Slate survey** (default) | `#141A1E` | `#1B2329` | `#2E3A40` | `#E7E2D4` | `#D6552B` | `#7E8F6E` |
| **Lamplight** | `#191510` | `#211B13` | `#3C3122` | `#EAE2CB` | `#D6552B` | `#8A9166` |
| **Blackwood** | `#121813` | `#19221B` | `#2E3C31` | `#E5E4D0` | `#D6552B` | `#94A47D` |
| **Gilt** (v2 homage) | `#14100A` | `#1C1610` | `#3A2F1C` | `#E9DFC4` | `#D6552B` | `#C9A04C` (gold = trail role, never signal) |
| **Daylight** (light) | `#E8E3D2` | `#EFEBDC` | `#C8C0A8` | `#262218` ink | `#BC4720` | `#5C6B47` |

Derive muted variants (text at 70/45/28/12%) — no new hues. Signal is the ONE bold accent.

**Theme switch placement:** canonical = **Account → Appearance**; compact duplicate at the bottom of in-campaign **Settings** under "this device, not this table." Client-side preference (localStorage key `cairn-v4-theme`).

**Type:** **Space Grotesk** (UI/labels) · **Newsreader** (DM prose / reading column) · **Space Mono** (dice, numerals, timestamps, data ticks). Google Fonts CDN.

**Signature:** the campaign *is* a **waymarked trail** — cairns/waypoints down a contour-lined spine, vermilion "you are here." The left nav-rail IS this trail. The **node-graph vocabulary** is shared by the combat zone-map and the exploration map.

**Avoid the three AI-design tells:** no cream+terracotta serif, no black+acid-green, no broadsheet hairlines.

---

## Interaction principles (NEW in v4 — Decision 11, from user review round 2)

These govern every screen; they exist because v3 over-used three patterns (card grids, terse chips, veil modals):

1. **Every rules noun is inspectable.** Any spell, condition, item, or feature name opens a popover with its SRD text on hover/tap (`.pop`/`.popcard`; text from `/v1/srd`, zero new backend). Demonstrated on the play band (Exhaustion, Bless), the sheet (spell rows, quest item), and the forge reading panes.
2. **Pickers are a list + a reading pane, not a card grid.** Terse rows to scan on the left; a full page on the right with SRD description, granted traits (`.grant` rows), and a **"what this choice asks next"** box. Used for race/subrace/class/subclass/background; spells keep multi-select chips but gain the same reading pane (first click reads, the check commits).
3. **A modal only when the game cannot continue without the answer — and never when the answer requires seeing the table.** Dice (11) stays a veil: it blocks by nature and the card carries everything needed. Loot fails the "cannot continue" test → inline spoils card in the log. Reaction fails the "seeing the table" test → interrupt bar over a visible board. Spell prep is the last page of the long rest, not a popup.
4. **Mode changes happen under the narration, never as a cut.** Explore→combat is one orchestrated in-place transformation (screen 12a); the reverse runs at combat end. The prose column never resets.

---

## Global shell — "Waymarked rail" (Decision 3, amended v4)

Left nav-rail = the trail. **In-campaign:** live campaign trail on top (acts → waypoints; vermilion "you are here"); tabs: **Play · Character · Party · Codex · Map · Settings**. **Pre-campaign:** **Campaigns · Account** only — **the codex is campaign memory and never appears in the global rail** (v4 fix; it lives in the in-campaign tabs and, read-only, behind a concluded campaign's "Open the record").

---

## Flow map (v4)

```
LANDING (0, public — a page you SCROLL; the trail is the page spine)
  └─ Sign in → LOGIN (1) → HOME (4)
HOME (4)                                  rail: Campaigns · Account
  ├─ campaign card "Continue" → RECAP (20) → "Return to the trail" → PLAY (10)
  ├─ completed card "Read the record" → EPILOGUE (22) → codex/map/sheets read-only
  ├─ "+ Begin a new expedition" → WORLDS (5) → scenario → "Begin here" → NEW-CAMPAIGN (6)
  │     → "Create campaign" → CHOICE (7) → PREMADE (8) "Take this one" → PLAY (10)
  │                                      └→ FORGE (9) …list+pane steps… → PLAY (10)
  └─ Account tab → ACCOUNT (2) → "Manage plan" → BILLING (3)
PLAY (10)                                 rail: trail + the six tabs
  ├─ check_required → DICE (11, overlay — the one true modal; also death saves from 14)
  ├─ combat begins mid-turn → INTO-COMBAT (12a, in-place transformation) → COMBAT (12)
  │     ├─ reaction_prompt → REACTION (25, interrupt BAR on the live board)
  │     └─ combat ends + fallen foe → LOOT (23, spoils card riding the log)
  ├─ band "Rest" → REST (13); a LONG rest for a prepared caster ends on SPELL-PREP (24, the rest's last page)
  ├─ band "▲ level N waits" → LEVEL-UP (21, walks the preview's asks) → SHEET (15)
  └─ campaign_ended → EPILOGUE (22)
RECAP (20): the doorway back in — resume only, never mid-session, first session skips it.
```

## Screen inventory (27 sections, s00–s26)

### A. Shell / pre-play
0. **Landing (public)** — reworked v4: a **scrollable page whose spine is the trail** (dashed vertical line, waypoint dots inking section by section). Hero = headline ("Play D&D with a DM who never forgets") + CTA + scroll cue. Then four waypoints, each a **real product moment**: ① *The table* — a rendered turn exchange exactly as it looks in play (`.you` block, streaming tokens, field-note chips); ② *The ledger* — a real codex card + a mini self-drawing map; ③ *Your rules* — dice/death/hard-lines claim cards; ④ *You are here* — closing CTA. No abstract "set out → choose" steps — every waypoint labels real content.
1. **Login** — Phase-B visual-only, flagged.
2. **Account + security** — Phase-B visual-only (name, appearance swatches, plan → billing, sign out, danger zone).
3. **Billing / tiers** — Phase-B visual-only, speculative; Free→`local`, paid→`balanced`/`premium`.
4. **Home / campaign browser** — playthroughs (`GET /campaigns`) + "start new."
5. **World browser → scenario detail** — two levels (`World → CampaignTemplate`): world cards, then rich scenario detail (premise, lore quote, veiled act-teaser trail, canon figure chips, premades). Dep: `GET /v1/campaigns/templates`.
6. **New-campaign creation** — name + three framing knobs: agency preset · death mode · content & tone (+ hard lines, tone note). `POST /campaigns` + `PATCH …/settings`.

### B. Character creation
7. **Creation choice** — split: premade | forge.
8. **Premade fast-path** — dossier expand-in-place, thumbnail rail, "Take this one." Caster dossiers add a spell block.
9. **Custom forge** — step-trail on the left (same waymark language), each picker step now a **list + reading pane** (principle 2): 9 races, 12 classes (casters marked), 13 backgrounds, 3 elf subraces shown; reading pane = SRD text + granted traits + "what this asks next" (e.g. fighter: two skills, subclass at 3; cleric/sorcerer/warlock: **subclass required at creation — the engine refuses the sheet without it**; wizard/druid at 2). Subclass pane shows the SRD's one-per-class truth (Life Domain, "more arrive with content, not code"). **Spells step**: cantrip + day-one chips with the reading pane ("first click reads, the check commits"). Alignment 3×3 grid; abilities = standard-array assignment `[15,14,13,12,10,8]`; skills = choose-N chips; identity free text + **Weave** button (dep); portrait gallery/upload/generate (gen flagged). Conditional steps (Subrace/Subclass/Spells) render dimmed until the road calls; conditional panes tagged "shown for an elf / a cleric / a wizard, for the spec." Noted gap: subrace spell grants (high-elf cantrip) aren't applied by the creation service — dep #7.

### C. Play (the hero)
10. **Play — exploration:** vitals strip → reading column (Newsreader at reading measure) + field-notes margin → slim character band (portrait · HP · condition chips **with popovers** · inspiration · Rest · level-up chip; companion mini-avatars) → input bar. Prose column = pure prose; mechanical SSE events tick in the margin; pivotal events also announce inline. DM "thinking" = diegetic shimmer only.
11. **Dice modal** — the one true veil. Die · DC · mod · inspiration toggle ("roll two, take higher" → `resolve` + `inspiration_roll`). Also serves death saves (dep: player-rolled).
12. **Play — combat:** initiative strip · compressed prose log · **zone sketch-map** (the DM's napkin: irregular regions, occupants, cover/difficult/hazard attrs, distance-labeled edges; **all zones seeded at init, nothing hidden**) · read-only economy bar (A/B/R pips + MOVE in feet) + insert-chips + "◈ spend inspiration" chip. **Your message is your whole turn** — no End-turn, no verb buttons. Suggest-mode proposal band above the bar.
12a. **Into-combat (s26, NEW)** — the transformation moment, mocked with staged CSS animation: prose continues past a vermilion "Steel is drawn — round 1" pivot → the light drops a step (`duskcast` gradient) → initiative ribbon slides down → the sketch **unfurls complete** where the field notes stood → economy bar rises. Caption: combat begins *inside* a turn, no cut, no modal; the same moves run in reverse when the last foe falls.
13. **Rest moment** — one-click from the band; narrated stream; no form, hit-dice automatic. Blocked/risky states as field-note spec lines. A long rest for a prepared caster ends on screen 24.
14. **Downed** — band becomes the 3/3 death-save track; massive damage skips it.

### D. Panels (rail tabs)
15. **Character sheet** — dossier-grown-up header (big portrait, Newsreader name, bio, live chips, "every rules noun is inspectable" note) + ability tiles + attacks/features + saves/skills. **Inventory = the carried ledger** (v4, replaces the slot grid): equipped kit grouped by hand — **STEEL** (armor rows whose AC arithmetic sums to a balanced ledger line: chain shirt 13 + DEX 1 + shield 2 + Defense 1 = **AC 17**), **HANDS** (weapons + attack math), **WORN** — beside the **pack** tile grid (quest items vermilion, popovers). **No slot model, none needed** — grouping derives from `equipped` + SRD item data; equipping is a *sentence to the DM*, not a drag ("I sling the shield and take the sword in both hands" — the ledger follows). Spellcasting block for casters (slot pips, prepared rows, popovers).
16. **Party** — reworked v4: **companions are characters, not summaries.** A fireside roster strip (you + companions, mood + HP at a glance); selecting a member fills the screen with **the same full sheet component as your own** (dosshead + stats + attacks/features), plus the companion-only additions: **leash band** (Directed / Suggest / Free rein), **"How she holds you"** approval log (vague band + reason lines, no numbers), voice chips. `secret` never shown. No dossier drawer.
17. **Codex** — discovery journal (People/Places/Factions/History/**Days**) + search field (`GET …/lore?q=`, planned). Days tab = calendar surface (`GET …/calendar`), one row per in-game day.
18. **Exploration map** — auto-laid node graph of discovered locations; `???` stubs for rumors; same vocabulary as combat zones.
19. **Settings** — agency preset · death mode · content/tone · model tier · verbosity terse/normal/lush · Advanced (per-agent overrides · companion agency · your reactions ai/suggest/player · passive checks).
20. **Recap + cheatsheet** — the threshold screen on resume.

### E. Moments
21. **Level-up** — reworked v4: **the screen walks exactly the asks the preview names** (`GET …/level-up` — same path as the apply POST: hp{die, average, con_modifier} · asi_or_feat · subclass_required/available_subclasses · available_feats · new_features · spells_to_choose · new_spell_slots). A step strip (① hit points ② improve ③ seal); a "the preview names the asks" card that also says what's **NOT asked** ("what a level doesn't ask for never appears here"); HP step decided-state with change affordance (roll opens the dice modal); ASI allocator (2 points, each +1/2 — engine-validated) vs feat list; caster card ("the asks grow, the screen doesn't change shape"): spell chips for `spells_to_choose`, `subclass_required` joins the walk at wizard/druid 2, most classes 3; slots appear unasked — arithmetic, not choices. `POST …/level-up {hp_method, hp_roll?, asi|feat, new_spells?, subclass?}`. Companions level through the same door under Tactical agency.
22. **Epilogue** — `campaign_ended` or "Read the record"; record stays open read-only; hardcore variant darker (`ended_dead`).
23. **Loot** — reworked v4: a **spoils card riding the narration log** (vermilion-edged, inline after the combat-end prose), never a veil. Item rows with Take (`POST …/loot`), taken-state chips, "Take the rest" / "Leave it." Actionable while the fallen foe lies in the scene; the story can scroll past it — it never blocks. **A result, not a decision.**
24. **Spell prep** — reworked v4: **the last page of the long rest**, not a popup. A rest-morning play screen (dawn vitals, morning prose) with the prep card inline in the column: prepared rows + "PREPARE N — mod + level," **Seal the day's prayers** → `POST …/prepare-spells` (count + class-legality validated) / **Keep yesterday's**. Input waits until the book is sealed. Known-spell casters skip straight to the road. Shown from Isolde's table, for the spec.
25. **Reaction prompt** — reworked v4: an **interrupt bar over the live board**, never a curtain — you can see the aisle, the stair, and why the swing matters (that's the point). Round holds its breath: the acting foe highlighted in the ribbon, its move drawn on the sketch, a vermilion bar with the terse templated trigger + recommendation chip + countdown ("silence takes the recommendation") + take / let it go → `POST …/reactions`. May fire more than once a round; frequency = `reaction_control` (ai/suggest/player); AI allies and foes decide for themselves. Planned-engine dep, flagged.

---

## Build order (post-compaction)

1. **Tokens + shell** — variables, fonts, waymarked rail, contour texture, node-graph primitive, **popover primitive**.
2. **Play — exploration (10)** + **dice (11)** — the hero.
3. **Combat (12) + into-combat (12a) + map (18)** — the node-graph payoffs and the signature transition.
4. **Creation (7–9)** — choice, premade, list+pane forge.
5. **Panels (15–17, 19–20)** — sheet w/ carried ledger, party-as-full-sheet, codex, settings, recap.
6. **Moments (21–25)** + **pre-play/Phase-B (0–6)**.

Wire the top switcher so all 27 are clickable in one file.

---

## Surfaced backend deps (NOT UI — track in Slice 15)
1. **Weave agent** — concept → `bio`/`personality`/`voice_traits`.
2. **Player-rolled death saves** — `roll_death_save` → client-roll/`resolve` pattern.
3. **Portrait image-gen** (later/Phase B) — FLUX-schnell earmarked; "Generate" flagged only.
4. **`GET /v1/campaigns/templates`** — worlds with nested scenarios for screen 5.
5. ~~**Equipment slot taxonomy**~~ — **retired in v4:** the carried ledger groups by `equipped` + SRD item category; no slot model needed. Revisit only if true slot *rules* (one body, two hands) are ever wanted.
6. **`GET /v1/srd/alignments`** — `alignments.json` ships but no route serves it. Trivial.
7. **Subrace spell grants** (added v4) — the creation service applies subrace ability bonuses + proficiencies but not racial spells (high-elf cantrip). Either grant it server-side or drop the claim from the pane.

_Engine features (Slices 4/6/9/10/10.5) the UI renders rather than omits: caster creation contract, level-up preview/asks incl. caster knobs + rest-morning re-prep, loot, death modes/epilogue, combat inspiration, rest_blocked, zone anatomy + OA, suggest-mode proposals, reaction prompt + `reaction_control`, codex Days (`/calendar`) + search (`/lore?q=`)._
