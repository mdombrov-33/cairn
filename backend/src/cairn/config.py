from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    app_name: str = "cairn"
    log_level: str = "INFO"

    database_url: str

    llm_env: Literal["local", "frontier"] = "local"
    # Phase-A/testing override. Slice 14.5 replaces this process-wide value with
    # the authenticated user's current account tier at turn start.
    llm_tier: Literal["free", "plus", "pro"] = "free"
    llm_prompt_versions: str = "{}"  # JSON map e.g. '{"intent_router": "v2"}'


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
