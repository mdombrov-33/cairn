---
name: add-tool
description: Add a new LangChain tool to this project. Use when asked to add a tool, create a tool for X, or expose a new capability to agents.
argument-hint: "[tool-name]"
---

Add a new tool named `$ARGUMENTS` following the exact conventions of this project.

## Current tool registrations (ALL_TOOLS and COMBAT_TOOLS)

!`cat /Users/maximus/Projects/cairn/backend/src/cairn/tools/__init__.py`

## Existing tool modules (for pattern reference)

!`ls /Users/maximus/Projects/cairn/backend/src/cairn/tools/*.py | grep -v __`

## Steps

### 1. Pick the right module

- `dice.py` — dice rolling
- `combat.py` — combat mutations (apply damage, conditions, etc.)
- `resources.py` — spell slots, action economy, concentration
- `game_state.py` — read-only state queries
- `srd.py` — SRD lookups (spells, monsters, conditions, weapons, etc.)

Read the target module first to match its style before adding anything.

### 2. Add the function

```python
@tool
async def $ARGUMENTS(
    param: Annotated[type, "clear description of what this param does"],
) -> dict:
    """One-line docstring — this is what the LLM sees when choosing tools."""
    ...
```

Rules:
- `@tool` from `langchain_core.tools`, `Annotated` from `typing`
- Every parameter needs an `Annotated` description — the LLM reads these
- Return a plain `dict`
- Raise domain exceptions (`NotFoundError`, `AgentError`, etc.) — don't swallow errors

### 3. Register in `backend/src/cairn/tools/__init__.py`

- Import the function at the top with the other imports from the same module
- Add to `ALL_TOOLS`
- If the tool is used during active combat (mutations, lookups agents need mid-fight): also add to `COMBAT_TOOLS`

### 4. Verify

Run `make test` from the repo root — all existing tests must still pass.
