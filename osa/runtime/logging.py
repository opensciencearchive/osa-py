"""Logging setup for OSA containers (ingesters and hooks)."""

from __future__ import annotations

import logging
import os

_LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_configured = False


def setup_logging() -> None:
    """Configure logging for an OSA container.

    Sets up a stderr handler on the ``osa`` logger hierarchy so all
    ``osa.*`` and convention package loggers emit to container stdout/stderr.

    Reads ``OSA_LOG_LEVEL`` from the environment (default: ``INFO``).
    Called once by entrypoints; safe to call multiple times.
    """
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.environ.get("OSA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    # Configure root logger so all loggers (osa.*, convention packages) emit
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
