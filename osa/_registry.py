"""Global hook and convention registry for @hook decorator and convention()."""

from __future__ import annotations

import types
import typing
from dataclasses import dataclass, field
from typing import Any

from osa.authoring.example import Example
from osa.types.ingester import IngesterSchedule, InitialRun, Limits
from osa.types.schema import MetadataSchema


@dataclass
class HookInfo:
    """Metadata extracted from a decorated hook function."""

    fn: types.FunctionType
    name: str
    hook_type: str
    schema_type: type[MetadataSchema]
    return_type: type | None = None
    output_type: type | None = None
    cardinality: str = "one"
    dependencies: dict[str, type] = field(default_factory=dict)
    limits: Limits = field(default_factory=Limits)


@dataclass
class IngesterInfo:
    """Metadata from a registered ingester class."""

    ingester_cls: type
    name: str
    schedule: IngesterSchedule | None = None
    initial_run: InitialRun | None = None
    limits: Limits = field(default_factory=lambda: Limits(timeout_seconds=3600))
    max_file_mb: float | None = None


@dataclass
class ConventionInfo:
    """Metadata from a convention() declaration.

    ``purpose``/``examples`` default empty only at this internal layer —
    ``convention()`` requires them, and the deploy pre-flight rejects an
    undocumented ConventionInfo before any build or network call (#151).
    """

    title: str
    description: str
    version: str
    schema_type: type[MetadataSchema]
    file_requirements: dict[str, Any]
    hooks: list[types.FunctionType]
    ingester_info: IngesterInfo | None = None
    purpose: str = ""
    examples: list[Example] = field(default_factory=list)
    example_questions: list[str] = field(default_factory=list)
    when_not_to_use: str | None = None
    see_also: list[str] | None = None


_hooks: list[HookInfo] = []
_conventions: list[ConventionInfo] = []
_ingesters: list[IngesterInfo] = []


def clear() -> None:
    """Remove all registered hooks, conventions, and ingesters. Used in tests."""
    _hooks.clear()
    _conventions.clear()
    _ingesters.clear()


def register_ingester(ingester_cls: type) -> IngesterInfo:
    """Register an ingester class and return its IngesterInfo."""
    name = getattr(ingester_cls, "name", ingester_cls.__name__)
    schedule = getattr(ingester_cls, "schedule", None)
    initial_run = getattr(ingester_cls, "initial_run", None)
    limits = getattr(ingester_cls, "limits", Limits(timeout_seconds=3600))
    max_file_mb = getattr(ingester_cls, "max_file_mb", None)
    info = IngesterInfo(
        ingester_cls=ingester_cls,
        name=name,
        schedule=schedule,
        initial_run=initial_run,
        limits=limits,
        max_file_mb=max_file_mb,
    )
    _ingesters.append(info)
    return info


def _extract_hook_info(fn: types.FunctionType, hook_type: str) -> HookInfo:
    """Introspect a hook function's type hints to extract metadata."""
    hints = typing.get_type_hints(fn)

    schema_type: type[MetadataSchema] | None = None
    return_type: type | None = None
    dependencies: dict[str, type] = {}

    for param_name, hint in hints.items():
        if param_name == "return":
            return_type = hint
            continue

        origin = typing.get_origin(hint)
        if origin is not None:
            args = typing.get_args(hint)
            if getattr(origin, "__name__", "") == "Record" and args:
                schema_type = args[0]
                continue

        dependencies[param_name] = hint

    if schema_type is None:
        msg = f"Hook {fn.__name__} must have a Record[T] parameter"
        raise TypeError(msg)

    output_type: type | None = None
    cardinality = "one"
    if return_type is not None:
        if typing.get_origin(return_type) is list:
            cardinality = "many"
            args = typing.get_args(return_type)
            output_type = args[0] if args else None
        else:
            cardinality = "one"
            output_type = return_type

    return HookInfo(
        fn=fn,
        name=fn.__name__,
        hook_type=hook_type,
        schema_type=schema_type,
        return_type=return_type,
        output_type=output_type,
        cardinality=cardinality,
        dependencies=dependencies,
    )


def register(
    fn: types.FunctionType, hook_type: str, *, limits: Limits | None = None
) -> None:
    """Register a decorated function as a hook."""
    info = _extract_hook_info(fn, hook_type)
    if limits is not None:
        info.limits = limits
    _hooks.append(info)
