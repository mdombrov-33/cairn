from starlette.routing import Mount

from cairn.config import Settings
from cairn.main import create_app

DATABASE_URL = "postgresql+asyncpg://cairn:cairn@localhost:5433/cairn"


def test_mcp_defaults_on_only_in_development() -> None:
    assert Settings(database_url=DATABASE_URL, env="dev", mcp_enabled=None).is_mcp_enabled() is True
    assert Settings(database_url=DATABASE_URL, env="test", mcp_enabled=None).is_mcp_enabled() is False
    assert Settings(database_url=DATABASE_URL, env="prod", mcp_enabled=None).is_mcp_enabled() is False


def test_explicit_mcp_setting_overrides_environment() -> None:
    assert Settings(database_url=DATABASE_URL, env="dev", mcp_enabled=False).is_mcp_enabled() is False
    assert Settings(database_url=DATABASE_URL, env="prod", mcp_enabled=True).is_mcp_enabled() is True


def test_mcp_mount_follows_effective_setting() -> None:
    enabled = create_app(Settings(database_url=DATABASE_URL, env="test", mcp_enabled=True))
    disabled = create_app(Settings(database_url=DATABASE_URL, env="test", mcp_enabled=False))

    assert any(isinstance(route, Mount) and route.path == "/mcp" for route in enabled.routes)
    assert all(not isinstance(route, Mount) or route.path != "/mcp" for route in disabled.routes)
