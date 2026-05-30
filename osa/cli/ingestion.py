"""OSA ingestion commands — start and manage ingestion runs."""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml


class IngestionError(Exception):
    """Raised when an ingestion operation fails."""


@dataclass
class IngestableConvention:
    """A convention that has an ingester attached."""

    title: str
    version: str
    ingester_name: str


def discover_ingestable_conventions() -> list[IngestableConvention]:
    """Discover registered conventions that have an ingester.

    Loads convention entry points, filters to those with an ingester.
    Reusable by downstream CLIs.
    """
    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    from osa._registry import _conventions

    return [
        IngestableConvention(
            title=conv.title,
            version=conv.version,
            ingester_name=conv.ingester_info.name,
        )
        for conv in _conventions
        if conv.ingester_info is not None
    ]


def _read_domain(project_dir: Path) -> str:
    """Read the domain from osa.yaml."""
    config_path = project_dir / "osa.yaml"
    if not config_path.exists():
        raise IngestionError("osa.yaml not found. Cannot build convention SRN.")
    data = yaml.safe_load(config_path.read_text())
    domain = data.get("domain")
    if not domain:
        raise IngestionError(
            "No 'domain' field in osa.yaml. Cannot build convention SRN."
        )
    return domain


def build_convention_srn(
    *,
    title: str,
    project_dir: Path | None = None,
    version: str = "1.0.0",
) -> str:
    """Build a convention SRN from osa.yaml domain, title, and version.

    Format: urn:osa:{domain}:conv:{title}@{version}
    """
    project_dir = project_dir or Path.cwd()
    domain = _read_domain(project_dir)
    return f"urn:osa:{domain}:conv:{title}@{version}"


def start_ingestion(
    *,
    server: str,
    convention: str,
    token: str,
    batch_size: int = 1000,
    limit: int | None = None,
    project_dir: Path | None = None,
    http: Any = None,
) -> dict[str, Any]:
    """Start an ingestion run for a convention.

    Accepts a convention title, builds the SRN internally,
    and POSTs to /api/v1/ingestions on the archive server.
    """
    if http is None:
        http = httpx

    srn = build_convention_srn(title=convention, project_dir=project_dir)
    url = f"{server.rstrip('/')}/api/v1/ingestions"
    payload: dict[str, Any] = {
        "convention_srn": srn,
        "batch_size": batch_size,
    }
    if limit is not None:
        payload["limit"] = limit
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = http.post(url, json=payload, headers=headers, timeout=30.0)

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise IngestionError(
            f"Ingestion failed ({resp.status_code}): {detail}"
        ) from exc

    return resp.json()
