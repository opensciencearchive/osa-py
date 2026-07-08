"""Metadata schema definitions for OSA validators and transforms."""

from __future__ import annotations

import re
import typing
from datetime import date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict
from pydantic import Field as _PydanticField
from pydantic.fields import FieldInfo

# Python type → (FieldType, extra_constraints)
_TYPE_MAP: dict[type, str] = {
    str: "text",
    int: "number",
    float: "number",
    bool: "boolean",
    date: "date",
    datetime: "date",
}

_SCHEMA_ID_RE = re.compile(r"^[a-z][a-z0-9\-]{2,63}$")


class MetadataSchema(BaseModel):
    """Base class for defining typed metadata schemas.

    Subclass this to declare the metadata fields a record must provide.
    Uses Pydantic validation under the hood — fields support constraints
    like ``ge``, ``le``, ``pattern``, ``Literal``, etc.

    Every concrete subclass MUST declare ``__schema_id__`` — a human-readable
    slug matching ``^[a-z][a-z0-9-]{2,63}$``. It becomes the ``<id>`` segment
    of the server-side ``<id>@<semver>`` identity, so it should be stable and
    meaningful (e.g. ``"pdb-structure"``).

    Extra fields not declared in the schema are rejected.
    """

    model_config = ConfigDict(extra="forbid")

    __schema_id__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        schema_id = cls.__dict__.get("__schema_id__")
        if schema_id is None:
            raise TypeError(
                f"{cls.__name__} must declare ``__schema_id__`` — a slug matching "
                f"^[a-z][a-z0-9-]{{2,63}}$ (e.g. '__schema_id__ = \"pdb-structure\"')."
            )
        if not isinstance(schema_id, str) or not _SCHEMA_ID_RE.match(schema_id):
            raise TypeError(
                f"{cls.__name__}.__schema_id__ = {schema_id!r} is invalid: "
                "must be 3–64 chars of [a-z0-9-] and start with a letter."
            )

    @classmethod
    def schema_id(cls) -> str:
        """Return the declared slug — the ``<id>`` in ``<id>@<semver>``."""
        return cls.__schema_id__

    @classmethod
    def to_field_definitions(cls) -> list[dict[str, Any]]:
        """Convert this schema's fields to server FieldDefinition dicts.

        Maps Python type hints to the server's FieldType format:
            str → text, int → number (integer_only), float → number,
            bool → boolean, date/datetime → date, T | None → required=False.
        """
        result: list[dict[str, Any]] = []
        for name, field_info in cls.model_fields.items():
            annotation = field_info.annotation
            required = field_info.is_required()

            # Unwrap Optional[T] / T | None
            inner = _unwrap_optional(annotation)

            # Resolve field type
            field_type = _TYPE_MAP.get(inner, "text")

            field_def: dict[str, Any] = {
                "name": name,
                "type": field_type,
                "required": required,
                "cardinality": "exactly_one",
            }

            if field_info.description:
                field_def["description"] = field_info.description

            examples = _field_examples(field_info)
            if examples:
                field_def["examples"] = examples

            # Build constraints (discriminated union with "type" key)
            constraints: dict[str, Any] | None = None
            if field_type == "number":
                c: dict[str, Any] = {"type": "number"}
                if inner is int:
                    c["integer_only"] = True
                extra = field_info.json_schema_extra
                if isinstance(extra, dict) and "unit" in extra:
                    c["unit"] = extra["unit"]
                constraints = c
            elif field_type == "text":
                extra = field_info.json_schema_extra
                if isinstance(extra, dict):
                    text_extra = {k: v for k, v in extra.items() if k != "examples"}
                    if text_extra:
                        constraints = {"type": "text", **text_extra}

            if constraints:
                field_def["constraints"] = constraints

            result.append(field_def)
        return result


def _field_examples(field_info: FieldInfo) -> list[str]:
    """Representative values for a field: native pydantic ``examples`` or
    ``json_schema_extra["examples"]``, normalized to strings."""
    examples: list[Any] | None = field_info.examples
    if not examples:
        extra = field_info.json_schema_extra
        if isinstance(extra, dict):
            raw = dict(extra).get("examples")
            examples = raw if isinstance(raw, list) else None
    return [str(e) for e in examples] if examples else []


def _unwrap_optional(annotation: Any) -> type:
    """Unwrap Optional[T] / T | None to get the inner type."""
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Union:
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return non_none[0]
    return annotation


def Field(*, unit: str | None = None, **kwargs: Any) -> Any:
    """Declare a metadata field with optional unit annotation.

    Thin wrapper around :func:`pydantic.Field` that adds an optional
    ``unit`` keyword. The unit value is stored in ``json_schema_extra``
    and appears in the generated JSON Schema.

    Returns ``Any`` (like :func:`pydantic.Field`) so a typed field default
    ``name: T = Field(...)`` type-checks instead of tripping an
    assignment-type error.
    """
    extra: dict[str, Any] = kwargs.pop("json_schema_extra", None) or {}
    if unit is not None:
        extra["unit"] = unit
    if extra:
        kwargs["json_schema_extra"] = extra
    return _PydanticField(**kwargs)
