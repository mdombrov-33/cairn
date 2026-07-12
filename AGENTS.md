# Cairn coding instructions

Cairn is an AI Dungeon Master platform for persistent tabletop campaigns. The Python backend lives
in `backend/`; no frontend package exists yet.

## Read before acting

1. Read the nearest `AGENTS.md` files from the repository root to the target file.
2. Check the working tree and preserve unrelated user changes.
3. Read `CONTEXT.md` when domain language or ownership matters.
4. Read `backend/docs/architecture.md` for current implementation, `backend/docs/roadmap.md` for
   feature or product-contract work, and only the relevant accepted ADRs.

Code and tests are evidence of what exists. The roadmap specifies intended outcomes and constraints;
it does not prove that a feature, file map, or proposed internal mechanism is still appropriate.

## Working principles

### Think before coding

- Before implementation, state a short plan with observable success criteria.
- Surface assumptions, ambiguities, and contract risks. Do not silently choose a materially different
  behavior.
- Distinguish **Current** behavior verified in code from **Planned** behavior specified only in the
  roadmap.
- Re-check callers and current ownership before following an older design. If the proposed machinery
  no longer earns its keep, use the simpler design that still satisfies the required outcome.

### Simplicity first

- Make the smallest coherent change that satisfies the current request.
- Do not add speculative abstractions, metadata, configuration, extension points, or compatibility
  layers.
- An abstraction must hide meaningful complexity or serve real current variation. One concrete
  adapter does not justify a generic port or repository protocol.
- Apply the deletion test: if removing a module makes complexity disappear rather than reappear in
  callers, the module is probably unnecessary.
- Prefer a direct implementation until a seam is demonstrated by callers, tests, or multiple
  adapters.

### Change surgically

- Do not mix feature work with unrelated cleanup. Report adjacent problems separately.
- Local inspection, scoped edits, and tests may proceed autonomously. Ask before deployment, external
  communication, destructive data operations, or work outside the requested contract.
- Preserve runtime behavior during architecture work unless behavior change is explicitly in scope.
- Treat HTTP, SSE, typed JSON, JSONB, prompt, checkpoint, persistence, and gameplay representations
  as frozen unless the request authorizes a contract change.
- Never weaken checks, suppress errors, or rewrite tests merely to make a gate pass. Fail loudly and
  report the mismatch.

### Execute against outcomes

- Test through the interface callers use and match verification depth to risk.
- Update only the documentation that owns the changed fact.
- Finish one coherent iteration before starting another.
- The diff, owned documentation, and commit are the audit trail. Do not create session-memory or
  progress-log files.

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

Run `uv` commands from `backend/`. Add packages with `uv add`; never edit dependency lists or the
lockfile by hand.

## Documentation ownership

- `CONTEXT.md` — domain glossary only.
- `AGENTS.md` — imperative working rules only.
- `backend/docs/architecture.md` — current implementation.
- `backend/docs/development.md` — stable, currently supported extension procedures.
- `backend/docs/adr/` — durable decisions and their reasons, written sparingly.
- `backend/docs/roadmap.md` — future sequencing, product constraints, and deferred work.

Link to the owner instead of duplicating guidance. Do not record completed-slice history in active
instructions.

## Completion gate

- Pure rules: focused unit tests.
- Persistence and workflows: focused integration tests.
- HTTP, SSE, JSONB, prompts, or checkpoints: contract tests.
- Import or ownership changes: architecture tests.
- Persistence movement or schema changes: confirm one clean Alembic head.

Every completed implementation iteration ends with `make check`, `git diff --check`, an intentional
commit, and a report of the commit hash and message.
