"""Convention registration function."""

from __future__ import annotations

import types
from typing import Any

from osa._registry import ConventionInfo, _conventions, register_ingester
from osa.types.schema import MetadataSchema


def convention(
    *,
    title: str,
    description: str,
    version: str,
    schema: type[MetadataSchema],
    ingester: type | None = None,
    files: dict[str, Any],
    hooks: list[types.FunctionType],
) -> None:
    """Register a convention that composes schemas, hooks, and an optional ingester.

    The convention's stable identity slug is assigned server-side at registration.
    """
    ingester_info = None
    if ingester is not None:
        ingester_info = register_ingester(ingester)

    _conventions.append(
        ConventionInfo(
            title=title,
            description=description,
            version=version,
            schema_type=schema,
            file_requirements=files,
            hooks=hooks,
            ingester_info=ingester_info,
        )
    )
