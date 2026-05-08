## Project

### What this is
FastAPI backend for an AI Dungeon Master platform. Players submit text turns; agents classify intent, route through a LangGraph pipeline, and stream DM responses as SSE. Postgres for state, LangGraph for orchestration, LiteLLM as the universal LLM gateway.

Working directory for all backend work: `backend/`. Run everything from the repo root via `make`.

### Key commands
```
make dev          # start API with hot reload
make test         # run all tests (uv run pytest)
make check        # full CI gate: format + lint + typecheck + tests
make migrate      # apply pending migrations
make revision m="add x table"  # autogenerate migration
make up / down    # docker-compose infra (postgres + redis)
```
**Package management: always `uv add <package>`. Never edit `pyproject.toml` by hand** — uv owns the lockfile.

### Layers — don't mix them
```
api/v1/routes/     HTTP only. Parse → call service → format. No ORM, no LLM calls.
domain/services/   Business logic. Zero FastAPI or SQLAlchemy imports (unit-testable in isolation).
db/queries/        Single source of all DB access. Services, agents, tools — all go through here.
agents/            One file per agent. Each uses agent_setup() and complete()/complete_with_tools().
tools/             LangChain @tool functions. Registered in tools/__init__.py.
pipelines/         LangGraph graphs. Orchestration only — no business logic.
llm/client.py      All LLM calls. Never import litellm directly anywhere else.
prompts/           Versioned markdown + Jinja2. Loaded via load_prompt(name, version).
```

### How a turn flows
```
POST /sessions/{id}/turns
  → turns.service.prepare()
      if session.combat_active → intent = "combat_action" (bypasses graph)
      else → turn_graph.run() → IntentRouter classifies:
          narrative_action  → SceneNarrator streams tokens
          skill_check       → RulesLawyer → check_required SSE → [player rolls] → SceneNarrator
          npc_dialogue      → NPCDialogue → SceneNarrator
          combat_action     → CombatResolver (tool loop) → enemy turns via combat_ai → SceneNarrator
  → turn_end SSE event
  → LoreKeeper fires async (fire-and-forget via asyncio.create_task)
```

### Adding an agent
1. `agents/<name>.py` — use `agent_setup(name)` from `llm/router.py` to get `(prompt, model, fallbacks)`
2. `prompts/<name>/v1.md` — frontmatter: `temperature`, `version`. Body is a Jinja2 template.
3. `llm/models.yaml` — add entry under `agents:` (primary + fallback per env tier)
4. Wire into `pipelines/turn_graph.py` as a node, or call directly from another agent/resolver

### Adding a tool
1. `tools/<module>.py` — `@tool` decorator from `langchain_core.tools`, `Annotated[type, "description"]` per param
2. `tools/__init__.py` — import and add to `ALL_TOOLS`. If combat-relevant, also add to `COMBAT_TOOLS`.
3. Invoke via `await tool.ainvoke({"arg": val})` — never `.coroutine()`

### Hard rules
- All LLM calls through `llm/client.py` only
- All DB access through `db/queries/` only
- `domain/` has zero FastAPI / SQLAlchemy imports
- Migrations are always Alembic-generated (`make revision`) — no hand-written SQL
- `tools/` is the tool home — there is no `mcp/` directory

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.
