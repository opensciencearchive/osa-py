"""Ingester protocol for SDK convention packages — OCI container model."""

from __future__ import annotations

from collections.abc import AsyncIterator
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

    def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        """Yield up to ``limit`` records, continuing from ``session``.

        **Continuation comes from ``session``, and only from ``session``.** The
        server hands back whatever the previous batch passed to
        ``ctx.set_session(...)``, starting with ``None`` on the first batch. So
        read your start position out of it:

        ```python
        start = int((session or {}).get("offset", 0))
        window = items[start : start + limit] if limit is not None else items[start:]
        for item in window:
            yield ...
        next_start = start + len(window)
        if next_start < len(items):
            ctx.set_session({"offset": next_start})
        ```

        Two rules follow. **Advance the state you set** — handing back the state
        you were given means the next pull is identical, and the server aborts
        the run rather than loop (#227). And **set no session on the final
        batch**: that is what ends the run.

        An `offset` cursor and a `since` watermark used to sit in this
        signature. Neither was ever populated, so an ingester that paginated on
        either looped forever or truncated silently after one batch. They are
        gone; ``session`` carries a position just as well.
        """
        ...
