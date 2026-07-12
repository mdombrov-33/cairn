# Backend coding instructions

These instructions apply under `backend/` in addition to the repository root `AGENTS.md`.

## Evidence before design

- **Current** means verified in production source and tests and documented in `docs/architecture.md`.
- **Planned** means specified in `docs/roadmap.md` but not yet implemented.
- Never present planned work as an available interface.
- A roadmap outcome may be locked while its old file map or suggested internal mechanism is stale.
  Re-derive the smallest implementation from current code. Ask before changing the locked outcome or
  public contract, not before simplifying unused internal machinery.
- Before adding a module or seam, identify its callers, the complexity it hides, the variation it
  serves, and the interface-level test. If those are absent, keep the implementation direct.

## Package ownership

| Package | Owns | Must not own |
| --- | --- | --- |
| `api/` | HTTP parsing, authentication dependencies, schemas, response and SSE formatting | Business rules, agent coordination, query orchestration |
| `application/` | Use-case workflows, persistence coordination, transactions, agent coordination | HTTP formatting, reusable pure calculations |
| `domain/` | Pure values, calculations, invariants, capability-owned types | SQLAlchemy, FastAPI, queries, agents, application, pipelines |
| `db/models/` | SQLAlchemy persistence representations | Gameplay and workflow decisions |
| `db/queries/` | Selection, ORM construction, deletion, reusable persistence mutations, flush, lookup errors | Commits, LLM calls, cross-capability workflows |
| `agents/` | Prompt assembly and typed interpretation, classification, narration | Persistence ownership, live ORM mutation |
| `tools/` | Thin LangChain adapters registered once and projected to FastMCP | Rules, orchestration, a second tool definition |
| `pipelines/` | LangGraph construction, routing, delegation | Persistence, direct LLM calls, business logic |
| `prompts/` | Versioned LLM instructions and Jinja inputs | Deterministic mechanics |
| `srd/` | Validated cached rules catalog and SRD-owned records | Campaign or session state |
| `sse/` | Typed workflow-event transport encoding | Workflow decisions |

Prefer deep application modules: callers cross a small interface while persistence, agent
coordination, and sequencing remain inside. Do not expose internal seams merely for tests.

## Hard constraints

- All LLM provider calls go through `src/cairn/llm/client.py`.
- Database selection, ORM construction, deletion, and reusable persistence operations live in
  `src/cairn/db/queries/`.
- Domain code stays pure and imports no FastAPI, SQLAlchemy, queries, agents, application code, or
  pipelines.
- Database schema changes use generated Alembic revisions; never add standalone migration SQL.
- Types live beside the capability that owns their meaning; do not create `cairn/types.py`.
- Tools live under `src/cairn/tools/`; do not create a parallel `mcp/` tool hierarchy.
- Do not add a generic port or repository protocol for one concrete adapter.
- Preserve existing typed JSON, HTTP, SSE, JSONB, prompt, and checkpoint representations unless a
  contract change is explicitly in scope.

`tests/unit/test_architecture.py` mechanically enforces domain purity, pipeline isolation, exclusive
LiteLLM ownership, route/application seams, and the absence of a global types module. Add an
architecture test with any new rule that can be expressed mechanically.

## Persistence and transactions

- Query functions accept an `AsyncSession`, perform database operations, and may `flush`; they do not
  commit.
- Ordinary HTTP workflows share the request session. `api/deps.py` commits successful requests and
  rolls back failures.
- Graph nodes, tools, and post-turn work open their own sessions because they run outside the request
  transaction. Their owning application workflow defines the atomic unit.
- Make transaction ownership visible at the outer workflow seam. Do not add hidden commits to
  reusable inner functions.
- Application workflows may coordinate mutation of loaded ORM entities. Domain functions receive
  plain values and return plain results.

## Types and representation seams

- Use immutable strict Pydantic models for validated configuration and structured agent output.
- Use `TypedDict` for owned dictionary-shaped JSON contracts that must remain dictionaries.
- Read optional `TypedDict` keys with `.get()` or an explicit membership check.
- Validate external JSON once at its seam and convert explicitly at JSONB and HTTP seams.
- Do not leak ORM models or unvalidated dictionaries into pure rules.

Moving Python ownership does not authorize changing a stored or transported representation.

## LLM, agents, and prompts

- Agents obtain prompt, model, and fallback policy through `agent_setup()` and call only interfaces
  in `llm/client.py`.
- New agent tools have one clear, non-overlapping intent, validated inputs, and explicit failures.
  Reducing tool count alone does not justify replacing intent-named operations with mode flags or
  signed deltas.
- Prefer structured Pydantic output for decisions consumed by application code.
- Agents interpret, classify, plan, or narrate. Deterministic code owns mechanics and mutation.
- Keep versioned prompt inputs synchronized with callers and test material prompt behavior.
- Schedule post-turn LLM work only through `application/turns/epilogue.py`.
- Combat agents produce typed plans and never receive live mutation tools. The deterministic executor
  owns derivation, reactions, persistence, interruption, and resumption.

## Verification

- Unit tests exercise pure domain interfaces and deterministic mappings.
- Integration tests exercise application workflows with Postgres and verify persisted outcomes.
- Route tests assert status, response models, authorization, and SSE contracts.
- Agent tests patch the LLM client interface, not LiteLLM.
- Tests for a deepened module cross the same interface as production callers; remove obsolete tests of
  shallow internals after replacement coverage exists.

Run focused tests while iterating. Before committing, run `make check` and `git diff --check` from the
repository root, plus an Alembic head check for schema or persistence movement.
