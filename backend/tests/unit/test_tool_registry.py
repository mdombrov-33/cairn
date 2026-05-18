import importlib
import pkgutil

from langchain_core.tools import BaseTool

import cairn.tools as tools_pkg
from cairn.tools import ALL_TOOLS


def test_all_tools_registered() -> None:
    registered_names = {t.name for t in ALL_TOOLS}
    unregistered = []

    for _, module_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"cairn.tools.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, BaseTool) and attr.name not in registered_names:
                unregistered.append(f"cairn.tools.{module_name}.{attr_name} ({attr.name!r})")

    assert not unregistered, "Tools defined but not in ALL_TOOLS:\n" + "\n".join(unregistered)
