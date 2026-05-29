"""Typer sub-app for `osa ingestion *` commands."""

from __future__ import annotations

import json
import sys
from typing import Annotated, Optional

import typer

from osa.cli.ingestion import IngestionError, build_convention_srn, start_ingestion

ingestion_app = typer.Typer(help="Manage ingestion runs.")


@ingestion_app.command()
def start(
    convention_srn: Annotated[
        Optional[str],
        typer.Argument(help="Convention SRN. Auto-detected from project if omitted."),
    ] = None,
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
    token: Annotated[Optional[str], typer.Option(help="Auth token.")] = None,
    batch_size: Annotated[int, typer.Option(help="Records per batch.")] = 1000,
    limit: Annotated[Optional[int], typer.Option(help="Max total records.")] = None,
) -> None:
    """Start an ingestion run for a convention."""
    import importlib
    import importlib.metadata

    from osa.cli.credentials import resolve_token
    from osa.cli.link import resolve_server

    server_url = resolve_server(flag=server)

    resolved_token = token
    if not resolved_token:
        resolved_token = resolve_token(server_url)
        if resolved_token is None:
            print(
                "Error: Not authenticated. Run `osa login` first.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

    resolved_srn = convention_srn
    if not resolved_srn:
        # Auto-detect from convention registry + osa.yaml
        for ep in importlib.metadata.entry_points(group="osa.conventions"):
            importlib.import_module(ep.value)

        from osa._registry import _conventions

        if not _conventions:
            print(
                "Error: No conventions registered. Provide a convention SRN explicitly.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

        conv = _conventions[0]
        try:
            resolved_srn = build_convention_srn(title=conv.title)
        except IngestionError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1) from None

    try:
        result = start_ingestion(
            server=server_url,
            convention_srn=resolved_srn,
            token=resolved_token,
            batch_size=batch_size,
            limit=limit,
        )
        print(json.dumps(result, indent=2))
    except IngestionError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None
