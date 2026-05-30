"""Typer sub-app for `osa ingestion *` commands."""

from __future__ import annotations

import json
import sys
from typing import Annotated, Optional

import typer

from osa.cli.ingestion import (
    IngestionError,
    discover_ingestable_conventions,
    start_ingestion,
)

ingestion_app = typer.Typer(help="Manage ingestion runs.")


@ingestion_app.command()
def start(
    convention: Annotated[
        Optional[str],
        typer.Option(
            "--convention", help="Convention title. Auto-detected if omitted."
        ),
    ] = None,
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
    token: Annotated[Optional[str], typer.Option(help="Auth token.")] = None,
    batch_size: Annotated[int, typer.Option(help="Records per batch.")] = 1000,
    limit: Annotated[Optional[int], typer.Option(help="Max total records.")] = None,
) -> None:
    """Start an ingestion run for a convention."""
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

    resolved_name = convention
    if not resolved_name:
        try:
            candidates = discover_ingestable_conventions()
        except IngestionError as e:
            print(f"Error: {e}", file=sys.stderr)
            raise typer.Exit(1) from None

        if len(candidates) == 0:
            print(
                "Error: No conventions with an ingester found.",
                file=sys.stderr,
            )
            raise typer.Exit(1)
        elif len(candidates) == 1:
            pick = candidates[0]
            typer.confirm(
                f"Start ingestion for {pick.title}@{pick.version} "
                f"(ingester: {pick.ingester_name})?",
                abort=True,
            )
            resolved_name = pick.title
        else:
            print("Multiple ingestable conventions found:\n")
            for i, c in enumerate(candidates, 1):
                print(f"  {i}. {c.title}@{c.version} (ingester: {c.ingester_name})")
            print()
            choice = typer.prompt("Select a convention", type=int)
            if choice < 1 or choice > len(candidates):
                print("Error: Invalid selection.", file=sys.stderr)
                raise typer.Exit(1)
            resolved_name = candidates[choice - 1].title

    try:
        result = start_ingestion(
            server=server_url,
            convention=resolved_name,
            token=resolved_token,
            batch_size=batch_size,
            limit=limit,
        )
        print(json.dumps(result, indent=2))
    except IngestionError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None
