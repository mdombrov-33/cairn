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
- `tools/` — current LangChain-callable adapters.
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

When combat is active, the current implementation bypasses non-combat intent routing. Combat agents
run LangChain mutation tools, those tools open independent database sessions, and the completed facts
are passed to narration. This is current but transitional: Slice 10.5 replaces it with typed plans and
a deterministic executor. No reaction endpoint or `reaction_prompt` SSE event exists yet.

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

## Persistence and transaction contexts

Request routes receive one `AsyncSession` from `api/deps.py`. The dependency commits a successful
request and rolls back an exception, so ordinary application workflows participate in one request
transaction.

Code that runs outside that lifetime opens an explicit session:

- graph and foreground workflows that must persist before streaming;
- LangChain tools invoked during the current combat loop;
- each post-turn epilogue job.

Query adapters execute reads and writes and may flush, but do not commit. The owning workflow defines
the transaction. Some older application combat/resource/transition functions still commit internally;
these are legacy semantics, not the preferred interface, and remain frozen until their owning slice.

## Typed data seams

Runtime code uses capability-owned typed values. Storage and public transport still require exact
dictionary representations:

- Campaign settings are strict immutable Pydantic models in memory and dictionaries in JSONB/HTTP.
- Turn suspensions are tagged runtime values adapted to the existing `Turn.check_data` JSONB shape.
- Character, combat, scene, and narrative JSONB dictionaries use owner-local typed definitions.
- SRD JSON is validated once by the cached catalog and returned through typed records.
- SSE events remain dictionary payloads encoded centrally by `sse/events.py`.

Architecture refactors preserve these representations unless a feature specification explicitly
changes the contract.

## LLM seam

`llm/router.py` resolves an agent's prompt version, model, and fallbacks. Agents call completion,
structured-output, tool-loop, or streaming interfaces in `llm/client.py`; only that module imports
LiteLLM. Mechanical calculations remain deterministic code even when an agent chooses or narrates an
action.

The current combat mutation loop is the notable transitional exception to the intended planner shape.
It is replaced only by Slice 10.5.

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

- **Slice 10.5:** typed combat plans, deterministic execution, engine-owned to-hit, reaction registry,
  reaction suspension/resumption, and a reaction HTTP/SSE contract.
- **Slice 10.7:** tagged tool registry, symmetric tool consolidation, and a FastMCP server mounted at
  `/mcp`. There is no MCP server today.
- **Slice 13:** pgvector/FTS/tag hybrid retrieval with RRF and local reranking. There is no vector
  retrieval path today.
- **Phase B:** operational hardening, eval gates, Clerk authentication, entitlements, and deployment
  hardening.
- **Slices 15/15.5:** the Vite/React frontend. The repository remains backend-only today.

Read the relevant roadmap section before touching one of these areas; its old file paths are
illustrative and must be reconciled with the current package map above.
