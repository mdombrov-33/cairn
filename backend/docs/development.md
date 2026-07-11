# Backend development guide

This guide covers stable extension points in the backend that exists today. It intentionally omits
recipes for areas whose interface is already scheduled for replacement. Read `roadmap.md` before
using any procedure for feature or architecture work.

## Choose the owner first

Place a change according to the knowledge it owns:

- HTTP representation or authentication dependency -> `api/`.
- A user-visible use case combining persistence, agents, or transactions -> `application/`.
- A reusable calculation, invariant, or domain value -> `domain/`.
- A database read/write -> `db/queries/`.
- A persistence representation -> `db/models/`.
- LLM interpretation, classification, building, or narration -> `agents/` plus `prompts/`.
- Static game-rule data and its validated record -> `srd/`.
- LangGraph topology -> `pipelines/`.
- SSE encoding -> `sse/`.

If a proposed module would only forward the same arguments to one implementation, keep the logic in
the existing owner. Introduce a new interface only when it hides meaningful behavior or serves two
real adapters.

## Implement an HTTP capability

1. Define request and response representation in `api/v1/schemas/`.
2. Add or extend one application workflow that accepts domain values and the request session.
3. Put every database operation needed by that workflow in `db/queries/`.
4. Keep the route to authentication, parsing, one application call, and response/SSE formatting.
5. Add integration coverage for authorization, invalid input, persisted outcome, and exact transport
   representation.

Do not call an agent or query module directly from a route; this is mechanically checked for
`api/v1/routes/`.

## Implement an application workflow

1. Name it after the user or game capability, not a technical mechanism.
2. Accept the request/session dependencies at the outer interface rather than constructing them
   inside reusable helpers.
3. Load and persist through concrete query modules.
4. Pass plain typed values into pure domain rules.
5. Coordinate agents through their typed interfaces when interpretation is required.
6. Make the transaction owner and commit point visible at the outer workflow.
7. Return a typed result that the caller can serialize without learning workflow internals.

Test through the workflow interface with Postgres. Add focused unit tests separately for extracted
pure rules.

## Implement a domain rule

1. Put the rule and its input/output types beside the owning capability in `domain/`.
2. Accept plain values; do not accept `AsyncSession`, ORM models, request schemas, or agent objects.
3. Return a value or explicit result instead of mutating persistence.
4. Encode invariants in the narrowest useful interface.
5. Test observable outcomes, edge cases, and invalid states without database fixtures.

Do not create a generic utilities or shared-types module. A type belongs to the capability that gives
it meaning.

## Change persistence

1. Change the SQLAlchemy model only for the required storage representation.
2. Add reads/writes to the owning query module. Queries may flush but never commit.
3. Coordinate the new operation from an application workflow.
4. Generate the migration with `make revision m="..."`; inspect generated operations and imports.
5. Apply the migration locally and confirm a single Alembic head.
6. Add integration tests for defaults, round trips, ownership, and rollback-sensitive behavior.

For JSONB changes, define the in-memory owner and compatibility strategy first. Do not silently change
existing keys or optionality during a typing or package refactor.

## Add or change an agent

1. Put the agent interface in `agents/<name>.py` and obtain prompt/model/fallbacks with
   `agent_setup(<name>)`.
2. Put the versioned prompt in `prompts/<name>/<version>.md` and model policy in `llm/models.yaml`.
3. Use `complete_to_model` with a strict Pydantic model for decisions consumed by code.
4. Use streaming only for user-facing narration.
5. Keep database access and mutation in the calling application workflow.
6. Test prompt inputs, structured-output mapping, parse-failure policy, and the application behavior
   that consumes the result by patching the LLM client interface.

Do not import LiteLLM, encode deterministic mechanics in a prompt, or give a new agent ownership of a
live ORM mutation loop.

## Extend the SRD catalog

1. Define the record in `srd/models.py` with the strictness appropriate to the source JSON.
2. Load and validate the file once in `srd/catalog.py`.
3. Expose the narrow typed lookup needed by callers rather than the raw document.
4. Preserve existing SRD route JSON when replacing an internal lookup.
5. Test successful validation, malformed data, missing keys, and representative caller behavior.

## Add a foreground suspension or SSE event

1. Define the internal tagged outcome with the turn capability.
2. Keep persisted pause/checkpoint data behind explicit serialization and validation adapters.
3. Add preparation and resumption to the foreground runtime interface.
4. Keep the route responsible only for HTTP input and SSE encoding.
5. Add contract tests for event name/payload, persisted JSON, ownership checks, and resumption.

Slice 10.5 applies this pattern to reactions. Its exact plan/executor/checkpoint contract takes
precedence over a generic implementation inferred from current skill-check code.

## Add post-turn work

1. Add the job to `PostTurnEpilogue`; do not call `asyncio.create_task` from a route or streaming
   function.
2. Give the job its own short-lived database session and explicit transaction where it writes.
3. Keep failure isolation and logging under the epilogue supervisor.
4. Verify scheduling stays non-blocking, one job's failure does not cancel siblings, and shutdown
   awaits or cancels outstanding work.

Do not introduce a queue, worker framework, or outbox until deployment requirements justify durable
execution.

## Areas without a creation recipe

- **Combat plans, execution, attacks, and reactions:** wait for or work directly from Slice 10.5. Do
  not extend the current LLM-controlled mutation loop as a new architecture.
- **LangChain tools and MCP exposure:** work directly from Slice 10.7. It replaces manual tool lists
  with tagged registration and projects the same definitions through FastMCP; no parallel `mcp/`
  tool tree is allowed.
- **World-bible retrieval:** work directly from Slice 13. Do not introduce Qdrant, GraphRAG, or an
  agentic retrieval loop.
- **Authentication and entitlements:** remain Phase-B work. Preserve the development header seam and
  keep model/account policy out of campaign settings.
- **Frontend:** follow Slices 15 and 15.5 after the backend prerequisites are confirmed; mockups are a
  visual specification, not evidence that an endpoint exists.

Once one of these slices is implemented, replace its warning with a recipe describing the landed
interface—not the original plan.

## Verification before commit

Run focused tests during implementation, then from the repository root:

```text
make check
git diff --check
```

Also verify migration heads after schema or persistence movement. Contract-affecting work must assert
the exact HTTP, SSE, JSONB, prompt, or checkpoint shape it owns.
