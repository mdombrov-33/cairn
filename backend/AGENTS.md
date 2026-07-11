# Backend working instructions

These instructions apply under `backend/` in addition to the repository root `AGENTS.md`.

## Establish the time boundary

Use three labels consistently when reasoning about the backend:

- **Current** means verified in production source and tests.
- **Planned** means locked or proposed in `docs/roadmap.md` but not yet implemented.
- **Legacy deviation** means current code that violates the preferred shape and must not be copied.

Never present planned work as an available interface. Never describe a legacy deviation as the
creation recipe. Before implementing a roadmap slice, re-check every path in its old file map because
the architecture campaign moved many owners from `domain/services/` into `application/`.

## Current package ownership

| Package | Owns | Must not own |
| --- | --- | --- |
| `api/` | HTTP parsing, authentication dependencies, schemas, response and SSE formatting | New business rules, direct agent coordination, new query orchestration |
| `application/` | Use-case workflows, persistence coordination, transaction decisions, agent coordination | HTTP formatting, reusable pure calculations |
| `domain/` | Pure values, calculations, invariants, and capability-owned types | SQLAlchemy, FastAPI, queries, agents, application, pipelines |
| `db/models/` | SQLAlchemy persistence representations | Gameplay and workflow decisions |
| `db/queries/` | Database selection, ORM construction, deletion, reusable persistence mutations, flush, and lookup errors | Commits, LLM calls, cross-capability workflows |
| `agents/` | Prompt assembly and typed interpretation, classification, or narration | New persistence ownership or live ORM mutation |
| `tools/` | Thin LangChain adapters around application capabilities | Duplicated rules and orchestration |
| `pipelines/` | LangGraph construction, routing, and delegation | Persistence, direct LLM calls, business logic |
| `prompts/` | Versioned LLM instructions and Jinja inputs | Mechanical truth that deterministic code can enforce |
| `srd/` | Validated, cached rules catalog and SRD-owned records | Campaign or session state |
| `sse/` | Encoding typed workflow events for transport | Workflow decisions |

Prefer deep application modules: callers cross a small interface while persistence, agent
coordination, and sequencing remain inside. Do not add a port or repository protocol unless two real
adapters exist.

## Enforced constraints

`tests/unit/test_architecture.py` enforces the constraints that are hard today:

- `domain/` has no persistence, application, agent, pipeline, or framework imports.
- `pipelines/` has no persistence or direct LLM client imports.
- LiteLLM is confined to `llm/client.py`.
- The removed global `cairn/types.py` is not recreated.
- HTTP turn routes cross `application/turns/runtime.py`.
- HTTP v1 routes do not coordinate agents or query modules directly.

When adding a new architectural rule, add an architecture test in the same change if it can be
expressed mechanically.

## Persistence and transactions

- Query modules accept an `AsyncSession`, perform database operations, and may `flush`; they do not
  commit.
- Ordinary HTTP workflows share the request session. `api/deps.py` commits after a successful request
  and rolls back on failure.
- Graph nodes, tools, and post-turn work open their own sessions because they execute outside the
  ordinary request transaction; their owning application workflow defines the atomic unit.
- New application workflows should make transaction ownership visible at the outer workflow seam.
  Avoid hidden commits in reusable inner functions.

Legacy deviation: several existing resource and transition functions commit internally. Do not copy
this pattern. Combat mutation and transaction policy are consolidated in the combat executor.

Application workflows may coordinate and mutate ORM entities loaded through query adapters when the
capability requires it, but domain functions receive plain values and return plain results.

## Types and representation seams

- Put a type beside the capability that defines it: character types in `domain/characters.py`, combat
  types in combat modules, turn types in `application/turns/`, and transport schemas in `api/` or
  `sse/`.
- Use immutable strict Pydantic models for validated configuration and agent structured output.
- Use `TypedDict` for owned dictionary-shaped JSON contracts when their storage representation must
  remain a dictionary.
- Optional `TypedDict` keys must be read with `.get()` or an explicit membership check.
- Validate external JSON once at its seam. The typed SRD catalog is the model for static rule data.
- Convert typed values explicitly at JSONB and HTTP seams; do not leak ORM models or unvalidated
  dictionaries into pure rules.

Changing a Python owner does not authorize changing stored JSONB, checkpoint, HTTP, or SSE shapes.

## LLM, agents, and prompts

- Agents obtain prompt/model/fallback policy through `agent_setup()` and call only interfaces in
  `llm/client.py`.
- Prefer structured Pydantic output for decisions that application code consumes.
- Agents interpret, classify, plan, or narrate. Deterministic code owns mechanics and mutation.
- Prompt files are versioned and selected through `LLM_PROMPT_VERSIONS`; keep their input contract
  synchronized with the calling agent and cover material prompt behavior with tests.
- Post-turn LLM work is scheduled only through `application/turns/epilogue.py`, which owns task
  tracking, failure isolation, and shutdown.

Combat agents produce typed plans and never own live mutation tools. The deterministic executor owns
mechanical derivation, reactions, persistence, interruption, and resumption.

## Roadmap-sensitive areas

The following are locked plans, not current interfaces:

| Area | Current | Planned owner | Instruction before its slice lands |
| --- | --- | --- | --- |
| Tool registration and MCP | LangChain tools with hand-maintained lists; no MCP endpoint | Slice 10.7 tagged registry and FastMCP projection from the same tools | Do not add a general tool-creation recipe or a parallel `mcp/` hierarchy |
| Retrieval | Direct context assembly from authored lore and campaign memory | Slice 13 pgvector + FTS + tag RRF retrieval and local reranking | Do not add an alternate vector database or agentic retrieval loop |
| Authentication | Development `X-User-Id` header | Phase-B Clerk auth and user-owned limits | Do not treat the shim as production auth or invent a competing auth seam |
| Entitlements | Account-tier model bundles are configuration only | Slice 14.5 user entitlements and enforcement | Campaign settings never choose a model tier |
| Frontend | No frontend package | Slices 15/15.5 Vite React SPA | Do not invent backend contracts from the visual mockups; follow locked dependencies in the roadmap |

After one of these slices lands, move its stable creation guidance into `docs/development.md`, update
`docs/architecture.md`, and remove its warning row here in the same commit.

## Testing and verification

- Unit tests exercise pure domain interfaces and deterministic mapping logic.
- Integration tests exercise application workflows with Postgres and verify persisted outcomes.
- Route tests assert status, response models, authorization, and SSE event contracts.
- Agent tests patch the LLM client interface, not LiteLLM.
- Tests for a deepened module cross the same interface as production callers; do not preserve tests of
  obsolete shallow internals after replacement coverage exists.

Run focused tests while iterating. Before committing, run `make check` from the repository root,
`git diff --check`, and an Alembic head check whenever persistence ownership or schema changes.
