# Cairn App v3 — Build Brief (self-contained)

**Purpose:** everything needed to build `docs/ui-temp-reference/project/Cairn App v3.html` in one place, so a post-compaction session can build without reconstructing decisions. Full rationale lives in `docs/roadmap.md` → **Slice 15**; this file is the executable summary.

**Deliverable:** a single static `Cairn App v3.html` (keep `Cairn App v2.html` as history) with a screen-switcher (like v2's ~15-screen nav) so the user can click through every screen. Static/mock data — this is a *viewable visual spec*, not a wired app. Apply the `frontend-design` skill. Direction = **"Cartographer's Table."**

---

## Design tokens (EXACT — from Slice 15 Decision 2)

**Palette**
| token | hex | use |
|---|---|---|
| bg (slate ink) | `#141A1E` | app background |
| panel | `#1B2329` | cards, rail, drawers |
| line | `#2E3A40` | borders, dividers, contour lines |
| paper (warm survey) | `#E7E2D4` | primary text / prose |
| **signal (vermilion)** | `#D6552B` | "you are here", current waypoint, primary action, danger deltas |
| lichen (trail green) | `#7E8F6E` | trail, positive/known, secondary accent |

Derive muted variants (e.g. paper at 60% for secondary text) — don't introduce new hues. Vermilion is the ONE bold accent; spend it only on "you are here" + primary action + critical beats.

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

## Screen inventory (build all of these)

### A. Shell / pre-play
1. **Login** — Phase-B *visual-only*, flagged "not wired."
2. **Account + security** — Phase-B visual-only (name, theme, sign out, danger zone).
3. **Billing / tiers** — Phase-B visual-only, speculative. Tiers map to Slice 10 model tiers: Free→`local` (Ollama), paid→`balanced`/`premium`. Placeholder names/prices.
4. **Home / campaign browser** — your playthroughs (`GET /campaigns`) + "start new."
5. **Template browser + template detail** — premise · length · premades · **teaser lore blurb** (needs `GET /campaigns/templates`, a surfaced backend dep).
6. **New-campaign creation** — name + chosen template + **three framing knobs**: ① agency preset (Narrative/Balanced/Tactical) · ② death mode (pacifist/narrative/hardcore) · ③ content & tone (violence/gore/sexual/romance/horror/substances off·fade·on + hard-no `lines` + `tone_note`). Flow = `POST /campaigns` then `PATCH …/settings`.

### B. Character creation
7. **Creation choice** — split screen: **left = premade**, **right = build your own.**
8. **Premade fast-path** — 4–5 dossier cards in a row; **expand-in-place**: click → card grows to full field-dossier (portrait · stat block · bio prose), others shrink to a **thumbnail rail**; click a thumbnail to swap; **"Take this one"** confirms.
9. **Custom forge** ("BG3-grade", multi-step): race/subrace · class/subclass · background · **alignment** · **abilities (standard-array assignment only — `[15,14,13,12,10,8]`, no point-buy/rolling)** · skills — all locked SRD pickers. Then **identity (free text)**: name, bio, personality, voice — with an optional **"Weave from prompt"** button (concept → LLM fills bio/personality/voice, user edits; surfaced backend dep = Weave agent). Then **portrait**: frame with **Gallery** + **Upload** (both live) + **Generate** (designed but flagged — FLUX-schnell earmarked).

### C. Play (the hero)
10. **Play — exploration:** vitals strip on top → **reading column** (centered Newsreader prose at a real reading measure) + persistent **field-notes margin** (right; surveyor's marginalia holding live state) → **slim character band** at the column's edge (portrait · HP bar · condition chips · inspiration token · concentration chip · **Rest** button; **companions ride here as mood-tinted mini-avatars** with vague band labels). Input bar at bottom.
    - **Event rendering:** reading column = **pure prose**; the ~30 mechanical SSE events **tick in the field-notes margin** (margin **pulses subtly on change**). **Pivotal** events (`death_save_rolled`, PC `combatant_knocked_out`, `massive_damage_death`, `campaign_ended`) *also* get a brief **inline** announcement in the column.
    - **DM "thinking"** = **diegetic shimmer only** in the margin ("the DM considers…", quill/dice) — NO agent names, NO pipeline. (v2's "DM Thinking" panel dropped.)
11. **Dice modal** — `check_required` → single focused overlay (die · DC · mod). **Inspiration = "spend for advantage: roll two, take higher"** (→ `resolve` with `inspiration_roll`). Client animates/submits; result logs to margin, outcome streams as prose. **Death saves also use this modal** (surfaced backend dep: make death saves player-rolled).
12. **Play — combat mode:** on `combat_active` the screen re-proportions → **initiative strip** on top · **compressed prose log** left · **zone node-map** center-right (**node graph, not a grid**; gated on Slice 9 — until then show initiative + action economy + enemy states, no positioning) · **action-economy action bar** bottom (Attack/Move/Dash · A/B/R · movement ft). Biggest build.
13. **Rest moment** — one-click from the band → narrated stream (`rest_applied`/`rest_blocked` tick + prose). No form.
14. **Downed / death-save takeover** — the character band becomes the **3-successes / 3-failures track**; `massive_damage_death` = instant, no track.

### D. Panels / drawers (rail tabs)
15. **Character sheet** (PC) — full sheet.
16. **Party + companion drawer** — party at a glance in the band; click a companion → drawer with full sheet + **Approval** section = **vague band + colored reason-log (green/red lines with reason strings), NO raw number** + mood + personal_goal. `secret` never shown.
17. **Codex** — in-play **discovery journal** (`GET /campaigns/{id}/lore`), grouped People/Places/Factions/History; grows as you play; undiscovered categories shown empty. Spoiler-safe.
18. **Exploration map** (SIGNATURE payoff) — **auto-laid-out node graph of discovered locations**; nodes = visited places, edges from `Location.connections` (adjacency-only, no coords → frontend lays out), current = vermilion "you are here", known-but-unvisited = `???` stubs; click node → inspect/travel. **Same node-graph vocabulary as the combat zone-map.**
19. **Settings tab** — mirrors Slice 10: agency preset radios · death-mode · content toggles + `lines`/`tone_note` · **model-tier picker (anytime swap)** · narration verbosity · collapsible **Advanced** (per-agent `model_overrides` + per-companion agency sliders + passive-check modes). Header shows **"Balanced · N custom."**
20. **Recap + cheatsheet** — "previously on…" (`Session.summary` + `/calendar` day-summaries) + at-a-glance cheatsheet (active threads, objective, reachable exits).

---

## Build order (post-compaction)

1. **Tokens + shell** — CSS variables, fonts, the waymarked-rail, the topographic/contour texture + node-graph primitive (shared by map + zones). Get the visual language right FIRST; screenshot-critique against the three AI tells.
2. **Play — exploration (#10)** + **dice modal (#11)** — the hero; nail this before anything else.
3. **Combat (#12)** + **exploration map (#18)** — the two node-graph payoffs (reuse the shared primitive).
4. **Character creation (#7–9)** — choice + premade dossier + custom forge.
5. **Panels (#15–17, #19–20)** — sheet, party/approval, codex, settings, recap.
6. **Pre-play + Phase-B (#1–6)** — browser, creation, login/account/billing (visual-only).

Wire a top screen-switcher so all 20 are clickable in one file.

---

## Surfaced backend deps (NOT UI — track in Slice 15)
1. **Weave agent** — concept → `bio`/`personality`/`voice_traits`.
2. **Player-rolled death saves** — `roll_death_save` (`combat/rolls.py:65`) → client-roll/`resolve` pattern.
3. **Portrait image-gen** (later/Phase B) — FLUX-schnell earmarked; "Generate" is a flagged affordance only.
4. **`GET /v1/campaigns/templates`** — template-browse endpoint for Home/browser.
