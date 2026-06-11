"""Tests for the osa.cli.ui output layer."""

from __future__ import annotations

import io

import pytest

from osa.cli.ui import UI
from osa.cli.ui._glyphs import format_elapsed
from osa.cli.ui._renderer import PlainRenderer, RecordingRenderer


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("TERM", "xterm-256color")


class TestRendererSelection:
    def test_non_tty_gets_plain(self, clean_env: None) -> None:
        ui = UI.create(file=io.StringIO())
        assert isinstance(ui.renderer, PlainRenderer)

    def test_tty_gets_rich(self, clean_env: None) -> None:
        from osa.cli.ui._rich import RichRenderer

        ui = UI.create(file=FakeTTY())
        assert isinstance(ui.renderer, RichRenderer)

    def test_no_color_forces_plain(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        ui = UI.create(file=FakeTTY())
        assert isinstance(ui.renderer, PlainRenderer)

    def test_ci_forces_plain(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CI", "1")
        ui = UI.create(file=FakeTTY())
        assert isinstance(ui.renderer, PlainRenderer)

    def test_term_dumb_forces_plain(
        self, clean_env: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TERM", "dumb")
        ui = UI.create(file=FakeTTY())
        assert isinstance(ui.renderer, PlainRenderer)

    def test_force_plain_overrides_tty(self, clean_env: None) -> None:
        ui = UI.create(file=FakeTTY(), force_plain=True)
        assert isinstance(ui.renderer, PlainRenderer)


class TestElapsedFormatting:
    def test_subsecond(self) -> None:
        assert format_elapsed(0.64) == "0.6s"

    def test_seconds(self) -> None:
        assert format_elapsed(3.42) == "3.4s"

    def test_tens_of_seconds(self) -> None:
        assert format_elapsed(14.16) == "14.2s"

    def test_minutes(self) -> None:
        assert format_elapsed(72) == "1m12s"


class TestPlainRendererOutput:
    def _ui(self, *, verbose: bool = False) -> tuple[UI, io.StringIO, FakeClock]:
        buf = io.StringIO()
        clock = FakeClock()
        ui = UI.create(file=buf, force_plain=True, verbose=verbose, clock=clock)
        return ui, buf, clock

    def test_phase_header_with_count(self) -> None:
        ui, buf, _ = self._ui()
        with ui.phase("Building images", count=2):
            pass
        assert buf.getvalue() == "==> Building images (2)\n"

    def test_phase_header_without_count(self) -> None:
        ui, buf, _ = self._ui()
        with ui.phase("Registering conventions"):
            pass
        assert buf.getvalue() == "==> Registering conventions\n"

    def test_done_row_with_detail_and_elapsed(self) -> None:
        ui, buf, clock = self._ui()
        with ui.phase("Building images", count=1) as phase:
            with phase.task("microscopy-hook") as task:
                clock.advance(3.4)
                task.done(detail="9f2c1a")
        assert " ✓ microscopy-hook  9f2c1a  3.4s\n" in buf.getvalue()

    def test_auto_done_on_clean_exit(self) -> None:
        ui, buf, clock = self._ui()
        with ui.task("Started services") as _:
            clock.advance(12.1)
        assert " ✓ Started services  12.1s\n" in buf.getvalue()

    def test_skip_row(self) -> None:
        ui, buf, _ = self._ui()
        task = ui.task("spectra-ingester")
        task.skip("cached")
        assert " − spectra-ingester  cached\n" in buf.getvalue()

    def test_fail_row(self) -> None:
        ui, buf, _ = self._ui()
        with pytest.raises(ValueError):
            with ui.task("build") as _:
                raise ValueError("boom")
        assert " ✗ build  boom\n" in buf.getvalue()

    def test_success_with_arrow_and_elapsed(self) -> None:
        ui, buf, _ = self._ui()
        ui.success("Deployed 2 conventions", arrow="archive.example.org", elapsed=14.2)
        assert (
            buf.getvalue() == " ✓ Deployed 2 conventions → archive.example.org  14.2s\n"
        )

    def test_info_and_detail_lines(self) -> None:
        ui, buf, _ = self._ui()
        ui.info("Open: https://example.org/device")
        ui.detail("osa.yaml    archive configuration")
        assert buf.getvalue() == (
            "   Open: https://example.org/device\n"
            "   osa.yaml    archive configuration\n"
        )

    def test_warn_line(self) -> None:
        ui, buf, _ = self._ui()
        ui.warn("1 record rejected")
        assert buf.getvalue() == " ⚠ 1 record rejected\n"

    def test_error_block(self) -> None:
        ui, buf, _ = self._ui()
        ui.error(
            "Docker build failed for spectra-ingester",
            cause="error: failed to solve\nexit code 1",
            hint="Re-run with --verbose for full build output",
        )
        assert buf.getvalue() == (
            " ✗ Docker build failed for spectra-ingester\n"
            "   error: failed to solve\n"
            "   exit code 1\n"
            " → Re-run with --verbose for full build output\n"
        )

    def test_table_alignment(self) -> None:
        ui, buf, _ = self._ui()
        ui.table(
            ["SERVICE", "STATE"],
            [["postgres", "healthy"], ["archive-api", "starting"]],
        )
        assert buf.getvalue() == (
            " SERVICE      STATE\n postgres     healthy\n archive-api  starting\n"
        )

    def test_log_lines_suppressed_by_default(self) -> None:
        ui, buf, _ = self._ui()
        with ui.task("build") as task:
            task.log("#1 exporting layers")
        assert "exporting layers" not in buf.getvalue()

    def test_log_lines_echoed_when_verbose(self) -> None:
        ui, buf, _ = self._ui(verbose=True)
        with ui.task("build") as task:
            task.log("#1 exporting layers\n")
        assert "   #1 exporting layers\n" in buf.getvalue()


class TestTaskStateMachine:
    def _ui(self) -> tuple[UI, RecordingRenderer]:
        rec = RecordingRenderer()
        return UI(rec, clock=FakeClock()), rec

    def test_event_sequence(self) -> None:
        ui, rec = self._ui()
        with ui.phase("Building", count=1) as phase:
            with phase.task("img") as task:
                task.detail("building")
        assert [e[0] for e in rec.events] == [
            "phase_started",
            "task_started",
            "task_updated",
            "task_finished",
            "phase_finished",
        ]
        assert rec.events[3][1]["state"] == "done"

    def test_exception_marks_failed_and_reraises(self) -> None:
        ui, rec = self._ui()
        with pytest.raises(ValueError, match="boom"):
            with ui.task("t"):
                raise ValueError("boom")
        finished = [e for e in rec.events if e[0] == "task_finished"]
        assert finished[0][1]["state"] == "failed"
        assert finished[0][1]["message"] == "boom"

    def test_double_terminal_state_raises(self) -> None:
        ui, _ = self._ui()
        task = ui.task("t")
        task.done()
        with pytest.raises(RuntimeError):
            task.fail("nope")

    def test_skip_without_entering(self) -> None:
        ui, rec = self._ui()
        ui.task("img").skip("cached")
        assert [e[0] for e in rec.events] == ["task_finished"]
        assert rec.events[0][1]["state"] == "skipped"
        assert rec.events[0][1]["message"] == "cached"

    def test_log_buffers_full_output(self) -> None:
        ui, _ = self._ui()
        with ui.task("build") as task:
            task.log("line one\n")
            task.log("line two")
            assert task.log_lines == ["line one", "line two"]


class TestRichRendererSmoke:
    def test_renders_without_error(self, clean_env: None) -> None:
        buf = FakeTTY()
        ui = UI.create(file=buf)
        with ui.phase("Building images", count=1) as phase:
            with phase.task("microscopy-hook") as task:
                task.log("#1 exporting layers")
                task.detail("pushing")
                task.progress(0.5, "layer 3/7")
                task.done(detail="9f2c1a")
        ui.success("Deployed", arrow="archive.example.org", elapsed=1.0)
        ui.error("failed", cause="cause", hint="hint")
        ui.table(["A", "B"], [["1", "2"]])
        out = buf.getvalue()
        assert "microscopy-hook" in out
        assert "Building images" in out
