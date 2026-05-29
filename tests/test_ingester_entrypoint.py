"""Tests for the ingester entrypoint — max_file_mb filtering."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from osa._registry import IngesterInfo, clear, _ingesters
from osa.runtime.ingester_context import IngesterContext
from osa.runtime.ingester_entrypoint import run_ingester_entrypoint
from osa.types.ingester import IngesterFileRef, IngesterRecord


class FakeIngester:
    """Ingester that yields pre-built records."""

    name = "fake"
    schedule = None
    initial_run = None
    max_file_mb = None

    _records: list[IngesterRecord] = []

    def __init__(self, config=None) -> None:
        pass

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        since: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        for r in self.__class__._records:
            yield r


def _make_record(source_id: str, files: list[IngesterFileRef]) -> IngesterRecord:
    return IngesterRecord(
        source_id=source_id, metadata={"title": source_id}, files=files
    )


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    files_dir = tmp_path / "files"
    input_dir.mkdir()
    (input_dir / "config.json").write_text("{}")
    return input_dir, output_dir, files_dir


def _write_fake_files(files_dir: Path, record: IngesterRecord) -> None:
    """Create actual files on disk matching the record's file refs."""
    for f in record.files:
        path = files_dir / f.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x00" * 64)


def _read_records(output_dir: Path) -> list[dict]:
    records_path = output_dir / "records.jsonl"
    if not records_path.exists():
        return []
    records = []
    for line in records_path.read_text().strip().split("\n"):
        if line.strip():
            records.append(json.loads(line))
    return records


class TestMaxFileMbFilter:
    def setup_method(self) -> None:
        clear()
        FakeIngester._records = []

    def _register(
        self, records: list[IngesterRecord], max_file_mb: float | None = None
    ) -> None:
        FakeIngester._records = records
        info = IngesterInfo(
            ingester_cls=FakeIngester,
            name="fake",
            max_file_mb=max_file_mb,
        )
        _ingesters.append(info)

    def test_no_limit_passes_all_records(self, tmp_path: Path) -> None:
        small = _make_record(
            "rec1",
            [IngesterFileRef(name="a.cif", relative_path="rec1/a.cif", size_mb=5.0)],
        )
        large = _make_record(
            "rec2",
            [IngesterFileRef(name="b.cif", relative_path="rec2/b.cif", size_mb=100.0)],
        )
        self._register([small, large], max_file_mb=None)

        input_dir, output_dir, files_dir = _setup_dirs(tmp_path)

        exit_code = run_ingester_entrypoint(
            input_dir=input_dir, output_dir=output_dir, files_dir=files_dir
        )
        assert exit_code == 0

        records = _read_records(output_dir)
        assert len(records) == 2

    def test_oversized_record_skipped(self, tmp_path: Path) -> None:
        small = _make_record(
            "rec1",
            [IngesterFileRef(name="a.cif", relative_path="rec1/a.cif", size_mb=5.0)],
        )
        large = _make_record(
            "rec2",
            [IngesterFileRef(name="b.cif", relative_path="rec2/b.cif", size_mb=100.0)],
        )
        self._register([small, large], max_file_mb=40.0)

        input_dir, output_dir, files_dir = _setup_dirs(tmp_path)
        _write_fake_files(files_dir, large)

        exit_code = run_ingester_entrypoint(
            input_dir=input_dir, output_dir=output_dir, files_dir=files_dir
        )
        assert exit_code == 0

        records = _read_records(output_dir)
        assert len(records) == 1
        assert records[0]["source_id"] == "rec1"

        # Oversized file should be cleaned up
        assert not (files_dir / "rec2" / "b.cif").exists()

    def test_all_files_under_limit_passes(self, tmp_path: Path) -> None:
        rec = _make_record(
            "rec1",
            [
                IngesterFileRef(name="a.cif", relative_path="rec1/a.cif", size_mb=10.0),
                IngesterFileRef(name="b.cif", relative_path="rec1/b.cif", size_mb=20.0),
            ],
        )
        self._register([rec], max_file_mb=40.0)

        input_dir, output_dir, files_dir = _setup_dirs(tmp_path)

        exit_code = run_ingester_entrypoint(
            input_dir=input_dir, output_dir=output_dir, files_dir=files_dir
        )
        assert exit_code == 0

        records = _read_records(output_dir)
        assert len(records) == 1

    def test_one_oversized_file_skips_entire_record(self, tmp_path: Path) -> None:
        rec = _make_record(
            "rec1",
            [
                IngesterFileRef(
                    name="small.cif", relative_path="rec1/small.cif", size_mb=5.0
                ),
                IngesterFileRef(
                    name="huge.cif", relative_path="rec1/huge.cif", size_mb=200.0
                ),
            ],
        )
        self._register([rec], max_file_mb=40.0)

        input_dir, output_dir, files_dir = _setup_dirs(tmp_path)
        _write_fake_files(files_dir, rec)

        exit_code = run_ingester_entrypoint(
            input_dir=input_dir, output_dir=output_dir, files_dir=files_dir
        )
        assert exit_code == 0

        records = _read_records(output_dir)
        assert len(records) == 0
