# Cairn working instructions

## Start here

Cairn is an AI Dungeon Master platform for persistent tabletop campaigns. The repository currently
contains the Python backend in `backend/`; a frontend is planned but not present.

Before changing code:

1. Read the nearest `AGENTS.md` files from the repository root to the target file.
2. Read `CONTEXT.md` when domain terms or ownership are involved.
3. Read `backend/docs/roadmap.md` before feature, architecture, or product-contract work.
4. Read relevant accepted decisions in `backend/docs/adr/`.
5. Check the working tree and preserve unrelated user changes.

The roadmap describes planned behavior. It does not prove that behavior is implemented. Verify the
live code and `backend/docs/architecture.md` before relying on a roadmap statement.

## Commands

Run project commands from the repository root:

```text
make dev          start the API with hot reload
make test         run the test suite
make check        run formatting, lint, type checks, and tests
make migrate      apply pending migrations
make revision m="add x table"  generate an Alembic revision
make up / down    start or stop local infrastructure
```

Run `uv` commands from `backend/`. Always add packages with `uv add`; never edit dependency lists or
the lockfile by hand.

## Working method

Before implementation, state a short plan with observable success criteria. Distinguish:

- **Current** — verified in code and safe to document as available.
- **Planned** — specified by the roadmap but not implemented.
- **Legacy deviation** — present in code but not a pattern for new work.

Make the smallest coherent change that satisfies the request. Do not add speculative abstractions,
configurability, cleanup, or adjacent fixes. When the work exposes an unrelated bug, report it and
leave it separate.

For architecture-only work, preserve runtime behavior unless the user explicitly includes a behavior
change. HTTP, SSE, JSONB, prompt, persistence, and gameplay contracts are frozen by default.

For the established slice workflow, finish one coherent iteration, update the documentation owned by
that change, run the required checks, commit it, and provide the commit hash and message before the
user compacts the session.

## Universal constraints

- All LLM provider calls go through `backend/src/cairn/llm/client.py`.
- Database selection, ORM construction, deletion, and reusable persistence operations live in
  `backend/src/cairn/db/queries/`; application workflows may coordinate mutation of loaded ORM
  entities inside their owned transaction.
- Domain code is pure and has no FastAPI, SQLAlchemy, query, agent, application, or pipeline imports.
- Database schema changes use Alembic generation; never write standalone migration SQL.
- Types live with the capability that owns their meaning; do not recreate a global shared-types file.
- Do not introduce a generic port or repository protocol for a single concrete adapter.
- Preserve existing public representations at typed JSON, HTTP, SSE, and checkpoint seams.
- Tools live under `backend/src/cairn/tools/`; do not create a separate `mcp/` tool hierarchy.

Backend placement rules, current flows, known deviations, and roadmap-sensitive areas are in
`backend/AGENTS.md`.

## Documentation ownership

- `CONTEXT.md` — domain glossary only; no package paths, implementation decisions, or progress log.
- `AGENTS.md` — imperative working rules; no completed-slice history.
- `backend/docs/architecture.md` — current implementation only.
- `backend/docs/development.md` — procedures for stable, currently supported extension points.
- `backend/docs/adr/` — durable decisions and their reasons, written sparingly.
- `backend/docs/roadmap.md` — future sequencing, locked specifications, and deferred work.

Do not duplicate the same guidance across these files. Link to its owner.

## Verification

Match verification to risk:

- Pure rules: focused unit tests.
- Persistence and workflows: focused integration tests.
- HTTP, SSE, JSONB, prompts, or checkpoints: contract tests for the unchanged representation.
- Import or ownership changes: architecture tests.
- Persistence movement or schema work: confirm a single clean Alembic head.

Every completed implementation iteration ends with `make check` and `git diff --check`. Do not weaken
checks, suppress errors, or change tests merely to make the gate pass.
