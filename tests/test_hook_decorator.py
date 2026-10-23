"""Tests for the unified @hook decorator: registration, type introspection, cardinality detection."""

from __future__ import annotations

from typing import List, Optional  # noqa: UP035 — the legacy spellings are under test

from pydantic import BaseModel

from osa.types.record import Record
from osa.types.schema import MetadataSchema


class SampleSchema(MetadataSchema):
    __schema_id__ = "sample-schema-1"

    organism: str
    resolution: float | None = None


class PocketResult(BaseModel):
    pocket_id: str
    score: float


class QualityResult(BaseModel):
    atom_count: int
    completeness: float


class TestHookRegistration:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_hook_registers_in_global_registry(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect_pockets(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert len(_hooks) == 1

    def test_hook_preserves_function_callable(self) -> None:
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert callable(detect)

    def test_hook_preserves_function_name(self) -> None:
        from osa.authoring.hook import hook

        @hook
        def detect_pockets(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert detect_pockets.__name__ == "detect_pockets"

    def test_multiple_hooks_register(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        @hook
        def quality(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100, completeness=0.9)

        assert len(_hooks) == 2


class TestHookTypeIntrospection:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_extracts_schema_type(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert _hooks[0].schema_type is SampleSchema

    def test_extracts_output_type_from_list(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert _hooks[0].output_type is PocketResult

    def test_extracts_output_type_from_scalar(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100, completeness=0.9)

        assert _hooks[0].output_type is QualityResult

    def test_extracts_name(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect_pockets(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert _hooks[0].name == "detect_pockets"


class TestHookCardinality:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_list_return_is_many(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert _hooks[0].cardinality == "many"

    def test_scalar_return_is_one(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult:
            return QualityResult(atom_count=100, completeness=0.9)

        assert _hooks[0].cardinality == "one"


class TestHookDependencies:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_no_dependencies_for_simple_hook(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        assert _hooks[0].dependencies == {}

    def test_extracts_dependencies(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(
            record: Record[SampleSchema],
            quality: QualityResult,
        ) -> list[PocketResult]:
            return []

        assert "quality" in _hooks[0].dependencies
        assert _hooks[0].dependencies["quality"] is QualityResult


class TestHookRegistrySchemaType:
    """Verify @hook stores schema_type in the registry."""

    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_schema_type_available_via_registry(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        info = next(h for h in _hooks if h.fn is detect)
        assert info.schema_type is SampleSchema


class TestHookOptionalReturn:
    """``-> T | None`` is the natural annotation for a hook that sometimes has
    nothing to contribute (#20). The registry must see through the ``None``
    so the feature table keeps its columns."""

    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_pipe_none_unwraps_to_model(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def check(record: Record[SampleSchema]) -> QualityResult | None:
            return None

        assert _hooks[0].output_type is QualityResult
        assert _hooks[0].cardinality == "one"

    def test_optional_unwraps_to_model(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def check(record: Record[SampleSchema]) -> Optional[QualityResult]:  # noqa: UP045
            return None

        assert _hooks[0].output_type is QualityResult
        assert _hooks[0].cardinality == "one"

    def test_optional_list_unwraps_to_many(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult] | None:
            return None

        assert _hooks[0].output_type is PocketResult
        assert _hooks[0].cardinality == "many"

    def test_none_return_is_a_validator(self) -> None:
        from osa._registry import _hooks
        from osa.authoring.hook import hook

        @hook
        def validate(record: Record[SampleSchema]) -> None:
            return None

        assert _hooks[0].output_type is None
        assert _hooks[0].cardinality == "one"


class TestHookRejectsUnintrospectableReturn:
    """A hook whose output cannot become feature columns is a bug at the
    moment it is written, not after deploy (#20)."""

    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_multi_member_union_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match="either_or"):

            @hook
            def either_or(
                record: Record[SampleSchema],
            ) -> PocketResult | QualityResult:
                return PocketResult(pocket_id="a", score=1.0)

    def test_plain_dict_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match=r"raw_dict.*dict"):

            @hook
            def raw_dict(record: Record[SampleSchema]) -> dict:
                return {}

    def test_untyped_list_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match="bare_list"):

            @hook
            def bare_list(record: Record[SampleSchema]) -> list:
                return []

    def test_typing_list_alias_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match="alias_list"):

            @hook
            def alias_list(record: Record[SampleSchema]) -> List:  # noqa: UP006
                return []

    def test_optional_typing_list_alias_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match="optional_alias_list"):

            @hook
            def optional_alias_list(
                record: Record[SampleSchema],
            ) -> Optional[List]:  # noqa: UP006, UP045
                return None

    def test_missing_return_annotation_is_rejected(self) -> None:
        import pytest

        from osa.authoring.hook import hook

        with pytest.raises(TypeError, match="unannotated"):

            @hook
            def unannotated(record: Record[SampleSchema]):
                return None
