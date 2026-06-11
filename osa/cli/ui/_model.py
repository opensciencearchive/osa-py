"""Domain objects for CLI output: UI, Phase, Task."""

from __future__ import annotations

import os
import sys
import time
from enum import Enum
from types import TracebackType
from typing import IO, Callable, Sequence

from ._renderer import PlainRenderer, Renderer


class TaskState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


_TERMINAL_STATES = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.SKIPPED})


class Task:
    """A single unit of work rendered as one status row.

    Context manager: a spinner row while open collapses into a permanent
    row on exit. Clean exit without an explicit terminal state implies
    ``done()``; an escaping exception implies ``fail(str(exc))``.
    """

    def __init__(
        self,
        title: str,
        *,
        renderer: Renderer,
        clock: Callable[[], float],
        phase: Phase | None = None,
    ) -> None:
        self.title = title
        self.state = TaskState.PENDING
        self.detail_text: str | None = None
        self.message: str | None = None
        self.progress_fraction: float | None = None
        self.progress_label: str | None = None
        self.log_lines: list[str] = []
        self.elapsed: float | None = None
        self.phase = phase
        self._renderer = renderer
        self._clock = clock
        self._started_at: float | None = None

    def __enter__(self) -> Task:
        self.state = TaskState.RUNNING
        self._started_at = self._clock()
        self._renderer.task_started(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if self.state not in _TERMINAL_STATES:
            if exc is not None:
                self.fail(str(exc) or type(exc).__name__)
            else:
                self.done()
        return False

    def detail(self, text: str) -> None:
        self.detail_text = text
        self._renderer.task_updated(self)

    def progress(self, fraction: float, label: str | None = None) -> None:
        self.progress_fraction = fraction
        self.progress_label = label
        self._renderer.task_updated(self)

    def log(self, line: str) -> None:
        line = line.rstrip("\n")
        self.log_lines.append(line)
        self._renderer.task_log(self, line)

    def done(self, detail: str | None = None) -> None:
        if detail is not None:
            self.detail_text = detail
        self._finish(TaskState.DONE)

    def fail(self, message: str) -> None:
        self.message = message
        self._finish(TaskState.FAILED)

    def skip(self, reason: str) -> None:
        self.message = reason
        self._finish(TaskState.SKIPPED)

    def _finish(self, state: TaskState) -> None:
        if self.state in _TERMINAL_STATES:
            raise RuntimeError(
                f"Task {self.title!r} already finished ({self.state.value})"
            )
        self.state = state
        if self._started_at is not None:
            self.elapsed = self._clock() - self._started_at
        self._renderer.task_finished(self)


class Phase:
    """A group of tasks under a ``==> Title (count)`` header."""

    def __init__(
        self,
        title: str,
        *,
        count: int | None,
        renderer: Renderer,
        clock: Callable[[], float],
    ) -> None:
        self.title = title
        self.count = count
        self._renderer = renderer
        self._clock = clock

    def __enter__(self) -> Phase:
        self._renderer.phase_started(self)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        self._renderer.phase_finished(self)
        return False

    def task(self, title: str) -> Task:
        return Task(title, renderer=self._renderer, clock=self._clock, phase=self)


def _should_use_rich(file: IO[str]) -> bool:
    try:
        is_tty = file.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    return (
        is_tty
        and not os.environ.get("NO_COLOR")
        and not os.environ.get("CI")
        and os.environ.get("TERM") != "dumb"
    )


class UI:
    """Entry point for all CLI chrome. Renders to stderr by default."""

    def __init__(
        self,
        renderer: Renderer,
        *,
        verbose: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.renderer = renderer
        self.verbose = verbose
        self._clock = clock

    @classmethod
    def create(
        cls,
        *,
        verbose: bool = False,
        file: IO[str] | None = None,
        force_plain: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> UI:
        out = file if file is not None else sys.stderr
        use_rich = not force_plain if force_plain is not None else _should_use_rich(out)
        renderer: Renderer
        if use_rich:
            from ._rich import RichRenderer

            renderer = RichRenderer(out, verbose=verbose)
        else:
            renderer = PlainRenderer(out, verbose=verbose)
        return cls(renderer, verbose=verbose, clock=clock)

    def phase(self, title: str, *, count: int | None = None) -> Phase:
        return Phase(title, count=count, renderer=self.renderer, clock=self._clock)

    def task(self, title: str) -> Task:
        return Task(title, renderer=self.renderer, clock=self._clock)

    def info(self, text: str) -> None:
        self.renderer.info(text)

    def detail(self, text: str) -> None:
        self.renderer.detail(text)

    def success(
        self,
        text: str,
        *,
        arrow: str | None = None,
        elapsed: float | None = None,
    ) -> None:
        self.renderer.success(text, arrow, elapsed)

    def warn(self, text: str) -> None:
        self.renderer.warn(text)

    def error(
        self,
        headline: str,
        *,
        cause: str | None = None,
        hint: str | None = None,
    ) -> None:
        self.renderer.error(headline, cause, hint)

    def table(self, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        self.renderer.table(columns, rows)
