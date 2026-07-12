from langchain_core.tools import BaseTool

# Explicit side-effect imports keep registration deterministic.
from cairn.tools import combat, dice, game_state, inspiration, registry, resources, srd

_DISCOVERED_MODULES = (combat, dice, game_state, inspiration, resources, srd)
fetch_combat_context = game_state.fetch_combat_context
loot_item = game_state.loot_item

ALL_TOOLS: list[BaseTool] = registry.all()
COMBAT_TOOLS: list[BaseTool] = registry.select(include={"combat"})

__all__ = ["ALL_TOOLS", "COMBAT_TOOLS", "fetch_combat_context", "loot_item"]
