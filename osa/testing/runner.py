"""Convention test runner — orchestrates ingester + hooks end-to-end."""

from __future__ import annotations

import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from osa._registry import ConventionInfo
from osa.authoring.validator import Reject
from osa.testing.harness import run_hook, run_ingester


class TestError(Exception):
    """Raised when a convention test cannot proceed."""


@dataclass(frozen=True)
class HookOutcome:
    hook_name: str
    status: Literal["passed", "rejected", "error", "skipped"]
    result: Any = field(default=None)
    reason: str | None = None


@dataclass(frozen=True)
class RecordResult:
    source_id: str
    hooks: list[HookOutcome]

    @property
    def accepted(self) -> bool:
        return all(h.status in ("passed", "skipped") for h in self.hooks)


@dataclass(frozen=True)
class TestResult:
    convention_title: str
    ingester_name: str
    records: list[RecordResult]


def _run_hooks_for_record(
    hooks: list[types.FunctionType],
    *,
    meta: dict[str, Any],
    files_dir: Path,
) -> list[HookOutcome]:
    outcomes: list[HookOutcome] = []
    skip_remaining = False

    for hook_fn in hooks:
        if skip_remaining:
            outcomes.append(HookOutcome(hook_name=hook_fn.__name__, status="skipped"))
            continue
        try:
            result = run_hook(hook_fn, meta=meta, files=files_dir)
            outcomes.append(
                HookOutcome(hook_name=hook_fn.__name__, status="passed", result=result)
            )
        except Reject as e:
            outcomes.append(
                HookOutcome(
                    hook_name=hook_fn.__name__, status="rejected", reason=str(e)
                )
            )
            skip_remaining = True
        except Exception as e:
            outcomes.append(
                HookOutcome(hook_name=hook_fn.__name__, status="error", reason=str(e))
            )
            skip_remaining = True

    return outcomes


def run_test(
    *,
    convention_info: ConventionInfo,
    limit: int = 1,
    config: dict[str, Any] | None = None,
) -> TestResult:
    """Run a convention's full pipeline: ingester then hooks for each record."""
    if convention_info.ingester_info is None:
        raise TestError(
            f"Convention '{convention_info.title}' has no ingester. "
            "osa test requires a convention with an ingester."
        )

    ingester_result = run_ingester(
        convention_info.ingester_info.ingester_cls,
        limit=limit,
        config=config,
    )

    record_results: list[RecordResult] = []
    for record in ingester_result.records:
        files_path = ingester_result.files_dir / record.source_id
        outcomes = _run_hooks_for_record(
            convention_info.hooks, meta=record.metadata, files_dir=files_path
        )
        record_results.append(RecordResult(source_id=record.source_id, hooks=outcomes))

    return TestResult(
        convention_title=convention_info.title,
        ingester_name=ingester_result.ingester_name,
        records=record_results,
    )
