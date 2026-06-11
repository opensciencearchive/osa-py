"""OSA CLI — Typer app for the `osa` command."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Optional

if TYPE_CHECKING:
    from osa.testing.runner import TestResult

import typer
from pydantic import BaseModel, ConfigDict

from osa.cli._ingestion_commands import ingestion_app
from osa.cli._runtime_commands import (
    emit_command,
    meta_command,
    progress_command,
    reject_command,
)
from osa.cli.ui import UI


class CLIState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ui: UI


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        print(f"osa {version('osa-py')}")
        raise typer.Exit()


app = typer.Typer(help="OSA — Open Scientific Archive CLI")
app.add_typer(ingestion_app, name="ingestion")


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            "-v",
            help="Stream full subprocess output and extra detail.",
        ),
    ] = False,
) -> None:
    """OSA — Open Scientific Archive CLI"""
    ctx.obj = CLIState(ui=UI.create(verbose=verbose))


def _ui(ctx: typer.Context) -> UI:
    state = ctx.obj
    return state.ui if isinstance(state, CLIState) else UI.create()


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
    ctx: typer.Context,
    server: Annotated[str, typer.Option(help="Server URL to link.")],
) -> None:
    """Link this project to an OSA server."""
    from osa.cli.link import write_link

    ui = _ui(ctx)
    config_path = write_link(server)
    ui.success(f"Linked to {server.rstrip('/')}")
    ui.detail(f"Config written to {config_path}")


@app.command()
def login(
    ctx: typer.Context,
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
) -> None:
    """Authenticate with an OSA server via device flow."""
    from osa.cli.link import resolve_server
    from osa.cli.login import login as do_login

    server_url = resolve_server(flag=server)
    success = do_login(server_url, ui=_ui(ctx))
    if not success:
        raise typer.Exit(1)


@app.command()
def logout(
    ctx: typer.Context,
    server: Annotated[Optional[str], typer.Option(help="Server URL.")] = None,
) -> None:
    """Remove stored credentials for a server."""
    from osa.cli.link import resolve_server
    from osa.cli.logout import logout as do_logout

    server_url = resolve_server(flag=server)
    do_logout(server_url, ui=_ui(ctx))


@app.command()
def deploy(
    ctx: typer.Context,
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

    from osa.cli.deploy import DeployError, deploy as do_deploy
    from osa.cli.link import resolve_server

    ui = _ui(ctx)

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    server_url = resolve_server(flag=server)
    resolved_token = token

    if not resolved_token:
        from osa.cli.credentials import resolve_token

        resolved_token = resolve_token(server_url)
        if resolved_token is None:
            ui.error("Not authenticated", hint="Run `osa login` first")
            raise typer.Exit(1)

    try:
        do_deploy(
            server=server_url,
            token=resolved_token,
            registry=registry,
            skip_build=skip_build,
            ui=ui,
        )
    except DeployError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None


@app.command(name="init")
def init_cmd(
    ctx: typer.Context,
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

    ui = _ui(ctx)
    try:
        result = init_project(
            project_dir=project_dir.resolve(),
            name=name,
            force=force,
        )
    except InstanceError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    ui.success(f"Initialized OSA project in {result.project_dir}")
    width = max(len(path) for path, _ in result.created)
    for path, description in result.created:
        ui.detail(f"{path.ljust(width)}  {description}")
    ui.info("")
    ui.info("Next steps:")
    if result.show_cd:
        ui.info(f"  cd {result.project_dir.name}")
    ui.info("  osa start")


@app.command()
def start(
    ctx: typer.Context,
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
    osa_version: Annotated[
        Optional[str],
        typer.Option("--osa-version", help="OSA server image version tag."),
    ] = None,
) -> None:
    """Start the local OSA instance."""
    from osa.cli.instance import InstanceError, start_instance

    ui = _ui(ctx)
    try:
        start_instance(
            project_dir=Path.cwd(),
            detach=detach,
            source=source.resolve() if source else None,
            with_ui=with_ui,
            osa_version=osa_version,
            ui=ui,
        )
    except InstanceError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None


@app.command()
def stop(ctx: typer.Context) -> None:
    """Stop the local OSA instance."""
    from osa.cli.instance import InstanceError, stop_instance

    ui = _ui(ctx)
    try:
        stop_instance(project_dir=Path.cwd(), ui=ui)
    except InstanceError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None


@app.command()
def logs(
    ctx: typer.Context,
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
        _ui(ctx).error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None


_STATE_GLYPHS = {"running": "✓", "exited": "✗", "dead": "✗", "paused": "⚠"}


@app.command()
def status(ctx: typer.Context) -> None:
    """Show status of the local OSA instance."""
    from osa.cli.instance import InstanceError, instance_status

    ui = _ui(ctx)
    try:
        services = instance_status(project_dir=Path.cwd())
    except InstanceError as e:
        ui.error(str(e), cause=e.cause, hint=e.hint)
        raise typer.Exit(1) from None

    if not services:
        ui.info("No services running — run `osa start` to launch the archive")
        return

    rows = [
        [
            _STATE_GLYPHS.get(s.state, "⚠"),
            s.name,
            s.state + (f" ({s.health})" if s.health else ""),
            s.ports,
        ]
        for s in services
    ]
    ui.table(["", "SERVICE", "STATE", "PORTS"], rows)


@app.command("test")
def test_cmd(
    ctx: typer.Context,
    limit: Annotated[
        int,
        typer.Option(help="Max records to pull from the ingester."),
    ] = 1,
    convention: Annotated[
        Optional[str],
        typer.Option(
            "--convention", help="Convention title. Auto-detected if omitted."
        ),
    ] = None,
) -> None:
    """Test a convention end-to-end: run the ingester, then all hooks."""
    import importlib
    import importlib.metadata

    from osa._registry import _conventions
    from osa.testing.runner import TestError, run_test

    ui = _ui(ctx)

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)

    candidates = [c for c in _conventions if c.ingester_info is not None]

    if not candidates:
        ui.error("No conventions with an ingester found")
        raise typer.Exit(1)

    if convention:
        matched = [c for c in candidates if c.title == convention]
        if not matched:
            ui.error(f"Convention '{convention}' not found")
            raise typer.Exit(1)
        conv = matched[0]
    elif len(candidates) == 1:
        conv = candidates[0]
        assert conv.ingester_info is not None
        typer.confirm(
            f"Test {conv.title}@{conv.version} (ingester: {conv.ingester_info.name})?",
            abort=True,
        )
    else:
        ui.info("Multiple conventions found:")
        for i, c in enumerate(candidates, 1):
            assert c.ingester_info is not None
            ui.info(f"  {i}. {c.title}@{c.version} (ingester: {c.ingester_info.name})")
        choice = typer.prompt("Select a convention", type=int)
        if choice < 1 or choice > len(candidates):
            ui.error("Invalid selection")
            raise typer.Exit(1)
        conv = candidates[choice - 1]

    with ui.task(f"Running {conv.ingester_info.name}") as task:  # type: ignore[union-attr]
        try:
            result = run_test(convention_info=conv, limit=limit)
        except TestError as e:
            task.fail(str(e))
            raise typer.Exit(1) from None
        ids = ", ".join(r.source_id for r in result.records)
        task.done(detail=f"{len(result.records)} record(s) ({ids})" if ids else "")

    _render_test_result(result, ui)

    if not result.records:
        raise typer.Exit(1)


def _render_test_result(result: TestResult, ui: UI) -> None:
    for record in result.records:
        with ui.phase(record.source_id):
            for hook_outcome in record.hooks:
                if hook_outcome.status == "passed":
                    detail = _format_result(hook_outcome.result)
                    suffix = f" → {detail}" if detail else ""
                    ui.success(f"{hook_outcome.hook_name}{suffix}")
                elif hook_outcome.status == "rejected":
                    ui.error(
                        f"{hook_outcome.hook_name} → Reject: {hook_outcome.reason}"
                    )
                elif hook_outcome.status == "error":
                    ui.error(f"{hook_outcome.hook_name} → Error: {hook_outcome.reason}")
                elif hook_outcome.status == "skipped":
                    ui.detail(f"{hook_outcome.hook_name} (skipped)")

    accepted = sum(1 for r in result.records if r.accepted)
    rejected = len(result.records) - accepted
    summary = (
        f"{len(result.records)} record(s): {accepted} accepted, {rejected} rejected"
    )
    if rejected:
        ui.warn(summary)
    else:
        ui.success(summary)


def _format_result(result: object) -> str:
    if result is None:
        return ""
    if isinstance(result, list):
        if not result:
            return "0 results"
        type_name = type(result[0]).__name__
        return f"{len(result)} {type_name}(s)"
    return type(result).__name__
