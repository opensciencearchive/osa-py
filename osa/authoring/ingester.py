"""Ingester protocol for SDK convention packages — OCI container model."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

from osa.runtime.ingester_context import IngesterContext
from osa.types.ingester import IngesterRecord, IngesterSchedule, InitialRun


class Ingester(Protocol):
    """Protocol for pluggable data ingesters running as OCI containers.

    Implement this in your convention package to define an ingester.
    Ingesters are built into Docker images and executed by the server.
    """

    name: ClassVar[str]
    schedule: ClassVar[IngesterSchedule | None]
    initial_run: ClassVar[InitialRun | None]
    max_file_mb: ClassVar[float | None]

    class RuntimeConfig(BaseModel): ...

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        since: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]: ...
