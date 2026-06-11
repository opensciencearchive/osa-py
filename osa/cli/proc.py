"""Streamed subprocess execution feeding the UI log-tail window."""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from osa.cli.ui import Task


class ProcResult(BaseModel):
    returncode: int
    output: str


def run_streamed(
    args: list[str],
    *,
    task: Task,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> ProcResult:
    """Run a subprocess, streaming each output line into ``task.log()``.

    stderr is merged into stdout so a single reader loop suffices (avoids
    the classic two-pipe deadlock). Full output is always captured for
    failure dumps regardless of renderer verbosity.
    """
    proc = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
        env=env,
    )
    lines: list[str] = []
    assert proc.stdout is not None
    with proc.stdout:
        for line in proc.stdout:
            lines.append(line)
            task.log(line)
    returncode = proc.wait()
    return ProcResult(returncode=returncode, output="".join(lines))


def tail(output: str, max_lines: int) -> str:
    """Last ``max_lines`` of output, with a truncation note when cut."""
    lines = output.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    kept = lines[-max_lines:]
    note = f"(output truncated to last {max_lines} lines — use --verbose for all)"
    return "\n".join([note, *kept])
