"""OSA CLI logout command."""

from __future__ import annotations

from pathlib import Path

from osa.cli.credentials import _DEFAULT_PATH, remove_credentials
from osa.cli.ui import UI


def logout(
    server: str,
    *,
    cred_path: Path = _DEFAULT_PATH,
    ui: UI | None = None,
) -> None:
    """Remove stored credentials for a server URL."""
    ui = ui or UI.create()
    server = server.rstrip("/")
    removed = remove_credentials(server, path=cred_path)

    if removed:
        ui.success(f"Logged out from {server}")
    else:
        ui.info(f"No credentials found for {server}")
