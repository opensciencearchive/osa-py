"""OSA CLI — Typer app for the `osa` command."""

from __future__ import annotations

import json
import sys
from pathlib import Path
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


@app.command(name="init")
def init_cmd(
    project_dir: Annotated[
        Path,
        typer.Argument(help="Directory to initialize (default: current directory)."),
    ] = Path("."),
    name: Annotated[
        Optional[str],
        typer.Option(help="Archive name (defaults to directory name)."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing configuration files."),
    ] = False,
) -> None:
    """Initialize a new OSA archive project."""
    from osa.cli.instance import InstanceError, init_project

    try:
        init_project(
            project_dir=project_dir.resolve(),
            name=name,
            force=force,
        )
    except InstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def start(
    detach: Annotated[
        bool,
        typer.Option("--detach", "-d", help="Run in background."),
    ] = True,
    source: Annotated[
        Optional[Path],
        typer.Option("--source", help="Path to OSA server source for dev mode."),
    ] = None,
    with_ui: Annotated[
        bool,
        typer.Option("--with-ui", help="Start the web UI."),
    ] = False,
) -> None:
    """Start the local OSA instance."""
    from osa.cli.instance import InstanceError, start_instance

    try:
        start_instance(
            project_dir=Path.cwd(),
            detach=detach,
            source=source.resolve() if source else None,
            with_ui=with_ui,
        )
    except InstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def stop() -> None:
    """Stop the local OSA instance."""
    from osa.cli.instance import InstanceError, stop_instance

    try:
        stop_instance(project_dir=Path.cwd())
    except InstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def logs(
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Follow log output."),
    ] = False,
    service: Annotated[
        Optional[str],
        typer.Argument(help="Service name (e.g. server, db)."),
    ] = None,
    tail: Annotated[
        Optional[int],
        typer.Option("--tail", help="Number of lines to show from end."),
    ] = None,
) -> None:
    """View logs from the local OSA instance."""
    from osa.cli.instance import InstanceError, instance_logs

    try:
        instance_logs(
            project_dir=Path.cwd(),
            follow=follow,
            service=service,
            tail=tail,
        )
    except InstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None


@app.command()
def status() -> None:
    """Show status of the local OSA instance."""
    from osa.cli.instance import InstanceError, instance_status

    try:
        instance_status(project_dir=Path.cwd())
    except InstanceError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise typer.Exit(1) from None
