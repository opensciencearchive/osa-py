"""OSA ingestion commands — start and manage ingestion runs."""

from __future__ import annotations

from typing import Any

import httpx


class IngestionError(Exception):
    """Raised when an ingestion operation fails."""


def start_ingestion(
    *,
    server: str,
    convention_id: str,
    token: str,
    batch_size: int = 1000,
    limit: int | None = None,
    http: Any = None,
) -> dict[str, Any]:
    """Start an ingestion run for a convention, identified by its slug.

    POSTs ``{convention_id, batch_size, limit}`` to /api/v1/ingestions on the
    archive server. ``convention_id`` is the convention slug minted server-side
    at deploy time (shown by ``osa deploy``); ``limit=None`` means unlimited.
    """
    if http is None:
        http = httpx

    url = f"{server.rstrip('/')}/api/v1/ingestions"
    payload: dict[str, Any] = {
        "convention_id": convention_id,
        "batch_size": batch_size,
        "limit": limit,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    return _post(http, url, headers=headers, payload=payload, action="Ingestion")


def cancel_ingestion(
    *,
    server: str,
    ingest_run_id: str,
    token: str,
    http: Any = None,
) -> dict[str, Any]:
    """Cancel a running ingestion, stopping any further batch scheduling.

    POSTs to /api/v1/ingestions/{id}/cancel. The run is not deleted — its
    counters and reason stay queryable. A run that has already finished,
    failed or been cancelled gives a 409, surfaced as an ``IngestionError``
    rather than a silent no-op.

    A batch already running in its containers finishes; cancelling stops the
    scheduling of further ones.
    """
    if http is None:
        http = httpx

    url = f"{server.rstrip('/')}/api/v1/ingestions/{ingest_run_id}/cancel"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    return _post(http, url, headers=headers, payload=None, action="Cancel")


def _post(
    http: Any,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    action: str,
) -> dict[str, Any]:
    """POST and raise ``IngestionError`` carrying the server's own detail."""
    resp = http.post(url, json=payload, headers=headers, timeout=30.0)

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise IngestionError(f"{action} failed ({resp.status_code}): {detail}") from exc

    return resp.json()
