# Cairn UI reference — Ember canon

These files are the canonical visual reference for Cairn's planned frontend. They are static design
documents, not evidence that a backend route exists. Current engine behavior is described in
[`../architecture.md`](../architecture.md); sequencing and planned contracts live in
[`../roadmap.md`](../roadmap.md).

The archived `Cairn App v4.html` remains design history. Its screen inventory and interaction
research informed this reference, but its Slate Survey palette and exact component treatments are
superseded by Ember.

## Direction

**Ember** is a campaign ledger read by firelight. The interface should feel written, accumulated,
and handled—not decorated like generic fantasy software.

- **Palette:** candle-black `#0A0806`, table `#0E0B07`, ledger `#14100A`, parchment `#F3E8CD`,
  ember-gold `#D6A452`, lichen `#9A8E5C`, and hazard red `#C84B2F`.
- **Type:** Cormorant Garamond for rare display moments, Newsreader for narration and reading,
  Space Grotesk for controls, and Space Mono for rules, time, and mechanical state.
- **Signature:** the campaign is a waymarked trail. Its rail, exploration map, combat zones,
  progress steps, and interruption markers share one cartographic vocabulary.
- **Motion:** one orchestrated transformation when play changes mode. Routine controls stay quiet.
- **Structure:** prose stays central; mechanics accumulate in the margin or on the table without
  replacing the story.

Gold means guidance or a chosen action, lichen means established/healthy/done, and red means danger,
interruption, or the current hazardous point. Do not use all three merely to decorate a panel.

## Contract labels

Every capability that is not current must be labeled in the reference:

- **CURRENT** — verified in source and exposed by today's engine.
- **PLANNED · PHASE A** — locked frontend or engine work that is not implemented yet.
- **VISUAL ONLY · PHASE B** — account, billing, authentication, or admin direction awaiting Phase B.
- **DEFERRED** — intentionally outside the planned frontend slice.

Never make a planned affordance look wired by adding fake success, usage, pricing, validation, or
administrative data. Mock content may demonstrate layout; annotations must state the real dependency.

## Files

- `Cairn Landing.dc.html` — public thesis: one campaign performed down the page.
- `Cairn App - Shell.dc.html` — login, campaign browser, world/template choice, campaign framing,
  account, plans, and epilogue.
- `Cairn App - Creation.dc.html` — premade path, custom forge, and level-up.
- `Cairn App - Play.dc.html` — exploration, checks, combat, reactions, dying, loot, rest, spell prep,
  and recap.
- `Cairn App - Panels.dc.html` — character, party, codex, map, and campaign settings.
- `Cairn App - Admin.dc.html` — Phase-B authoring direction grounded only in the existing world,
  lore-chunk, and campaign-template representations.
- `Cairn App - Themes.dc.html` — the five lights applied to the same Ember structure.
- `Cairn UI Directions.dc.html` — historical exploration; not an implementation contract.

`reference.css` supplies the shared theme, focus, reduced-motion, and responsive floor.
`reference-theme.js` persists appearance per device under `cairn-ref-theme`.

## Implementation floor

The future React app must preserve the exact HTTP, SSE, JSONB, prompt, and checkpoint contracts that
exist when its slice begins. It must also provide keyboard-visible focus, reduced motion, and a
purpose-built narrow layout. These static documents demonstrate hierarchy; fixed mock data and the
developer screen switchers are not production navigation.
