"""Container entrypoint for the OCI ingester filesystem contract.

Run as: python -m osa.runtime.ingester_entrypoint

Flow:
1. Read $OSA_IN/config.json → ingester config
2. Parse env vars: OSA_SINCE, OSA_LIMIT, OSA_OFFSET
3. Discover ingester class from _ingesters registry
4. Create IngesterContext(files_dir=$OSA_FILES, output_dir=$OSA_OUT)
5. Call ingester.pull() → AsyncIterator[IngesterRecord]
6. Write each record as a JSON line to $OSA_OUT/records.jsonl
7. If session state set, write $OSA_OUT/session.json
8. Exit 0
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from osa._registry import _ingesters
from osa.runtime.ingester_context import IngesterContext
from osa.runtime.logging import setup_logging

log = logging.getLogger("osa.ingester.entrypoint")


def _discover_conventions() -> None:
    """Auto-discover convention packages via entry points."""
    import importlib
    import importlib.metadata

    for ep in importlib.metadata.entry_points(group="osa.conventions"):
        importlib.import_module(ep.value)


async def _run(
    *,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    files_dir: Path | None = None,
) -> int:
    """Run the ingester entrypoint. Returns exit code."""
    setup_logging()
    _discover_conventions()

    if input_dir is None:
        input_dir = Path(os.environ.get("OSA_IN", "/osa/in"))
    if output_dir is None:
        output_dir = Path(os.environ.get("OSA_OUT", "/osa/out"))
    if files_dir is None:
        files_dir = Path(os.environ.get("OSA_FILES", "/osa/files"))

    # Discover ingester
    if not _ingesters:
        log.error("no ingesters registered")
        return 1

    ingester_info = _ingesters[0]
    ingester_cls = ingester_info.ingester_cls

    # Read config
    config = None
    config_path = input_dir / "config.json"
    if config_path.exists():
        try:
            config_data = json.loads(config_path.read_text())
            if hasattr(ingester_cls, "RuntimeConfig"):
                config = ingester_cls.RuntimeConfig(**config_data)  # type: ignore[attr-defined]
            else:
                config = config_data
        except (json.JSONDecodeError, OSError) as exc:
            log.error("failed to read config.json: %s", exc)
            return 1

    # Parse env vars
    since: datetime | None = None
    since_str = os.environ.get("OSA_SINCE")
    if since_str:
        since = datetime.fromisoformat(since_str)

    limit: int | None = None
    limit_str = os.environ.get("OSA_LIMIT")
    if limit_str:
        limit = int(limit_str)

    offset = int(os.environ.get("OSA_OFFSET", "0"))

    # Read session from input if available
    session = None
    session_path = input_dir / "session.json"
    if session_path.exists():
        try:
            session = json.loads(session_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Instantiate ingester
    if config is not None:
        ingester = ingester_cls(config)
    else:
        ingester = ingester_cls()

    # Create context
    files_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    ctx = IngesterContext(files_dir=files_dir, output_dir=output_dir)

    log.info(
        "INGESTER START name=%s since=%s limit=%s offset=%d session=%s",
        ingester_info.name,
        since,
        limit,
        offset,
        session,
    )

    max_file_mb = ingester_info.max_file_mb

    try:
        # Write records.jsonl
        records_path = output_dir / "records.jsonl"
        count = 0
        skipped = 0
        with records_path.open("w") as f:
            async for record in ingester.pull(
                ctx=ctx,
                since=since,
                limit=limit,
                offset=offset,
                session=session,
            ):
                if max_file_mb is not None:
                    oversized = [
                        file for file in record.files if file.size_mb > max_file_mb
                    ]
                    if oversized:
                        for file in oversized:
                            log.warning(
                                "Skipping record %s: file %s is %.1fMB (limit: %.0fMB)",
                                record.source_id,
                                file.name,
                                file.size_mb,
                                max_file_mb,
                            )
                            # Clean up downloaded files for this record
                            file_path = files_dir / file.relative_path
                            file_path.unlink(missing_ok=True)
                        skipped += 1
                        continue

                f.write(record.model_dump_json() + "\n")
                count += 1

        # Write session if set
        ctx.write_session()

        if skipped:
            log.info(
                "INGESTER DONE %d records yielded, %d skipped (max_file_mb=%.0f)",
                count,
                skipped,
                max_file_mb,
            )
        else:
            log.info("INGESTER DONE %d records yielded", count)
        return 0

    except Exception as exc:
        log.error("INGESTER FAILED: %s", exc, exc_info=True)
        return 1
    finally:
        await ctx.close()


def run_ingester_entrypoint(
    *,
    input_dir: Path | None = None,
    output_dir: Path | None = None,
    files_dir: Path | None = None,
) -> int:
    """Synchronous wrapper for the ingester entrypoint."""
    return asyncio.run(
        _run(input_dir=input_dir, output_dir=output_dir, files_dir=files_dir)
    )


def main() -> None:
    """Console script entry point for osa-run-ingester."""
    sys.exit(run_ingester_entrypoint())


if __name__ == "__main__":
    main()
