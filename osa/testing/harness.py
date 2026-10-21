"""Test harness for running hooks and ingesters in-process."""

from __future__ import annotations

import asyncio
import tempfile
import types
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from osa._registry import _hooks
from osa.authoring.ingester import Ingester
from osa.runtime.ingester_context import IngesterContext
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


@dataclass(frozen=True)
class IngesterResult:
    ingester_name: str
    records: list[IngesterRecord]
    files_dir: Path


async def _run_ingester_async(
    ingester: Ingester,
    ctx: IngesterContext,
    *,
    limit: int | None,
    session: dict[str, Any] | None,
) -> list[IngesterRecord]:
    try:
        records: list[IngesterRecord] = []
        async for record in ingester.pull(ctx=ctx, limit=limit, session=session):
            records.append(record)
        return records
    finally:
        await ctx.close()


def run_ingester(
    ingester_cls: type[Ingester],
    *,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
    files_dir: Path | None = None,
) -> IngesterResult:
    """Run an ingester in-process for testing — ONE batch.

    Creates an IngesterContext, calls pull(), and collects all yielded records.
    Files are downloaded to files_dir (or a temp directory if not provided).

    One batch only, so this cannot tell you whether your pagination works. If
    your source has more records than one batch, test with
    :func:`run_ingester_batches` instead.
    """
    resolved_files_dir = Path(tempfile.mkdtemp()) if files_dir is None else files_dir

    with tempfile.TemporaryDirectory() as output_dir:
        ingester_name = getattr(ingester_cls, "name", ingester_cls.__name__)

        runtime_config_cls = getattr(ingester_cls, "RuntimeConfig", None)
        if config is not None and runtime_config_cls is not None:
            validated = runtime_config_cls(**config)
            ingester = ingester_cls(validated)
        else:
            ingester = ingester_cls()

        ctx = IngesterContext(files_dir=resolved_files_dir, output_dir=Path(output_dir))

        records = asyncio.run(
            _run_ingester_async(ingester, ctx, limit=limit, session=session)
        )

    return IngesterResult(
        ingester_name=ingester_name,
        records=records,
        files_dir=resolved_files_dir,
    )


class StalledIngesterError(AssertionError):
    """An ingester re-emitted its window without advancing its session (#227)."""


@dataclass(frozen=True)
class IngesterBatchesResult:
    ingester_name: str
    records: list[IngesterRecord]
    batches: list[list[IngesterRecord]]
    files_dir: Path


def run_ingester_batches(
    ingester_cls: type[Ingester],
    *,
    batch_size: int,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    files_dir: Path | None = None,
    max_batches: int = 100,
) -> IngesterBatchesResult:
    """Run an ingester the way the server does — batch after batch, to completion.

    Calls ``pull()`` repeatedly, threading each batch's ``ctx.set_session``
    state into the next call, and stops when a batch sets no session. That is
    the real contract, and :func:`run_ingester` cannot exercise it: one batch
    always looks fine.

    Raises :class:`StalledIngesterError` as soon as a batch hands back the
    session it was given *and* re-emits the previous batch's records — the
    #227 loop, which in production cost hours of container time before the
    server learned to detect it. ``max_batches`` bounds anything stranger.

    ```python
    result = run_ingester_batches(MyIngester, batch_size=100)
    assert len(result.records) == 7600
    assert len(result.batches) == 76
    ```
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    resolved_files_dir = Path(tempfile.mkdtemp()) if files_dir is None else files_dir
    ingester_name = getattr(ingester_cls, "name", ingester_cls.__name__)

    records: list[IngesterRecord] = []
    batches: list[list[IngesterRecord]] = []
    session: dict[str, Any] | None = None

    for index in range(max_batches):
        remaining = (
            batch_size if limit is None else min(batch_size, limit - len(records))
        )
        if remaining <= 0:
            break

        with tempfile.TemporaryDirectory() as output_dir:
            ingester = _instantiate(ingester_cls, config)
            ctx = IngesterContext(
                files_dir=resolved_files_dir, output_dir=Path(output_dir)
            )
            batch = asyncio.run(
                _run_ingester_async(ingester, ctx, limit=remaining, session=session)
            )
            next_session = ctx.session

        _check_progress(index, batch, batches, session, next_session)

        batches.append(batch)
        records.extend(batch)

        # Setting no session is what ends the run.
        if next_session is None or not batch:
            break
        session = next_session
    else:
        raise StalledIngesterError(
            f"ingester {ingester_name!r} still had records after {max_batches} "
            f"batches ({len(records)} pulled). Either raise max_batches, or check "
            f"that the state you pass to ctx.set_session() advances and that you "
            f"stop setting it on the final batch."
        )

    return IngesterBatchesResult(
        ingester_name=ingester_name,
        records=records,
        batches=batches,
        files_dir=resolved_files_dir,
    )


def _instantiate(
    ingester_cls: type[Ingester], config: dict[str, Any] | None
) -> Ingester:
    runtime_config_cls = getattr(ingester_cls, "RuntimeConfig", None)
    if config is not None and runtime_config_cls is not None:
        return ingester_cls(runtime_config_cls(**config))
    return ingester_cls()


def _check_progress(
    index: int,
    batch: list[IngesterRecord],
    previous_batches: list[list[IngesterRecord]],
    session: dict[str, Any] | None,
    next_session: dict[str, Any] | None,
) -> None:
    """Fail the moment a batch provably repeats its predecessor (#227).

    Mirrors the server's guard: an unchanged session means the next pull gets
    identical inputs, and a repeated window of source ids confirms the output
    is identical too. Both together, so an ingester whose session is a constant
    marker but whose records advance is left alone.
    """
    if not batch or next_session is None or next_session != session:
        return
    if not previous_batches:
        return
    window = {record.source_id for record in batch}
    if window != {record.source_id for record in previous_batches[-1]}:
        return
    raise StalledIngesterError(
        f"batch {index} handed back the session it was given and re-emitted the "
        f"same {len(window)} records, so every further batch would be identical. "
        f"Continuation comes from ctx.set_session(...): read your start position "
        f"out of the `session` argument, advance the state you set, and set no "
        f"session on the final batch."
    )
