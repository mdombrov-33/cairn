# Cairn roadmap

This is the forward plan. It deliberately does not repeat completed work or
claim that a locked design is running. For verified implementation, read
[architecture.md](architecture.md). For the full rationale and detailed
acceptance criteria of a planned slice, read the linked section of the
[v5 design archive](archive/design-v5.md).

## Status language

- **Current** is verified in production source and tests.
- **Next** is the one implementation slice to start after this document.
- **Planned** is locked work that has not landed; it is not an interface or a
  recipe to copy into unrelated work.
- **Deferred** has no implementation commitment in the current sequence.

The architecture-improvement campaign is complete. The next implementation
slice is **Slice 10.5 — Reaction engine**. Its archived file map is historical:
use today's package owners from `architecture.md` and `AGENTS.md`, while
preserving the contracts below.

## Ordered work

| Order | Status | Slice | Purpose and dependency | Full specification |
| --- | --- | --- | --- | --- |
| 1 | **Next** | 10.5 | Deterministic combat execution and reactions; depends on the existing zones and campaign settings. | [Reaction engine](archive/design-v5.md#slice-105--reaction-engine) |
| 2 | Planned | 10.7 | Tool registry and FastMCP server; begins only after the 10.5 combat surface is final. | [MCP server + tool registry](archive/design-v5.md#slice-107--mcp-server--tool-registry) |
| 3 | Planned | 11 | Operational hardening before evaluation and frontend SSE work. | [Operational hardening](archive/design-v5.md#slice-11--operational-hardening) |
| 4 | Planned | 12 | Eval suite and CI gate; depends on Slice 11's complete event history. | [Eval suite + CI gate](archive/design-v5.md#slice-12--eval-suite--ci-gate) |
| 5 | Planned | 13 | World-bible retrieval; depends on the Slice 12 baseline for tuning. | [World bible retrieval](archive/design-v5.md#slice-13--world-bible-retrieval-rag) |
| 6 | Planned, Phase B | 14 | Authentication and cost controls. | [Auth + cost controls](archive/design-v5.md#slice-14--auth--cost-controls) |
| 7 | Planned, Phase B | 14.5 | Plans and entitlements; depends on account identity from Slice 14. | [Plans & entitlements](archive/design-v5.md#slice-145--plans--entitlements) |
| 8 | Planned, Phase A | 15 + 15.5 | Frontend product design and implementation. It starts after Slice 10.7 and uses the development header until Phase B auth lands. | [Frontend product spec](archive/design-v5.md#slice-15--frontend-ui-reference-rebuild) · [frontend build architecture](archive/design-v5.md#slice-155--frontend-architecture--build-phase-a) · [v4 build brief](ui-temp-reference/v4-build-brief.md) |

Slice 15's Phase A does **not** wait for Slice 14: it uses the development
`X-User-Id` header behind its swappable frontend auth seam. Login, billing, and
admin screens are visual-only until Phase B. This explicit dependency takes
precedence over older wording in the archive.

## Next — Slice 10.5: reaction engine

Slice 10.5 is a single combat restructuring, not an incremental cleanup of the
current live mutation-tool loop. Its goal is to replace that loop with a
deterministic, interruptible execution module while preserving normal combat
narration when no reaction occurs.

The implementation must:

- make `combat_ai` and `combat_resolver` typed plan producers;
- put operation execution, persistence and transaction policy, checkpoints,
  interruption, and resumption behind one deterministic executor;
- keep the reaction registry internal to that executor; it owns opportunity
  attack, Shield, Absorb Elements, Counterspell, readied actions, and Sentinel;
- introduce deterministic `roll_attack`, including cover as a hard AC modifier;
- use deterministic reaction heuristics for AI combatants, with no new LLM call
  in the combat loop;
- model player reactions using the existing `reaction_control` setting:
  `suggest`, `player`, and `ai`;
- suspend in `session.combat_state` JSONB, emit the exact `reaction_prompt` SSE
  event, and resume through `POST /v1/sessions/{id}/reactions`;
- support LIFO nested reactions (depth cap 4), initiative ordering for
  simultaneous opportunities, and one reaction per creature per round;
- parse a readied action once into a typed trigger and match it
  deterministically at runtime; and
- move combat-owned types beside the plan, execution, reaction, and state
  modules rather than recreating a global type home.

There is no new schema migration. Public HTTP, SSE, JSONB, narration, and
checkpoint representations stay compatible through adapters. The complete
request/response payloads, resource rules, examples, and verification matrix
are locked in the [full Slice 10.5 specification](archive/design-v5.md#slice-105--reaction-engine).

Before this slice lands, do not add a second executor, an ad-hoc reaction
abstraction, a new mutation tool loop, or a generic combat cleanup. See the
roadmap-sensitive constraints in `backend/AGENTS.md`.

## Later locked work

### Slice 10.7 — tool registry and MCP

The tool change is deferred until the combat surface is final. It replaces the
hand-maintained tool lists with a tagged registry and projects the same tool
definition into LangChain and FastMCP. It is a **server-only**, single-process,
streamable-HTTP server mounted at `/mcp`; agents continue to call tools
in-process. There is no `mcp/` tool hierarchy, no client integration, and no
internet exposure before Phase B authentication. Follow the [full locked
specification](archive/design-v5.md#slice-107--mcp-server--tool-registry),
including the known Phase-A concurrency risk.

### Slices 11–13 — reliability, evaluation, and retrieval

- Slice 11 hardens timeouts, failed SSE turns, event persistence, tool-loop
  atomicity, LoreKeeper retries, hooks, and model fallbacks.
- Slice 12 adds the evaluation baseline and CI gate for prompts and agents.
- Slice 13 is small-corpus retrieval: pgvector and Postgres FTS/tag fusion with
  RRF, local FastEmbed embedding and reranking, scene-scoped lore caching, and
  graceful degradation. It is neither an external vector database nor an
  agentic retrieval loop.

Each slice's complete requirements remain in its linked row above. Do not
pre-implement a retrieval alternative or evaluation framework while working on
an earlier slice.

### Phase B — identity and account policy

Slice 14 replaces the development identity shim with Clerk-based authentication,
campaign access control, rate limiting, and inference cost tracking. Slice 14.5
then establishes one user-owned `free | plus | pro` entitlement. An account
tier selects hosted model bundles and caps; campaign settings never select a
model tier. BYOK is orthogonal, real checkout is later, and safety, content,
retrieval, builders, and agency are never paywalled. The archived specs are the
source for the exact persistence, enforcement, and deferred-payment decisions.

### Frontend — Slices 15 and 15.5

The current frontend source of truth is the [v4 build brief](ui-temp-reference/v4-build-brief.md),
not older HTML prototypes or v3 brief. Its product direction is “Cartographer's
Table.” Slice 15.5 locks Vite + React 19, TanStack Router/Query, Zustand,
Tailwind v4, React Aria Components, React Flow, generated OpenAPI types,
RHF/Zod, Motion, and the stated test stack. Build frontend contracts only after
their engine dependencies are present; the visual mockups never authorize a new
backend contract.

## Deferred work

Advanced combat mechanics beyond the 10.5 scope, additional game systems,
multi-user clients, richer lore visualization, and the remaining v2 platform
ideas are deferred. Their historical candidates and resolved decisions are
preserved in [Future / out of scope](archive/design-v5.md#future--out-of-scope-for-v1).
They are not a backlog to pull into the next slice.

## Updating this roadmap

When a planned slice lands:

1. Update `architecture.md` with only the verified current design.
2. Add stable extension guidance to `development.md` and remove the corresponding
   warning from `backend/AGENTS.md`.
3. Change this roadmap's status and ordering without copying implementation
   history into it.
4. Keep `archive/design-v5.md` as historical evidence; do not retrofit its old
   paths or completion claims.

This keeps a future agent's read order small: active roadmap → exact archived
slice → current architecture → package instructions.
