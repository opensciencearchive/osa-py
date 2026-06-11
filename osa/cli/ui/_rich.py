"""Rich-backed renderer. The only module in the package that imports rich."""

from __future__ import annotations

import time
from collections import deque
from typing import IO, TYPE_CHECKING, Sequence

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from ._glyphs import format_elapsed, glyphs_for

if TYPE_CHECKING:
    from ._model import Phase, Task

_TAIL_LINES = 5
_BAR_WIDTH = 12
_TITLE_PAD = 20


class RichRenderer:
    """Live spinner/progress rows that collapse into permanent rows."""

    def __init__(self, file: IO[str], *, verbose: bool = False) -> None:
        self._console = Console(file=file, highlight=False, soft_wrap=True)
        self._verbose = verbose
        self._glyphs = glyphs_for(self._console.legacy_windows)
        self._live: Live | None = None
        self._active: list[Task] = []
        self._tails: dict[int, deque[str]] = {}

    # -- live region ---------------------------------------------------

    def _ensure_live(self) -> None:
        if self._live is None:
            self._live = Live(
                get_renderable=self._render_active,
                console=self._console,
                refresh_per_second=10,
                transient=True,
            )
            self._live.start()

    def _stop_live_if_idle(self) -> None:
        if self._live is not None and not self._active:
            self._live.stop()
            self._live = None

    def _render_active(self) -> RenderableType:
        g = self._glyphs
        frame = g.spinner[int(time.monotonic() * 10) % len(g.spinner)]
        parts: list[RenderableType] = []
        for task in self._active:
            row = Text()
            row.append(f" {frame} ", style="cyan")
            row.append(task.title.ljust(_TITLE_PAD))
            if task.progress_fraction is not None:
                row.append("  " + self._bar(task.progress_fraction), style="cyan")
                if task.progress_label:
                    row.append(f"  {task.progress_label}", style="dim")
            elif task.detail_text:
                row.append(f"  {task.detail_text}", style="dim")
            parts.append(row)
            tail = self._tails.get(id(task))
            if tail:
                for line in tail:
                    parts.append(Text(f"   {g.tail} {line}", style="dim", no_wrap=True))
        if parts:
            # Bottom padding so the live region reads as a finite window
            # rather than running into the edge of the terminal.
            parts.append(Text(""))
        return Group(*parts)

    def _bar(self, fraction: float) -> str:
        g = self._glyphs
        fraction = max(0.0, min(1.0, fraction))
        done = int(fraction * _BAR_WIDTH)
        todo = _BAR_WIDTH - done - 1
        bar = g.bar_done * done
        if todo >= 0:
            bar += g.bar_head + g.bar_todo * todo
        return f"{bar}  {int(fraction * 100):3d}%"

    def _print_row(self, left: Text, elapsed: float | None) -> None:
        if elapsed is None:
            self._console.print(left)
            return
        grid = Table.grid(expand=True)
        grid.add_column()
        grid.add_column(justify="right")
        grid.add_row(left, Text(format_elapsed(elapsed), style="dim"))
        self._console.print(grid)

    # -- renderer protocol ----------------------------------------------

    def phase_started(self, phase: Phase) -> None:
        suffix = f" ({phase.count})" if phase.count is not None else ""
        self._console.print(Text(f"==> {phase.title}{suffix}", style="bold"))

    def phase_finished(self, phase: Phase) -> None:
        pass

    def task_started(self, task: Task) -> None:
        self._active.append(task)
        self._tails[id(task)] = deque(maxlen=_TAIL_LINES)
        self._ensure_live()

    def task_updated(self, task: Task) -> None:
        pass  # live region re-renders via get_renderable

    def task_log(self, task: Task, line: str) -> None:
        if self._verbose:
            self._console.print(Text(f"   {line}", style="dim"))
        else:
            tail = self._tails.get(id(task))
            if tail is not None:
                tail.append(line)

    def task_finished(self, task: Task) -> None:
        from ._model import TaskState

        if task in self._active:
            self._active.remove(task)
        self._tails.pop(id(task), None)
        g = self._glyphs
        row = Text()
        if task.state is TaskState.DONE:
            row.append(f" {g.check} ", style="green")
            row.append(task.title.ljust(_TITLE_PAD) if task.detail_text else task.title)
            if task.detail_text:
                row.append(f"  {task.detail_text}", style="dim")
            self._print_row(row, task.elapsed)
        elif task.state is TaskState.FAILED:
            row.append(f" {g.cross} ", style="red")
            row.append(task.title)
            if task.message:
                row.append(f"  {task.message}", style="red")
            self._print_row(row, None)
        else:
            row.append(f" {g.skip} {task.title}  {task.message}", style="dim")
            self._print_row(row, None)
        self._stop_live_if_idle()

    def info(self, text: str) -> None:
        self._console.print(Text(f"   {text}"))

    def detail(self, text: str) -> None:
        self._console.print(Text(f"   {text}", style="dim"))

    def success(self, text: str, arrow: str | None, elapsed: float | None) -> None:
        g = self._glyphs
        row = Text()
        row.append(f" {g.check} ", style="green")
        row.append(text, style="bold")
        if arrow:
            row.append(f" {g.arrow} ", style="dim")
            row.append(arrow, style="cyan")
        self._print_row(row, elapsed)

    def warn(self, text: str) -> None:
        row = Text()
        row.append(f" {self._glyphs.warn} ", style="yellow")
        row.append(text)
        self._console.print(row)

    def error(self, headline: str, cause: str | None, hint: str | None) -> None:
        g = self._glyphs
        row = Text()
        row.append(f" {g.cross} ", style="red")
        row.append(headline, style="bold")
        self._console.print(row)
        if cause:
            for line in cause.splitlines():
                self._console.print(Text(f"   {line}", style="dim"))
        if hint:
            hint_row = Text()
            hint_row.append(f" {g.arrow} ", style="yellow")
            hint_row.append(hint)
            self._console.print(hint_row)

    def table(self, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        table = Table(
            box=None,
            show_header=True,
            header_style="dim",
            pad_edge=False,
            padding=(0, 2, 0, 1),
        )
        for column in columns:
            table.add_column(column)
        for row in rows:
            table.add_row(*[str(cell) for cell in row])
        self._console.print(table)
