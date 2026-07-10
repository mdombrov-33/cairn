from functools import lru_cache
from pathlib import Path

import yaml

from cairn.config import get_settings
from cairn.prompts.registry import Prompt, load_prompt, resolve_version

_MODELS_PATH = Path(__file__).parent / "models.yaml"


@lru_cache
def _load_models() -> dict:
    return yaml.safe_load(_MODELS_PATH.read_text())


def get_model(agent: str, llm_env: str, account_tier: str = "free") -> tuple[str, list[str]]:
    """Return the configured model policy for an agent and runtime/account tier."""
    data = _load_models()
    if llm_env == "local":
        profile = data["profiles"]["development"]
        spec = profile.get("agents", {}).get(agent, profile["default"])
        return spec["primary"], [spec["fallback"]] if "fallback" in spec else []

    tier = data["tiers"].get(account_tier, data["tiers"]["free"])
    spec = tier.get("agents", {}).get(agent, tier["default"])
    return spec["primary"], [spec["fallback"]] if "fallback" in spec else []


def agent_setup(name: str, account_tier: str | None = None) -> tuple[Prompt, str, list[str]]:
    """Return (prompt, model, fallbacks) for an agent. Consolidates the standard 4-line setup."""
    settings = get_settings()
    version = resolve_version(name, settings.llm_prompt_versions)
    prompt = load_prompt(name, version)
    model, fallbacks = get_model(name, settings.llm_env, account_tier or settings.llm_tier)
    return prompt, model, fallbacks
