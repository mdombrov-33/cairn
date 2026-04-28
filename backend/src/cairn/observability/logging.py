import logging
import os
import sys
from typing import Any

import structlog

from cairn.config import Settings

SENSITIVE_KEYS = {"password", "authorization", "api_key", "token", "secret", "cookie"}


def _redact_sensitive(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for k in list(event_dict.keys()):
        if k.lower() in SENSITIVE_KEYS:
            event_dict[k] = "[REDACTED]"
    return event_dict


def configure_logging(settings: Settings) -> None:
    in_pytest = "PYTEST_CURRENT_TEST" in os.environ
    level_name = "WARNING" if in_pytest else settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_sensitive,
    ]
    if settings.env == "dev":
        processors.append(structlog.dev.ConsoleRenderer(colors=True))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
