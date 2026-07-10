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
