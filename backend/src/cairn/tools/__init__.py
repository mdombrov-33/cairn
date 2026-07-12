# Explicit side-effect imports keep registration deterministic.
from cairn.tools import combat as _combat  # noqa: F401
from cairn.tools import dice as _dice  # noqa: F401
from cairn.tools import game_state as _game_state
from cairn.tools import inspiration as _inspiration  # noqa: F401
from cairn.tools import registry as registry
from cairn.tools import resources as _resources  # noqa: F401
from cairn.tools import srd as _srd  # noqa: F401

fetch_combat_context = _game_state.fetch_combat_context
loot_item = _game_state.loot_item

__all__ = ["fetch_combat_context", "loot_item", "registry"]
