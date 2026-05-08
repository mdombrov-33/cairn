---
name: add-agent
description: Scaffold a new agent for this project. Use when asked to add an agent, create an agent for X, or build a new agent.
argument-hint: "[agent-name]"
---

Create a new agent named `$ARGUMENTS` following the exact conventions of this project.

## Existing agents (for pattern reference)

!`ls /Users/maximus/Projects/cairn/backend/src/cairn/agents/*.py | grep -v __`

## Current models.yaml (for tier reference)

!`cat /Users/maximus/Projects/cairn/backend/src/cairn/llm/models.yaml`

## Steps

### 1. `backend/src/cairn/agents/$ARGUMENTS.py`

Read an existing agent (e.g. `lore_keeper.py` or `npc_dialogue.py`) first to match the style. Then:
- Import `agent_setup` from `cairn.llm.router`
- Call `agent_setup("$ARGUMENTS")` to get `(prompt, model, fallbacks)`
- Call `complete()` or `complete_with_tools()` from `cairn.llm.client`
- Return a typed result (Pydantic model or plain type)
- No bare `except Exception` unless followed by a specific re-raise

### 2. `backend/src/cairn/prompts/$ARGUMENTS/v1.md`

Frontmatter must include `temperature` and `version: v1`. Body is Jinja2. Variables are whatever the agent passes to `prompt.render(...)`. Read an existing prompt file first to match the format.

### 3. `backend/src/cairn/llm/models.yaml`

Add an entry under `agents:` with `$ARGUMENTS` as key. Pick the right tier:
- Classification / extraction → fast (haiku-class)
- Character voice / mid-complexity → mid-tier
- Narrative / tool loop → frontier

### 4. Wire it up

- If it's a LangGraph node: add to `backend/src/cairn/pipelines/turn_graph.py`
- If called directly by another agent (like `combat_resolver` calls `combat_ai`): just import and call — no graph wiring needed

### 5. Verify

Run `make test` from the repo root — all existing tests must still pass.
