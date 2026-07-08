"""Convention registration function."""

from __future__ import annotations

import types
from typing import Any

from osa._registry import ConventionInfo, _conventions, register_ingester
from osa.authoring.example import Example
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
    purpose: str,
    examples: list[Example],
    example_questions: list[str] | None = None,
    when_not_to_use: str | None = None,
    see_also: list[str] | None = None,
) -> None:
    """Register a convention that composes schemas, hooks, and an optional ingester.

    The convention's stable identity slug is assigned server-side at registration.

    Documentation is mandatory (#151): ``purpose`` and at least one worked
    ``Example`` are required, and the node needs ≥3 distinct trigger questions
    across ``example_questions`` and the worked examples' questions (a worked
    example's question counts, so nothing is written twice). The deploy
    pre-flight and the server both enforce this — there is no skip flag.
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
            purpose=purpose,
            examples=list(examples),
            example_questions=list(example_questions or []),
            when_not_to_use=when_not_to_use,
            see_also=see_also,
        )
    )
