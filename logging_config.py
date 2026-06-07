"""Centralized logging configuration for application entry points."""

from __future__ import annotations

import logging
import os

_DEFAULT_LEVEL = "INFO"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def _resolve_level(level: str | None) -> int:
    name = (level or os.getenv("LOG_LEVEL", _DEFAULT_LEVEL)).strip().upper()
    resolved = getattr(logging, name, None)
    if isinstance(resolved, int):
        return resolved
    return logging.INFO


def configure_logging(level: str | None = None) -> None:
    """Configure root logging once from an entry point (CLI or FastAPI startup)."""
    logging.basicConfig(
        level=_resolve_level(level),
        format=_LOG_FORMAT,
        datefmt=_DATE_FORMAT,
        force=True,
    )
