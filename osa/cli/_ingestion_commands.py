"""Typer sub-app for `osa ingestion *` commands."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from osa.cli.ingestion import (
    IngestionError,
    discover_ingestable_conventions,
    start_ingestion,
)
from osa.cli.ui import UI

ingestion_app = typer.Typer(help="Manage ingestion runs.")


def _ui(ctx: typer.Context) -> UI:
    ui = getattr(ctx.obj, "ui", None)
    return ui if isinstance(ui, UI) else UI.create()


@ingestion_app.command()
def start(
    ctx: typer.Context,
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

    ui = _ui(ctx)
    server_url = resolve_server(flag=server)

    resolved_token = token
    if not resolved_token:
        resolved_token = resolve_token(server_url)
        if resolved_token is None:
            ui.error("Not authenticated", hint="Run `osa login` first")
            raise typer.Exit(1)

    resolved_name = convention
    if not resolved_name:
        try:
            candidates = discover_ingestable_conventions()
        except IngestionError as e:
            ui.error(str(e))
            raise typer.Exit(1) from None

        if len(candidates) == 0:
            ui.error("No conventions with an ingester found")
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
            ui.info("Multiple ingestable conventions found:")
            for i, c in enumerate(candidates, 1):
                ui.info(f"  {i}. {c.title}@{c.version} (ingester: {c.ingester_name})")
            choice = typer.prompt("Select a convention", type=int)
            if choice < 1 or choice > len(candidates):
                ui.error("Invalid selection")
                raise typer.Exit(1)
            resolved_name = candidates[choice - 1].title

    with ui.task(f"Starting ingestion for {resolved_name}") as task:
        try:
            result = start_ingestion(
                server=server_url,
                convention=resolved_name,
                token=resolved_token,
                batch_size=batch_size,
                limit=limit,
            )
        except IngestionError as e:
            task.fail(str(e))
            raise typer.Exit(1) from None
        task.done(detail=str(result.get("srn", "")))
