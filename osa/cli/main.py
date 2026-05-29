"""OSA CLI — Typer app for the `osa` command."""

from __future__ import annotations

import json
import sys
from typing import Annotated, Optional

import typer

from osa.cli._ingestion_commands import ingestion_app
from osa.cli._runtime_commands import (
    emit_command,
    meta_command,
    progress_command,
    reject_command,
)

app = typer.Typer(help="OSA — Open Scientific Archive CLI")
app.add_typer(ingestion_app, name="ingestion")


@app.command()
def meta() -> None:
    """Generate and print the convention manifest."""
    print(meta_command())


@app.command()
def emit(data: Annotated[str, typer.Argument(help="JSON data to emit.")]) -> None:
    """Write feature data to $OSA_OUT/features.json."""
    emit_command(data)


@app.command()
def progress(
    step: Annotated[Optional[str], typer.Option(help="Step name.")] = None,
    status: Annotated[str, typer.Option(help="Status level.")] = "info",
    message: Annotated[Optional[str], typer.Option(help="Progress message.")] = None,
) -> None:
    """Append a progress entry to $OSA_OUT/progress.jsonl."""
    progress_command(step=step, status=status, message=message)


@app.command()
def reject(
    reason: Annotated[str, typer.Argument(help="Rejection reason.")],
) -> None:
    """Write a rejection entry to $OSA_OUT/progress.jsonl."""
    reject_command(reason=reason)


@app.command()
def link(
    server: Annotated[str, typer.Option(help="Server URL to link.")],
) -> None:
    """Link this project to an OSA server."""
    from osa.cli.link import write_link

    config_path = write_link(server)
    print(f"Linked to {server.rstrip('/')}")
    print(f"Config written to {config_path}")


@app.command()
def login(
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
) -> None:
    """Authenticate with an OSA server via device flow."""
    import logging

    from osa.cli.link import resolve_server
    from osa.cli.login import login as do_login

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    server_url = resolve_server(flag=server)
    success = do_login(server_url)
    if not success:
        raise typer.Exit(1)


@app.command()
def logout(
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
) -> None:
    """Remove stored credentials for a server."""
    from osa.cli.link import resolve_server
    from osa.cli.logout import logout as do_logout

    server_url = resolve_server(flag=server)
    do_logout(server_url)


@app.command()
def deploy(
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
    token: Annotated[Optional[str], typer.Option(help="Auth token.")] = None,
    registry: Annotated[
        Optional[str],
        typer.Option(
            help="Container registry to push images to (e.g. ghcr.io/your-org).",
            envvar="OSA_REGISTRY",
        ),
    ] = None,
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build", help="Skip image build/push, reuse last-pushed images."
        ),
    ] = False,
) -> None:
    """Build hook/ingester images and register conventions with the server."""
    import importlib
    import importlib.metadata

    from osa.cli.deploy import deploy as do_deploy
    from osa.cli.link import resolve_server

    print("Deploying...")

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    server_url = resolve_server(flag=server)
    resolved_token = token

    if not resolved_token:
        from osa.cli.credentials import resolve_token

        resolved_token = resolve_token(server_url)
        if resolved_token is None:
            print(
                "Error: Not authenticated. Run `osa login` first.",
                file=sys.stderr,
            )
            raise typer.Exit(1)

    result = do_deploy(
        server=server_url,
        token=resolved_token,
        registry=registry,
        skip_build=skip_build,
    )
    print(json.dumps(result, indent=2, default=str))
