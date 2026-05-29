"""OCI container helper commands: meta, emit, progress, reject."""

from __future__ import annotations

import json
import os
from pathlib import Path


def meta_command() -> str:
    """Generate and return manifest JSON from the hook registry."""
    from osa.manifest import generate_manifest

    manifest = generate_manifest()
    return manifest.model_dump_json(indent=2)


def emit_command(data: str) -> None:
    """Write feature data to $OSA_OUT/features.json."""
    output_dir = Path(os.environ.get("OSA_OUT", "/osa/out"))
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = json.loads(data)
    (output_dir / "features.json").write_text(json.dumps(parsed, indent=2))


def progress_command(
    *,
    step: str | None = None,
    status: str,
    message: str | None = None,
) -> None:
    """Append a progress entry to $OSA_OUT/progress.jsonl."""
    output_dir = Path(os.environ.get("OSA_OUT", "/osa/out"))
    output_dir.mkdir(parents=True, exist_ok=True)
    entry: dict = {"status": status}
    if step is not None:
        entry["step"] = step
    if message is not None:
        entry["message"] = message
    with (output_dir / "progress.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def reject_command(*, reason: str) -> None:
    """Write a rejection entry to $OSA_OUT/progress.jsonl."""
    output_dir = Path(os.environ.get("OSA_OUT", "/osa/out"))
    output_dir.mkdir(parents=True, exist_ok=True)
    entry = {"status": "rejected", "message": reason}
    with (output_dir / "progress.jsonl").open("a") as f:
        f.write(json.dumps(entry) + "\n")
