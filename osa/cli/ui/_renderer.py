"""Renderer protocol plus plain-text and recording implementations."""

from __future__ import annotations

from typing import IO, TYPE_CHECKING, Any, Protocol, Sequence

from ._glyphs import UNICODE, format_elapsed

if TYPE_CHECKING:
    from ._model import Phase, Task


class Renderer(Protocol):
    def phase_started(self, phase: Phase) -> None: ...
    def phase_finished(self, phase: Phase) -> None: ...
    def task_started(self, task: Task) -> None: ...
    def task_updated(self, task: Task) -> None: ...
    def task_log(self, task: Task, line: str) -> None: ...
    def task_finished(self, task: Task) -> None: ...
    def info(self, text: str) -> None: ...
    def detail(self, text: str) -> None: ...
    def success(self, text: str, arrow: str | None, elapsed: float | None) -> None: ...
    def warn(self, text: str) -> None: ...
    def error(self, headline: str, cause: str | None, hint: str | None) -> None: ...
    def table(self, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None: ...


class PlainRenderer:
    """Sequential lines, no ANSI, no redraws. Same wording as the rich renderer."""

    def __init__(self, file: IO[str], *, verbose: bool = False) -> None:
        self._file = file
        self._verbose = verbose
        self._glyphs = UNICODE

    def _write(self, line: str) -> None:
        self._file.write(line + "\n")
        self._file.flush()

    def phase_started(self, phase: Phase) -> None:
        suffix = f" ({phase.count})" if phase.count is not None else ""
        self._write(f"==> {phase.title}{suffix}")

    def phase_finished(self, phase: Phase) -> None:
        pass

    def task_started(self, task: Task) -> None:
        if self._verbose:
            self._write(f"   {task.title} ...")

    def task_updated(self, task: Task) -> None:
        pass

    def task_log(self, task: Task, line: str) -> None:
        if self._verbose:
            self._write(f"   {line}")

    def task_finished(self, task: Task) -> None:
        from ._model import TaskState

        g = self._glyphs
        if task.state is TaskState.DONE:
            parts = [f" {g.check} {task.title}"]
            if task.detail_text:
                parts.append(task.detail_text)
            if task.elapsed is not None:
                parts.append(format_elapsed(task.elapsed))
            self._write("  ".join(parts))
        elif task.state is TaskState.FAILED:
            self._write(f" {g.cross} {task.title}  {task.message}")
        else:
            self._write(f" {g.skip} {task.title}  {task.message}")

    def info(self, text: str) -> None:
        self._write(f"   {text}".rstrip())

    def detail(self, text: str) -> None:
        self._write(f"   {text}".rstrip())

    def success(self, text: str, arrow: str | None, elapsed: float | None) -> None:
        g = self._glyphs
        line = f" {g.check} {text}"
        if arrow:
            line += f" {g.arrow} {arrow}"
        if elapsed is not None:
            line += f"  {format_elapsed(elapsed)}"
        self._write(line)

    def warn(self, text: str) -> None:
        self._write(f" {self._glyphs.warn} {text}")

    def error(self, headline: str, cause: str | None, hint: str | None) -> None:
        g = self._glyphs
        self._write(f" {g.cross} {headline}")
        if cause:
            for line in cause.splitlines():
                self._write(f"   {line}")
        if hint:
            self._write(f" {g.arrow} {hint}")

    def table(self, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        widths = [
            max(len(str(columns[i])), *(len(str(r[i])) for r in rows))
            if rows
            else len(str(columns[i]))
            for i in range(len(columns))
        ]
        for row in [columns, *rows]:
            cells = [str(cell).ljust(widths[i]) for i, cell in enumerate(row)]
            self._write((" " + "  ".join(cells)).rstrip())


class RecordingRenderer:
    """Captures renderer events as (name, snapshot) tuples for tests."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _task_snapshot(self, task: Task) -> dict[str, Any]:
        return {
            "title": task.title,
            "state": task.state.value,
            "detail": task.detail_text,
            "message": task.message,
            "log_count": len(task.log_lines),
        }

    def phase_started(self, phase: Phase) -> None:
        self.events.append(
            ("phase_started", {"title": phase.title, "count": phase.count})
        )

    def phase_finished(self, phase: Phase) -> None:
        self.events.append(("phase_finished", {"title": phase.title}))

    def task_started(self, task: Task) -> None:
        self.events.append(("task_started", self._task_snapshot(task)))

    def task_updated(self, task: Task) -> None:
        self.events.append(("task_updated", self._task_snapshot(task)))

    def task_log(self, task: Task, line: str) -> None:
        self.events.append(("task_log", {"title": task.title, "line": line}))

    def task_finished(self, task: Task) -> None:
        self.events.append(("task_finished", self._task_snapshot(task)))

    def info(self, text: str) -> None:
        self.events.append(("info", {"text": text}))

    def detail(self, text: str) -> None:
        self.events.append(("detail", {"text": text}))

    def success(self, text: str, arrow: str | None, elapsed: float | None) -> None:
        self.events.append(
            ("success", {"text": text, "arrow": arrow, "elapsed": elapsed})
        )

    def warn(self, text: str) -> None:
        self.events.append(("warn", {"text": text}))

    def error(self, headline: str, cause: str | None, hint: str | None) -> None:
        self.events.append(
            ("error", {"headline": headline, "cause": cause, "hint": hint})
        )

    def table(self, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        self.events.append(("table", {"columns": list(columns), "rows": rows}))
