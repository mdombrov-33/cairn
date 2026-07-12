# Backend architecture

This document describes the backend that exists now. Future specifications live in `roadmap.md`; an
item appearing there is not part of the current architecture until its implementation, tests, and
this document land together.

## System shape

Cairn is a FastAPI application backed by Postgres. LangGraph routes non-combat turns, LiteLLM is the
single provider gateway, and Server-Sent Events stream narration and mechanical events. Application
workflows coordinate persistence and agents; pure domain modules own calculations and invariants.

```text
HTTP / SSE
    -> application workflows
        -> domain rules and SRD catalog
        -> query adapters -> SQLAlchemy models -> Postgres
        -> agents -> llm/client.py -> LiteLLM
    -> pipelines for graph topology and routing
```

The dependency direction is intentionally asymmetric. Domain code knows nothing about the runtime.
Query adapters know storage, while application workflows know when and why queries are combined.

## Package map

- `api/` — FastAPI dependencies, middleware, schemas, routes, and transport error mapping.
- `application/` — campaign, character, scene, narrative, rest, combat, and turn workflows.
- `application/turns/runtime.py` — foreground turn preparation, continuation, and resumption interface.
- `application/turns/epilogue.py` — supervised non-blocking post-turn work.
- `application/combat/` — current persistence-aware combat mutations, rolls, state, events, and zones.
- `domain/` — capability-owned values and pure rules.
- `db/models/` — SQLAlchemy models and JSONB persistence annotations.
- `db/queries/` — the only database-access modules.
- `agents/` — LLM-backed classifiers, interpreters, builders, directors, and narrators.
- `llm/` — model routing and the sole LiteLLM client.
- `pipelines/` — LangGraph construction and routing.
- `prompts/` — versioned markdown/Jinja prompts.
- `srd/` — cached typed catalog over static rules JSON.
- `tools/` — tagged LangChain-callable adapters and their shared registry.
- `api/mcp.py` — the FastMCP projection of registered tools.
- `sse/` — SSE event serialization.

Types live with these owners. There is no global `cairn/types.py`.

## Foreground turn flow

`POST /v1/sessions/{id}/turns` first crosses `TurnRuntime.prepare`. Outside combat, preparation runs
the LangGraph turn graph: the graph constructs and routes nodes while application turn resolvers own
persistence and agent coordination. Preparation can produce a tagged internal suspension for a skill
check or companion proposal.

The route then crosses `TurnRuntime.continue_turn`, converts typed runtime events to SSE frames, and
streams Scene Narrator output. Persisted `Turn.check_data` remains the compatibility representation
for suspended turns; the typed runtime validates and adapts it when resuming.

Check and companion endpoints prepare a resumption through the runtime, validate campaign ownership
and persisted pause data, then continue the same turn. Route code does not interpret suspension
payloads.

Standalone rest endpoints cross the rest workflow before SSE formatting. A safe scene applies the
rest immediately; a hostile scene emits `rest_blocked`; and a risky scene emits
`rest_confirmation_required` without changing state. Repeating that request with
`{"confirm_risky": true}` explicitly accepts the ambush risk and applies the rest. Player-controlled
prepared casters choose spells after a long rest, while AI-controlled companions deterministically
retain legal preparations and fill remaining slots from the typed SRD catalog.

When combat is active, combat agents produce strict ordered plans without mutation tools. The combat
executor derives mechanics from campaign, combat, actor, and SRD state and executes operations
deterministically. It owns combat commits, engine attack rolls, reaction dispatch, persisted
checkpoints, and resumption. Completed facts reach Scene Narrator only after execution finishes.

The executor-private reaction registry covers opportunity attacks, Shield, Absorb Elements,
Counterspell, readied actions, and Sentinel. Player reactions follow `reaction_control`; interactive
opportunities persist `pending_reaction` in combat-state JSONB and emit `reaction_prompt`.
`POST /v1/sessions/{id}/reactions` validates the checkpoint and continues the same turn.

## Post-turn work

