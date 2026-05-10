---
name: add-tool
description: Add a new LangChain tool to this project. Use when asked to add a tool, create a tool for X, or expose a new capability to agents.
argument-hint: "[tool-name]"
---

Add a new tool named `$ARGUMENTS` following the exact conventions of this project.

## Current tool registrations (ALL_TOOLS and COMBAT_TOOLS)

!`cat backend/src/cairn/tools/__init__.py`

## Existing tool modules (for pattern reference)

!`ls backend/src/cairn/tools/*.py | grep -v __`

## Steps

### 1. Pick the right module

- `dice.py` — dice rolling
- `combat.py` — combat mutations (apply damage, conditions, etc.)
- `resources.py` — spell slots, action economy, concentration
- `game_state.py` — read-only state queries
- `srd.py` — SRD lookups (spells, monsters, conditions, weapons, etc.)

If no existing module fits, create a new one with a clear name.

Read the target module first to match its style before adding anything.

### 2. Implement the service function first (if DB or domain logic is involved)

**Every tool that touches the database or has domain logic must delegate to `domain/services/`.** The tool file is a thin wire only — `@tool` signature + `async with db_client.get_session() as db: return await some_service.fn(db, ...)`.

The one exception is `dice.py` — pure computation with no DB stays in the tool file.

If you need a new service function:

- HTTP-facing (requires auth): add to the relevant service, take `owner_id`, call `get_campaign_owned_by` or similar
- Tool-facing (no auth): prefix with `_` to signal it's internal (e.g. `init_state`, `end_state`, `_award_xp`)
- Domain helpers (`mod`, `roll_d20`, `find_combatant`, etc.) belong in the service file — never in the tool file

A tool can import from **any** service, not just the one matching its module. For example, `award_xp` lives in `combat.py` (the tool file) but calls `leveling_service._award_xp`. Put the tool in whichever module it will most often be called from, then import the right service.

**Shared helpers:** if multiple service functions need the same lookup logic (e.g. computing a save modifier or skill modifier for different combatant types), extract it as a private `_helper` in the service file and reuse it. See `_save_modifier` and `_skill_modifier` in `combat.py` as examples.

### 3. Add the tool function

```python
@tool
async def $ARGUMENTS(
    param: Annotated[type, "clear description of what this param does"],
) -> dict:
    """One-line docstring — this is what the LLM sees when choosing tools."""
    async with db_client.get_session() as db:
        return await some_service.$ARGUMENTS(db, param=param)
```

Rules:

- `@tool` from `langchain_core.tools`, `Annotated` from `typing`
- Every parameter needs an `Annotated` description — the LLM reads these
- Return a plain `dict`
- No business logic in the tool body — only UUID parsing and the service call
- Don't add module-level helpers or imports that aren't needed for thin-wiring

### 4. Register in `backend/src/cairn/tools/__init__.py`

- Import the function at the top with the other imports from the same module
- Add to `ALL_TOOLS`
- If the tool is used during active combat (mutations, lookups agents need mid-fight): also add to `COMBAT_TOOLS`

### 5. Verify

Run `make test` from the repo root — all existing tests must still pass.
