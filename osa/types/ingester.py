"""Ingester types for SDK — IngesterFileRef and IngesterRecord."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Limits(BaseModel, frozen=True):
    """Resource limits for a container (hook or ingester)."""

    timeout_seconds: int = 300
    memory: str = "512m"
    cpu: str = "0.5"


class IngesterSchedule(BaseModel, frozen=True):
    """Cron schedule for periodic ingester runs."""

    cron: str
    limit: int | None = None


class InitialRun(BaseModel, frozen=True):
    """Configuration for the first ingester run on server startup."""

    limit: int | None = None


class IngesterFileRef(BaseModel, frozen=True):
    """A reference to a file written by an ingester container.

    The ingester writes files to $OSA_FILES/{source_id}/{name}.
    The server renames this directory into the deposition's canonical location.
    """

    name: str  # e.g. "structure.cif"
    relative_path: str  # e.g. "{source_id}/structure.cif" (relative to $OSA_FILES)
    size_mb: float  # file size in megabytes


class IngesterRecord(BaseModel, frozen=True):
    """A record produced by an ingester container, written to records.jsonl."""

    source_id: str
    metadata: dict[str, Any]
    files: list[IngesterFileRef] = []
    fetched_at: datetime | None = None
