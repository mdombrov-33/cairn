import importlib
import pkgutil

import pytest
from langchain_core.tools import BaseTool

import cairn.tools as tools_pkg
from cairn.tools import registry


def test_all_tools_registered() -> None:
    registered_tools = {id(tool) for tool in registry.all()}
    unregistered = []

    for _, module_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"cairn.tools.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, BaseTool) and id(attr) not in registered_tools:
                unregistered.append(f"cairn.tools.{module_name}.{attr_name} ({attr.name!r})")

    assert not unregistered, "Tools defined but not registered:\n" + "\n".join(unregistered)


def test_registry_contains_exact_consolidated_surface() -> None:
    all_tools = registry.all()
    all_names = {tool.name for tool in all_tools}

    assert len(all_tools) == 55
    assert {
        "adjust_exhaustion",
        "adjust_resource",
        "adjust_spell_slot",
        "set_condition",
        "use_economy",
    }.issubset(all_names)
    assert {
        "add_exhaustion",
        "apply_condition",
        "consume_spell_slot",
        "remove_condition",
        "restore_spell_slot",
        "use_action",
    }.isdisjoint(all_names)


def test_register_projects_one_definition_without_list_edits(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})

    @registry.register
    async def example_tool(name: str) -> dict[str, str]:
        """Return the supplied name."""
        return {"name": name}

    assert registry.all() == [example_tool]


def test_register_rejects_duplicate_names(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})

    async def first_definition() -> dict[str, bool]:
        """First definition."""
        return {"first": True}

    async def second_definition() -> dict[str, bool]:
        """Second definition."""
        return {"first": False}

    first_definition.__name__ = "duplicated"
    second_definition.__name__ = "duplicated"
    registry.register(first_definition)

    with pytest.raises(ValueError, match="duplicate tool name: duplicated"):
        registry.register(second_definition)
