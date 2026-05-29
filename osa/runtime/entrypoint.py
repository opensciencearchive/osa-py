"""Container entrypoint for the unified batch hook contract.

Reads records.jsonl, runs the hook per record, writes features/rejections/errors JSONL.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import sys
import tempfile
import types
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from osa._registry import _hooks
from osa.authoring.validator import Reject
from osa.runtime.logging import setup_logging
from osa.types.files import FileCollection
from osa.types.record import Record
from osa.types.schema import MetadataSchema

log = logging.getLogger("osa.hook.entrypoint")


def _discover_conventions() -> None:
    """Auto-discover convention packages via entry points."""
    import importlib
    import importlib.metadata

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)


def _get_schema_type(fn: types.FunctionType) -> type[MetadataSchema]:
    """Look up the schema type for a hook function from the registry."""
    for info in _hooks:
        if info.fn is fn:
            return info.schema_type
    msg = f"Function {fn.__name__} is not a registered hook"
    raise ValueError(msg)


def _serialize_features(result: Any) -> list[Any]:
    """Serialize hook result to a features list.

    Scalar results are wrapped in a single-element list.
    BaseModel instances are dumped to dicts.
    """
    if isinstance(result, list):
        return [
            item.model_dump() if isinstance(item, BaseModel) else item
            for item in result
        ]
    if isinstance(result, BaseModel):
        return [result.model_dump()]
    return [result]


def run_hook_entrypoint(
    *,
    hook_fn: types.FunctionType,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    files_dir: Path | None = None,
) -> int:
    """Run a hook against the unified batch contract.

    Reads ``records.jsonl`` from the input directory, runs the hook per record,
    and writes ``features.jsonl``, ``rejections.jsonl``, ``errors.jsonl``.

    Always returns 0 unless there is an infrastructure failure (missing input, etc).
    """
    setup_logging()
    _discover_conventions()

    if input_dir is None:
        input_dir = Path(os.environ.get("OSA_IN", "/osa/in"))
    if output_dir is None:
        output_dir = Path(os.environ.get("OSA_OUT", "/osa/out"))
    if files_dir is None:
        files_dir = Path(os.environ.get("OSA_FILES", "/osa/files"))

    if not input_dir.exists():
        log.error("input directory not found: %s", input_dir)
        return 1

    records_path = input_dir / "records.jsonl"
    if not records_path.exists():
        log.error("records.jsonl not found in %s", input_dir)
        return 1

    # Count records for the startup log
    total_lines = sum(1 for line in records_path.open() if line.strip())

    schema_type = _get_schema_type(hook_fn)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("HOOK START hook=%s records=%d", hook_fn.__name__, total_lines)

    passed = 0
    rejected = 0
    errored = 0
    processed = 0

    with (
        (output_dir / "features.jsonl").open("w") as features_f,
        (output_dir / "rejections.jsonl").open("w") as rejections_f,
        (output_dir / "errors.jsonl").open("w") as errors_f,
    ):
        for line_num, line in enumerate(records_path.open(), 1):
            line = line.strip()
            if not line:
                continue

            processed += 1
            record_id = f"line-{line_num}"

            try:
                data = json.loads(line)
                record_id = data["id"]
                metadata_fields = data["metadata"]
            except (json.JSONDecodeError, KeyError) as e:
                log.error(
                    "[%s] malformed record at line %d: %s", record_id, line_num, e
                )
                errored += 1
                errors_f.write(
                    json.dumps(
                        {
                            "id": record_id,
                            "error": f"malformed record: {e}",
                            "retryable": False,
                        }
                    )
                    + "\n"
                )
                continue

            # Per-record files from $OSA_FILES/{id}/
            record_files_dir = files_dir / record_id
            if record_files_dir.is_dir():
                file_collection = FileCollection(record_files_dir)
            else:
                log.debug("[%s] no files directory, using empty dir", record_id)
                file_collection = FileCollection(Path(tempfile.mkdtemp()))

            try:
                metadata = schema_type(**metadata_fields)
            except Exception as e:
                log.warning("[%s] metadata validation failed: %s", record_id, e)
                errored += 1
                errors_f.write(
                    json.dumps(
                        {
                            "id": record_id,
                            "error": f"metadata validation: {e}",
                            "retryable": False,
                        }
                    )
                    + "\n"
                )
                continue

            try:
                record: Record[Any] = Record(
                    id=record_id,
                    created_at=datetime.now(),
                    metadata=metadata,
                    files=file_collection,
                    srn="",
                )
                result = hook_fn(record)
                features = _serialize_features(result)
                features_f.write(
                    json.dumps({"id": record_id, "features": features}) + "\n"
                )
                passed += 1
                log.debug("[%s] passed (%d features)", record_id, len(features))
            except Reject as e:
                rejected += 1
                log.info("[%s] rejected: %s", record_id, e)
                rejections_f.write(
                    json.dumps({"id": record_id, "reason": str(e)}) + "\n"
                )
            except Exception as e:
                errored += 1
                log.error("[%s] hook error: %s", record_id, e, exc_info=True)
                errors_f.write(
                    json.dumps({"id": record_id, "error": str(e), "retryable": False})
                    + "\n"
                )
            finally:
                gc.collect()
                try:
                    import ctypes

                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except (OSError, AttributeError):
                    pass  # not Linux / glibc

    log.info(
        "HOOK DONE %d total, %d passed, %d rejected, %d errored",
        processed,
        passed,
        rejected,
        errored,
    )

    return 0


def _resolve_hook_fn() -> types.FunctionType:
    """Resolve the hook function from OSA_HOOK_NAME or single-hook fallback."""
    setup_logging()
    _discover_conventions()

    hook_name = os.environ.get("OSA_HOOK_NAME")
    if hook_name:
        matches = [h for h in _hooks if h.name == hook_name]
        if not matches:
            log.error("hook '%s' not found in registry", hook_name)
            sys.exit(1)
        return matches[0].fn
    elif len(_hooks) == 1:
        return _hooks[0].fn
    else:
        log.error("OSA_HOOK_NAME not set and %d hooks registered", len(_hooks))
        sys.exit(1)


def main() -> None:
    """Console script entry point for osa-run-hook."""
    sys.exit(run_hook_entrypoint(hook_fn=_resolve_hook_fn()))
