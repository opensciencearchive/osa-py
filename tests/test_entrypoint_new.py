"""Tests for the batch hook entrypoint: records.jsonl → features/rejections/errors."""

from __future__ import annotations

import json

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


class TestBatchEntrypoint:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_single_record_writes_features_jsonl(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return [PocketResult(pocket_id="P1", score=0.85)]

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Human", "title": "Test"}}
            )
            + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=detect, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        lines = (output_dir / "features.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["id"] == "rec1"
        assert isinstance(data["features"], list)
        assert data["features"][0]["pocket_id"] == "P1"

    def test_scalar_result_wraps_in_list(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=42)

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Mouse", "title": "Test"}}
            )
            + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=check, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        lines = (output_dir / "features.jsonl").read_text().strip().split("\n")
        data = json.loads(lines[0])
        assert data["id"] == "rec1"
        assert isinstance(data["features"], list)
        assert data["features"][0]["atom_count"] == 42

    def test_reject_writes_to_rejections_jsonl(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            raise Reject("Bad structure file")

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Human", "title": "Test"}}
            )
            + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=check, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        lines = (output_dir / "rejections.jsonl").read_text().strip().split("\n")
        data = json.loads(lines[0])
        assert data["id"] == "rec1"
        assert "Bad structure file" in data["reason"]

    def test_unhandled_exception_writes_to_errors_jsonl(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            raise KeyError("atoms")

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Human", "title": "Test"}}
            )
            + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=check, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        lines = (output_dir / "errors.jsonl").read_text().strip().split("\n")
        data = json.loads(lines[0])
        assert data["id"] == "rec1"
        assert "atoms" in data["error"]
        assert data["retryable"] is False

    def test_multiple_records_processed_independently(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            if record.metadata.organism == "Bad":
                raise Reject("Invalid organism")
            if record.metadata.organism == "Error":
                raise RuntimeError("boom")
            return QualityResult(atom_count=100)

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        records = [
            {"id": "pass1", "metadata": {"organism": "Human", "title": "A"}},
            {"id": "reject1", "metadata": {"organism": "Bad", "title": "B"}},
            {"id": "error1", "metadata": {"organism": "Error", "title": "C"}},
            {"id": "pass2", "metadata": {"organism": "Mouse", "title": "D"}},
        ]
        (input_dir / "records.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=check, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        features = [
            json.loads(raw)
            for raw in (output_dir / "features.jsonl").read_text().strip().split("\n")
        ]
        rejections = [
            json.loads(raw)
            for raw in (output_dir / "rejections.jsonl").read_text().strip().split("\n")
        ]
        errors = [
            json.loads(raw)
            for raw in (output_dir / "errors.jsonl").read_text().strip().split("\n")
        ]

        assert len(features) == 2
        assert features[0]["id"] == "pass1"
        assert features[1]["id"] == "pass2"

        assert len(rejections) == 1
        assert rejections[0]["id"] == "reject1"

        assert len(errors) == 1
        assert errors[0]["id"] == "error1"

    def test_per_record_files(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        files_dir = tmp_path / "files"
        input_dir.mkdir()

        # Create per-record file directories
        (files_dir / "rec1").mkdir(parents=True)
        (files_dir / "rec1" / "test.cif").write_text("ATOM 1")

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Human", "title": "Test"}}
            )
            + "\n"
        )

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            cif_files = record.files.glob("*.cif")
            assert len(cif_files) == 1
            return [PocketResult(pocket_id="P1", score=0.9)]

        exit_code = run_hook_entrypoint(
            hook_fn=detect,
            input_dir=input_dir,
            output_dir=output_dir,
            files_dir=files_dir,
        )
        assert exit_code == 0

    def test_missing_records_jsonl_returns_1(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        exit_code = run_hook_entrypoint(
            hook_fn=detect, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 1

    def test_record_id_populates_record(self, tmp_path) -> None:
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        captured = {}

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            captured["id"] = record.id
            captured["organism"] = record.metadata.organism
            return [PocketResult(pocket_id="P1", score=0.85)]

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {
                    "id": "my-record-id",
                    "metadata": {"organism": "Human", "title": "Test"},
                }
            )
            + "\n"
        )

        run_hook_entrypoint(hook_fn=detect, input_dir=input_dir, output_dir=output_dir)
        assert captured["id"] == "my-record-id"
        assert captured["organism"] == "Human"

    def test_empty_output_files_created(self, tmp_path) -> None:
        """All three output files are created even if empty."""
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return [PocketResult(pocket_id="P1", score=0.85)]

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        (input_dir / "records.jsonl").write_text(
            json.dumps(
                {"id": "rec1", "metadata": {"organism": "Human", "title": "Test"}}
            )
            + "\n"
        )

        run_hook_entrypoint(hook_fn=detect, input_dir=input_dir, output_dir=output_dir)

        assert (output_dir / "features.jsonl").exists()
        assert (output_dir / "rejections.jsonl").exists()
        assert (output_dir / "errors.jsonl").exists()

    def test_validation_error_does_not_kill_batch(self, tmp_path) -> None:
        """A ValidationError on record N should go to errors.jsonl, not kill the loop."""
        from osa.authoring.hook import hook
        from osa.runtime.entrypoint import run_hook_entrypoint

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100)

        input_dir = tmp_path / "in"
        output_dir = tmp_path / "out"
        input_dir.mkdir()

        # Record 2 is missing required "organism" field → ValidationError
        records = [
            {"id": "good1", "metadata": {"organism": "Human", "title": "A"}},
            {"id": "bad", "metadata": {"title": "B"}},
            {"id": "good2", "metadata": {"organism": "Mouse", "title": "C"}},
        ]
        (input_dir / "records.jsonl").write_text(
            "\n".join(json.dumps(r) for r in records) + "\n"
        )

        exit_code = run_hook_entrypoint(
            hook_fn=check, input_dir=input_dir, output_dir=output_dir
        )
        assert exit_code == 0

        features = [
            json.loads(raw)
            for raw in (output_dir / "features.jsonl").read_text().strip().split("\n")
        ]
        errors = [
            json.loads(raw)
            for raw in (output_dir / "errors.jsonl").read_text().strip().split("\n")
        ]

        # Both good records should pass through
        assert len(features) == 2
        assert features[0]["id"] == "good1"
        assert features[1]["id"] == "good2"

        # The bad record should be in errors
        assert len(errors) == 1
        assert errors[0]["id"] == "bad"
