"""Tests for convention() registration function."""

from __future__ import annotations

from pydantic import BaseModel

from osa.types.record import Record
from osa.types.schema import MetadataSchema


class SampleSchema(MetadataSchema):
    __schema_id__ = "sample-schema-1"

    organism: str


class PocketResult(BaseModel):
    pocket_id: str
    score: float


class QualityResult(BaseModel):
    atom_count: int


def _test_docs_kwargs() -> dict:
    """Minimal valid docs for convention() — mandatory since #151."""
    from osa import Example

    return {
        "purpose": "Test data for unit tests.",
        "example_questions": ["q1?", "q2?", "q3?"],
        "examples": [Example(question="q1?", query="GET /x", interpretation="means x")],
    }


class TestConventionRegistration:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_convention_records_in_registry(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Test Convention",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={"extensions": [".cif"], "min": 1, "max": 10},
            hooks=[detect],
            **_test_docs_kwargs(),
        )
        assert len(_conventions) == 1

    def test_convention_stores_title(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Protein Structure",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={"extensions": [".cif"]},
            hooks=[detect],
            **_test_docs_kwargs(),
        )
        assert _conventions[0].title == "Protein Structure"

    def test_convention_stores_schema_type(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[detect],
            **_test_docs_kwargs(),
        )
        assert _conventions[0].schema_type is SampleSchema

    def test_convention_stores_file_requirements(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        files = {"extensions": [".cif", ".pdb"], "min": 1, "max": 10}
        convention(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files=files,
            hooks=[detect],
            **_test_docs_kwargs(),
        )
        assert _conventions[0].file_requirements == files

    def test_convention_stores_hook_references(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100)

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Full",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[check, detect],
            **_test_docs_kwargs(),
        )
        assert _conventions[0].hooks == [check, detect]

    def test_multiple_conventions(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100)

        convention(
            title="Simple",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[detect],
            **_test_docs_kwargs(),
        )
        convention(
            title="Detailed",
            description="A test convention",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[check, detect],
            **_test_docs_kwargs(),
        )
        assert len(_conventions) == 2
        assert _conventions[0].title == "Simple"
        assert _conventions[1].title == "Detailed"
