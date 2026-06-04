"""Test harness for running hooks and ingesters in-process."""

from __future__ import annotations

import asyncio
import tempfile
import types
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from osa._registry import _hooks
from osa.types.files import FileCollection
from osa.types.ingester import IngesterRecord
from osa.types.record import Record
from osa.types.schema import MetadataSchema


def _get_schema_type(fn: types.FunctionType) -> type[MetadataSchema]:
    """Look up the schema type for a hook function from the registry."""
    for info in _hooks:
        if info.fn is fn:
            return info.schema_type
    msg = f"Function {fn.__name__} is not a registered hook"
    raise ValueError(msg)


def _build_record(
    fn: types.FunctionType,
    meta: dict[str, Any] | MetadataSchema,
    files: Path | None,
    srn: str | None = None,
) -> Record[Any]:
    """Construct a Record[T] for testing from a decorated function."""
    schema_type = _get_schema_type(fn)

    if isinstance(meta, dict):
        metadata = schema_type(**meta)
    else:
        metadata = meta

    if files is not None:
        file_collection = FileCollection(files)
    else:
        import tempfile

        file_collection = FileCollection(Path(tempfile.mkdtemp()))

    return Record(
        id=str(uuid.uuid4()),
        created_at=datetime.now(),
        metadata=metadata,
        files=file_collection,
        srn=srn or "",
    )


def run_hook(
    fn: types.FunctionType,
    *,
    meta: dict[str, Any] | MetadataSchema,
    files: Path | None = None,
    srn: str | None = None,
) -> Any:
    """Run a hook function in-process for testing.

    Constructs a :class:`Record[T]` from the provided metadata and
    optional files directory, then executes the hook.
    """
    record = _build_record(fn, meta, files, srn=srn)
    return fn(record)


@dataclass
class IngesterResult:
    ingester_name: str
    records: list[IngesterRecord]
    files_dir: Path
    _temp_dir: tempfile.TemporaryDirectory[str] | None = field(default=None, repr=False)


async def _run_ingester_async(
    ingester: Any,
    ctx: Any,
    *,
    limit: int | None,
    since: datetime | None,
    session: dict[str, Any] | None,
) -> list[IngesterRecord]:
    try:
        records: list[IngesterRecord] = []
        async for record in ingester.pull(
            ctx=ctx, since=since, limit=limit, offset=0, session=session
        ):
            records.append(record)
        return records
    finally:
        await ctx.close()


def run_ingester(
    ingester_cls: type,
    *,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    since: datetime | None = None,
    session: dict[str, Any] | None = None,
    files_dir: Path | None = None,
) -> IngesterResult:
    """Run an ingester in-process for testing.

    Creates an IngesterContext, calls pull(), and collects all yielded records.
    Files are downloaded to files_dir (or a temp directory if not provided).
    """
    from osa.runtime.ingester_context import IngesterContext

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if files_dir is None:
        temp_dir = tempfile.TemporaryDirectory()
        files_dir = Path(temp_dir.name)

    output_temp = tempfile.TemporaryDirectory()
    output_dir = Path(output_temp.name)

    ingester_name = getattr(ingester_cls, "name", ingester_cls.__name__)

    runtime_config_cls = getattr(ingester_cls, "RuntimeConfig", None)
    if config is not None and runtime_config_cls is not None:
        validated = runtime_config_cls(**config)
        ingester = ingester_cls(validated)
    else:
        ingester = ingester_cls()

    ctx = IngesterContext(files_dir=files_dir, output_dir=output_dir)

    records = asyncio.run(
        _run_ingester_async(ingester, ctx, limit=limit, since=since, session=session)
    )

    return IngesterResult(
        ingester_name=ingester_name,
        records=records,
        files_dir=files_dir,
        _temp_dir=temp_dir,
    )
