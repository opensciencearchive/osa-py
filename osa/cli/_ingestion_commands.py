"""Typer sub-app for `osa ingestion *` commands."""

from __future__ import annotations

from typing import Annotated, Optional

import typer

from osa.cli.ingestion import IngestionError, start_ingestion
from osa.cli.ui import UI

ingestion_app = typer.Typer(help="Manage ingestion runs.")


def _ui(ctx: typer.Context) -> UI:
    ui = getattr(ctx.obj, "ui", None)
    return ui if isinstance(ui, UI) else UI.create()


@ingestion_app.command()
def start(
    ctx: typer.Context,
    convention: Annotated[
        str,
        typer.Option(
            "--convention",
            help="Convention slug (shown by `osa deploy`).",
        ),
    ],
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
    token: Annotated[Optional[str], typer.Option(help="Auth token.")] = None,
    batch_size: Annotated[int, typer.Option(help="Records per batch.")] = 1000,
    limit: Annotated[Optional[int], typer.Option(help="Max total records.")] = None,
) -> None:
    """Start an ingestion run for a convention, identified by its slug."""
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

    with ui.task(f"Starting ingestion for {convention}") as task:
        try:
            result = start_ingestion(
                server=server_url,
                convention_id=convention,
                token=resolved_token,
                batch_size=batch_size,
                limit=limit,
            )
        except IngestionError as e:
            task.fail(str(e))
            raise typer.Exit(1) from None
        task.done(detail=str(result.get("srn", "")))
