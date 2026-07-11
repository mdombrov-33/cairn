"""Dependency rules for architecture slices that have been migrated."""

import ast
from pathlib import Path


def test_typed_settings_module_has_no_persistence_or_framework_dependencies() -> None:
    path = Path(__file__).parents[2] / "src/cairn/domain/services/settings.py"
    tree = ast.parse(path.read_text())
    forbidden = ("sqlalchemy", "fastapi", "cairn.db", "cairn.agents")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(name == prefix or name.startswith(f"{prefix}.") for name in names for prefix in forbidden)


def test_turn_graph_has_no_persistence_or_resolver_agent_dependencies() -> None:
    path = Path(__file__).parents[2] / "src/cairn/pipelines/turn_graph.py"
    tree = ast.parse(path.read_text())
    forbidden = ("cairn.db", "cairn.agents.dialogue", "cairn.agents.recruiter", "cairn.agents.rules_lawyer")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(name == prefix or name.startswith(f"{prefix}.") for name in names for prefix in forbidden)


def test_turn_routes_cross_the_foreground_runtime_seam() -> None:
    path = Path(__file__).parents[2] / "src/cairn/api/v1/routes/turns.py"
    tree = ast.parse(path.read_text())
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]

    assert "cairn.application.turns.runtime" in imports


def test_campaign_scene_and_npc_domain_modules_have_no_runtime_dependencies() -> None:
    root = Path(__file__).parents[2] / "src/cairn/domain/services"
    forbidden = ("sqlalchemy", "fastapi", "cairn.db", "cairn.agents", "cairn.pipelines")

    for filename in ("campaign_view.py", "npcs.py", "scenes.py"):
        tree = ast.parse((root / filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == prefix or name.startswith(f"{prefix}.") for name in names for prefix in forbidden)


def test_character_domain_rules_have_no_runtime_dependencies() -> None:
    root = Path(__file__).parents[2] / "src/cairn/domain/services"
    forbidden = ("sqlalchemy", "fastapi", "cairn.db", "cairn.agents", "cairn.pipelines")

    for filename in ("ac.py", "feat_effects.py", "inventory.py"):
        tree = ast.parse((root / filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == prefix or name.startswith(f"{prefix}.") for name in names for prefix in forbidden)


def test_narrative_domain_rules_have_no_runtime_dependencies() -> None:
    root = Path(__file__).parents[2] / "src/cairn/domain/services"
    forbidden = ("sqlalchemy", "fastapi", "cairn.db", "cairn.agents", "cairn.pipelines")

    for filename in ("companions.py", "narrative_profile.py", "rng.py", "settings.py"):
        tree = ast.parse((root / filename).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == prefix or name.startswith(f"{prefix}.") for name in names for prefix in forbidden)
