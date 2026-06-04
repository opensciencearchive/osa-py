"""Tests for run_hook() test harness."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from osa.types.record import Record
from osa.types.schema import MetadataSchema


class SampleSchema(MetadataSchema):
    __schema_id__ = "sample-schema-1"

    organism: str
    title: str


class PocketResult(BaseModel):
    pocket_id: str
    score: float


class QualityResult(BaseModel):
    atom_count: int
    completeness: float


class TestRunHook:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_passes_valid_metadata(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            assert record.metadata.organism == "Human"
            return QualityResult(atom_count=100, completeness=0.9)

        result = run_hook(
            check,
            meta={"organism": "Human", "title": "Test"},
        )
        assert result.atom_count == 100

    def test_returns_typed_result_scalar(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=42, completeness=0.5)

        result = run_hook(check, meta={"organism": "Mouse", "title": "Test"})
        assert isinstance(result, QualityResult)
        assert result.atom_count == 42

    def test_returns_typed_result_list(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return [
                PocketResult(pocket_id="P1", score=0.9),
                PocketResult(pocket_id="P2", score=0.7),
            ]

        result = run_hook(detect, meta={"organism": "Human", "title": "Test"})
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0].pocket_id == "P1"

    def test_catches_reject(self) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            raise Reject("Bad data")

        with pytest.raises(Reject, match="Bad data"):
            run_hook(check, meta={"organism": "Human", "title": "Test"})

    def test_passes_files_directory(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        # Create a test file
        (tmp_path / "test.cif").write_text("ATOM 1")

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            files = record.files.glob("*.cif")
            assert len(files) == 1
            return [PocketResult(pocket_id="P1", score=0.8)]

        result = run_hook(
            detect,
            meta={"organism": "Human", "title": "Test"},
            files=tmp_path,
        )
        assert len(result) == 1

    def test_passes_srn_to_record(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            assert record.srn == "urn:osa:localhost:dep:abc123"
            return QualityResult(atom_count=50, completeness=1.0)

        result = run_hook(
            check,
            meta={"organism": "Human", "title": "Test"},
            srn="urn:osa:localhost:dep:abc123",
        )
        assert result.completeness == 1.0

    def test_srn_defaults_to_empty(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            assert record.srn == ""
            return QualityResult(atom_count=50, completeness=1.0)

        run_hook(check, meta={"organism": "Human", "title": "Test"})

    def test_works_without_files(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.harness import run_hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=50, completeness=1.0)

        result = run_hook(check, meta={"organism": "Human", "title": "Test"})
        assert result.completeness == 1.0


class FakeIngester:
    name = "fake-ingester"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(self, *, ctx, since=None, limit=None, offset=0, session=None):
        from osa.types.ingester import IngesterRecord

        ids = ["REC-1", "REC-2", "REC-3"]
        for source_id in ids[:limit]:
            file_ref = await ctx.add_bytes(
                source_id, "data.txt", data=f"content-{source_id}".encode()
            )
            yield IngesterRecord(
                source_id=source_id,
                metadata={"organism": "Human", "title": f"Record {source_id}"},
                files=[file_ref],
            )


class FakeIngesterWithConfig:
    name = "configurable-ingester"
    schedule = None
    initial_run = None
    max_file_mb = None

    class RuntimeConfig(BaseModel):
        api_key: str

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config

    async def pull(self, *, ctx, since=None, limit=None, offset=0, session=None):
        from osa.types.ingester import IngesterRecord

        yield IngesterRecord(
            source_id="configured",
            metadata={"key": self.config.api_key if self.config else "none"},
            files=[],
        )


class TestRunIngester:
    def test_collects_records(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=2)
        assert len(result.records) == 2
        assert result.records[0].source_id == "REC-1"
        assert result.records[1].source_id == "REC-2"

    def test_ingester_name(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1)
        assert result.ingester_name == "fake-ingester"

    def test_files_written_to_disk(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1)
        data_file = result.files_dir / "REC-1" / "data.txt"
        assert data_file.exists()
        assert data_file.read_text() == "content-REC-1"

    def test_creates_temp_dir_when_none_provided(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1)
        assert result.files_dir.exists()

    def test_uses_provided_files_dir(self, tmp_path) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1, files_dir=tmp_path)
        assert result.files_dir == tmp_path
        assert (tmp_path / "REC-1" / "data.txt").exists()

    def test_respects_limit(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1)
        assert len(result.records) == 1

    def test_passes_config_to_ingester(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(
            FakeIngesterWithConfig, limit=1, config={"api_key": "secret-123"}
        )
        assert result.records[0].metadata["key"] == "secret-123"

    def test_no_config_instantiates_without_args(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngesterWithConfig, limit=1)
        assert result.records[0].metadata["key"] == "none"

    def test_file_refs_on_records(self) -> None:
        from osa.testing.harness import run_ingester

        result = run_ingester(FakeIngester, limit=1)
        record = result.records[0]
        assert len(record.files) == 1
        assert record.files[0].name == "data.txt"
