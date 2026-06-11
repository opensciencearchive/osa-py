"""CLI output layer: phases, tasks, and status lines.

All CLI chrome goes through :class:`UI` (rendered to stderr); data such as
JSON results stays on stdout. Commands must never import rich directly —
rich is an implementation detail of this package.

Convention: never run interactive prompts (``typer.confirm``/``prompt``)
while a phase or task is open — prompt first, then start phases.
"""

from __future__ import annotations

from ._model import UI, Phase, Task, TaskState

__all__ = ["UI", "Phase", "Task", "TaskState"]
