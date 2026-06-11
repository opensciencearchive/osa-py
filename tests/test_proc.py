"""Tests for osa.cli.proc streamed subprocess execution."""

from __future__ import annotations

import io
from pathlib import Path

from osa.cli.proc import ProcResult, run_streamed, tail
from osa.cli.ui import UI


def _task_ui() -> UI:
    return UI.create(file=io.StringIO(), force_plain=True)


class TestRunStreamed:
    def test_captures_full_output(self) -> None:
        with _task_ui().task("t") as task:
            result = run_streamed(["sh", "-c", "echo one; echo two"], task=task)
        assert result.returncode == 0
        assert result.output == "one\ntwo\n"

    def test_streams_lines_to_task_log(self) -> None:
        with _task_ui().task("t") as task:
            run_streamed(["sh", "-c", "echo one; echo two"], task=task)
            assert task.log_lines == ["one", "two"]

    def test_merges_stderr_into_output(self) -> None:
        with _task_ui().task("t") as task:
            result = run_streamed(["sh", "-c", "echo err >&2"], task=task)
        assert "err" in result.output
        assert task.log_lines == ["err"]

    def test_nonzero_exit(self) -> None:
        with _task_ui().task("t") as task:
            result = run_streamed(["sh", "-c", "echo bad; exit 3"], task=task)
        assert result.returncode == 3
        assert "bad" in result.output

    def test_cwd_forwarding(self, tmp_path: Path) -> None:
        with _task_ui().task("t") as task:
            result = run_streamed(["pwd"], task=task, cwd=tmp_path)
        assert result.output.strip().endswith(tmp_path.name)

    def test_env_forwarding(self) -> None:
        with _task_ui().task("t") as task:
            result = run_streamed(
                ["sh", "-c", "echo $OSA_TEST_VAR"],
                task=task,
                env={"OSA_TEST_VAR": "hello", "PATH": "/usr/bin:/bin"},
            )
        assert result.output.strip() == "hello"


class TestTail:
    def test_short_output_unchanged(self) -> None:
        assert tail("a\nb\n", 5) == "a\nb"

    def test_truncates_to_last_lines(self) -> None:
        text = "\n".join(str(i) for i in range(100))
        result = tail(text, 3)
        assert result.splitlines()[-3:] == ["97", "98", "99"]
        assert "(output truncated" in result.splitlines()[0]

    def test_empty(self) -> None:
        assert tail("", 5) == ""


class TestProcResult:
    def test_model_fields(self) -> None:
        result = ProcResult(returncode=0, output="x")
        assert result.returncode == 0
        assert result.output == "x"
