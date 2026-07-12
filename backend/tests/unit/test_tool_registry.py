import importlib
import pkgutil

import pytest
from langchain_core.tools import BaseTool

import cairn.tools as tools_pkg
from cairn.tools import ALL_TOOLS, COMBAT_TOOLS, registry


def test_all_tools_registered() -> None:
    registered_tools = {id(tool) for tool in ALL_TOOLS}
    unregistered = []

    for _, module_name, _ in pkgutil.iter_modules(tools_pkg.__path__):
        module = importlib.import_module(f"cairn.tools.{module_name}")
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, BaseTool) and id(attr) not in registered_tools:
                unregistered.append(f"cairn.tools.{module_name}.{attr_name} ({attr.name!r})")

    assert not unregistered, "Tools defined but not in ALL_TOOLS:\n" + "\n".join(unregistered)


def test_registry_derives_exact_consolidated_surfaces() -> None:
    all_names = {tool.name for tool in ALL_TOOLS}
    combat_names = {tool.name for tool in COMBAT_TOOLS}

    assert len(ALL_TOOLS) == 55
    assert len(COMBAT_TOOLS) == 39
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
    assert combat_names == {tool.name for tool in registry.select(include={"combat"})}


def test_register_projects_one_definition_without_list_edits(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_REGISTRY", {})

    @registry.register(tags={"readonly", "srd"})
    async def example_tool(name: str) -> dict[str, str]:
        """Return the supplied name."""
        return {"name": name}

    assert registry.all() == [example_tool]
    assert registry.select(include={"srd"}) == [example_tool]
    assert registry.select(include={"srd"}, exclude={"readonly"}) == []
    assert [registered.tool for registered in registry.mcp_tools()] == [example_tool]


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
    registry.register(tags={"readonly"})(first_definition)

    with pytest.raises(ValueError, match="duplicate tool name: duplicated"):
        registry.register(tags={"readonly"})(second_definition)
