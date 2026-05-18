from functools import lru_cache
from pathlib import Path

import yaml

from cairn.config import get_settings
from cairn.prompts.registry import Prompt, load_prompt, resolve_version

_MODELS_PATH = Path(__file__).parent / "models.yaml"


@lru_cache
def _load_models() -> dict:
    return yaml.safe_load(_MODELS_PATH.read_text())


def get_model(agent: str, llm_env: str) -> tuple[str, list[str]]:
    """Return (primary_model, fallbacks) for a given agent and environment."""
    data = _load_models()
    agents = data.get("agents", {})

    tier = agents[agent][llm_env] if agent in agents and llm_env in agents[agent] else data["defaults"][llm_env]

    primary: str = tier["primary"]
    fallbacks: list[str] = [tier["fallback"]] if "fallback" in tier else []
    return primary, fallbacks


def agent_setup(name: str) -> tuple[Prompt, str, list[str]]:
    """Return (prompt, model, fallbacks) for an agent. Consolidates the standard 4-line setup."""
    settings = get_settings()
    version = resolve_version(name, settings.llm_prompt_versions)
    prompt = load_prompt(name, version)
    model, fallbacks = get_model(name, settings.llm_env)
    return prompt, model, fallbacks
