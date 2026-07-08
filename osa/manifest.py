"""Manifest generation for OSA deployments.

Introspects the hook registry to produce a typed, serializable
manifest describing all hooks and conventions in a project.
"""

from __future__ import annotations

import typing
from datetime import date, datetime
from typing import Any, get_args, get_origin
from uuid import UUID

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from osa._registry import HookInfo, _hooks


class ColumnDef(BaseModel):
    """Definition of a single column in a feature table."""

    name: str
    json_type: str
    format: str | None = None
    required: bool
    description: str | None = None
    unit: str | None = None


class HookManifestEntry(BaseModel):
    """Manifest entry for a single hook (display/introspection only)."""

    name: str
    record_schema: str
    cardinality: str
    columns: list[ColumnDef]
    runner: str = "oci"


class ConventionManifest(BaseModel):
    """Manifest entry for a convention."""

    title: str
    description: str
    version: str
    record_schema: str
    file_requirements: dict[str, Any]
    hook_names: list[str]
    ingester_name: str | None = None


class Manifest(BaseModel):
    """Full deployment manifest."""

    hooks: list[HookManifestEntry]
    conventions: list[ConventionManifest] = []
    schemas: dict[str, dict]


# ---- Type mapping for column generation ----

_PYTHON_TYPE_TO_JSON: dict[type, tuple[str, str | None]] = {
    str: ("string", None),
    float: ("number", None),
    int: ("integer", None),
    bool: ("boolean", None),
    datetime: ("string", "date-time"),
    date: ("string", "date"),
    UUID: ("string", "uuid"),
}


def _resolve_json_type(annotation: Any) -> tuple[str, str | None]:
    """Map a Python type annotation to (json_type, format)."""
    # Unwrap Optional[T] / T | None
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _resolve_json_type(non_none[0])

    # Handle list[X] → array
    if origin is list:
        return ("array", None)

    # Handle dict[X, Y] → object
    if origin is dict:
        return ("object", None)

    # Direct type lookup
    if annotation in _PYTHON_TYPE_TO_JSON:
        return _PYTHON_TYPE_TO_JSON[annotation]

    return ("string", None)


def _is_required(field_info: FieldInfo) -> bool:
    """Determine if a Pydantic field is required (non-optional)."""
    return field_info.is_required()


def _column_unit(field_info: FieldInfo) -> str | None:
    """Measurement unit from ``json_schema_extra["unit"]``, if declared."""
    extra = field_info.json_schema_extra
    if isinstance(extra, dict):
        unit = dict(extra).get("unit")
        if isinstance(unit, str):
            return unit
    return None


def generate_columns(model_cls: type[BaseModel]) -> list[ColumnDef]:
    """Generate column definitions from a Pydantic BaseModel.

    Carries the field's ``description`` and a ``json_schema_extra["unit"]``
    annotation through to the deploy payload (#151) so the node can document
    feature-table columns for agents.
    """
    columns: list[ColumnDef] = []
    for name, field_info in model_cls.model_fields.items():
        json_type, fmt = _resolve_json_type(field_info.annotation)
        columns.append(
            ColumnDef(
                name=name,
                json_type=json_type,
                format=fmt,
                required=_is_required(field_info),
                description=field_info.description,
                unit=_column_unit(field_info),
            )
        )
    return columns


# ---- Manifest generation ----


def _json_schema(cls: type) -> dict[str, Any]:
    """Extract JSON Schema from a Pydantic model."""
    if isinstance(cls, type) and issubclass(cls, BaseModel):
        return cls.model_json_schema()
    return {}


def _build_hook(info: HookInfo) -> HookManifestEntry:
    """Build a HookManifestEntry from introspected HookInfo."""
    columns: list[ColumnDef] = []
    if (
        info.output_type is not None
        and isinstance(info.output_type, type)
        and issubclass(info.output_type, BaseModel)
    ):
        columns = generate_columns(info.output_type)

    return HookManifestEntry(
        name=info.name,
        record_schema=info.schema_type.__name__,
        cardinality=info.cardinality,
        columns=columns,
        runner="oci",
    )


def generate_manifest() -> Manifest:
    """Generate the full deployment manifest from all registered hooks."""
    from osa._registry import _conventions

    hooks = [_build_hook(info) for info in _hooks]

    conventions = [
        ConventionManifest(
            title=c.title,
            description=c.description,
            version=c.version,
            record_schema=c.schema_type.__name__,
            file_requirements=c.file_requirements,
            hook_names=[h.__name__ for h in c.hooks],
            ingester_name=c.ingester_info.name if c.ingester_info else None,
        )
        for c in _conventions
    ]

    return Manifest(
        hooks=hooks,
        conventions=conventions,
        schemas={
            info.schema_type.__name__: _json_schema(info.schema_type)
            for info in _hooks
            if info.schema_type is not None
        },
    )