After narration, foreground code schedules one `PostTurnEpilogue`. It supervises four independent
in-process jobs:

- LoreKeeper extraction and world-bible persistence;
- Scene Director post-pass and scene/time/act updates;
- scene-progress summarization;
- companion reflection and approval updates.

Scheduling is non-blocking. The epilogue owns task tracking, consistent failure logging, cancellation,
and graceful shutdown through the FastAPI lifespan. It is deliberately in-process; no durable queue or
outbox exists.

## Tool registry and MCP server

Every LLM-callable tool is decorated with `tools.registry.register`. The registry creates the
LangChain tool, records its tags and MCP eligibility, and derives `ALL_TOOLS` plus the legacy
`COMBAT_TOOLS` subset. The latter has no current production consumer after the plan-based combat
slice, but remains a compatibility export.

`api/mcp.py` projects the same registered async coroutine into FastMCP; it does not wrap or
reimplement a tool. When `MCP_ENABLED` is enabled (by default only in `ENV=dev`), the FastAPI app
mounts a single-process Streamable HTTP server at `/mcp` and runs its session manager inside the
application lifespan alongside the checkpointer and post-turn shutdown.

The MCP server exposes the full stateful engine without authentication for local Phase-A use only.
Do not expose it to the internet before Phase-B authentication. Concurrent MCP and internal writes
to one `combat_state` row can lose an update; locking or optimistic concurrency remains Phase-B work.

## Persistence and transaction contexts

Request routes receive one `AsyncSession` from `api/deps.py`. The dependency commits a successful
request and rolls back an exception, so ordinary application workflows participate in one request
transaction.

Code that runs outside that lifetime opens an explicit session:

- graph and foreground workflows that must persist before streaming;
- standalone LangChain tools;
- each post-turn epilogue job.

Query adapters execute reads and writes and may flush, but do not commit. The owning workflow defines
the transaction. Reusable combat operations flush without committing; the executor commits completed
combat work and reaction checkpoints, while standalone combat tools use their outer session context.

## Typed data seams

Runtime code uses capability-owned typed values. Storage and public transport still require exact
dictionary representations:

- Campaign settings are strict immutable Pydantic models in memory and dictionaries in JSONB/HTTP.
- Turn suspensions are tagged runtime values adapted to the existing `Turn.check_data` JSONB shape.
- Character, combat, scene, and narrative JSONB dictionaries use owner-local typed definitions.
- SRD JSON is validated once by the cached catalog and returned through typed records, including armor-class data.
- SSE events remain dictionary payloads encoded centrally by `sse/events.py`.

Architecture refactors preserve these representations unless a feature specification explicitly
changes the contract.

## LLM seam

`llm/router.py` resolves an agent's prompt version, model, and fallbacks. Agents call completion,
structured-output, tool-loop, or streaming interfaces in `llm/client.py`; only that module imports
LiteLLM. Mechanical calculations remain deterministic code even when an agent chooses or narrates an
action.

Combat planners use structured output. Mechanical values, legality, resources, rolls, and mutation are
owned by deterministic application code rather than prompts.

## Enforced architecture

`tests/unit/test_architecture.py` verifies:

- domain purity;
- pipeline isolation from persistence and direct LLM calls;
- LiteLLM confinement;
- absence of a global shared-types module;
- the foreground turn-runtime seam;
- v1 route isolation from direct agent and query coordination;
- purity of migrated domain capabilities.

The source is checked by mypy and Pyright; strict Pyright covers all production modules. The full CI
gate is `make check`.

## Planned, not implemented

The current roadmap locks several future shapes that must not be mistaken for present behavior:

- **Slice 13:** pgvector/FTS/tag hybrid retrieval with RRF and local reranking. There is no vector
  retrieval path today.
- **Phase B:** operational hardening, eval gates, Clerk authentication, entitlements, and deployment
  hardening.
- **Slices 15/15.5:** the Vite/React frontend. The repository remains backend-only today.

Read the relevant roadmap section before touching one of these areas; its old file paths are
illustrative and must be reconciled with the current package map above.
