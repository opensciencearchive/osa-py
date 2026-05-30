"""Tests for updated convention() with version and ingester support."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from osa.types.record import Record
from osa.types.schema import MetadataSchema


class SampleSchema(MetadataSchema):
    __schema_id__ = "sample-schema-1"

    organism: str


class PocketResult(BaseModel):
    pocket_id: str
    score: float


class TestConventionVersion:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_convention_stores_version(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Test Convention",
            version="1.0.0",
            schema=SampleSchema,
            files={"accepted_types": [".cif"]},
            hooks=[detect],
        )
        assert _conventions[0].version == "1.0.0"

    def test_convention_stores_ingester_cls(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook
        from osa.authoring.ingester import Ingester
        from osa.runtime.ingester_context import IngesterContext
        from osa.types.ingester import IngesterRecord

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        class MyIngester(Ingester):
            name = "test-ingester"

            class RuntimeConfig(BaseModel):
                api_key: str

            async def pull(
                self,
                *,
                ctx: IngesterContext,
                since: datetime | None = None,
                limit: int | None = None,
                offset: int = 0,
                session: dict[str, Any] | None = None,
            ) -> AsyncIterator[IngesterRecord]:
                yield  # type: ignore[misc]  # pragma: no cover

        convention(
            title="Test Convention",
            version="1.0.0",
            schema=SampleSchema,
            ingester=MyIngester,
            files={"accepted_types": [".cif"]},
            hooks=[detect],
        )
        assert _conventions[0].ingester_info is not None
        assert _conventions[0].ingester_info.ingester_cls is MyIngester

    def test_convention_populates_ingester_info(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook
        from osa.authoring.ingester import Ingester
        from osa.runtime.ingester_context import IngesterContext
        from osa.types.ingester import IngesterRecord

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        class MyIngester(Ingester):
            name = "test-ingester"

            class RuntimeConfig(BaseModel):
                api_key: str

            async def pull(
                self,
                *,
                ctx: IngesterContext,
                since: datetime | None = None,
                limit: int | None = None,
                offset: int = 0,
                session: dict[str, Any] | None = None,
            ) -> AsyncIterator[IngesterRecord]:
                yield  # type: ignore[misc]  # pragma: no cover

        convention(
            title="Test Convention",
            version="1.0.0",
            schema=SampleSchema,
            ingester=MyIngester,
            files={"accepted_types": [".cif"]},
            hooks=[detect],
        )
        assert _conventions[0].ingester_info is not None
        assert _conventions[0].ingester_info.name == "test-ingester"
        assert _conventions[0].ingester_info.ingester_cls is MyIngester

    def test_convention_ingester_defaults_to_none(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="No Ingester",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[detect],
        )
        assert _conventions[0].ingester_info is None

    def test_backward_compatible_without_version(self) -> None:
        """version defaults to '0.0.0' if omitted."""
        from osa._registry import _conventions
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="No Version",
            schema=SampleSchema,
            files={},
            hooks=[detect],
        )
        assert _conventions[0].version == "0.0.0"


class TestManifestWithVersion:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_manifest_convention_has_version(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook
        from osa.manifest import generate_manifest

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Test",
            version="2.1.0",
            schema=SampleSchema,
            files={},
            hooks=[detect],
        )
        m = generate_manifest()
        assert m.conventions[0].version == "2.1.0"

    def test_manifest_convention_has_ingester_name(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook
        from osa.authoring.ingester import Ingester
        from osa.manifest import generate_manifest
        from osa.runtime.ingester_context import IngesterContext
        from osa.types.ingester import IngesterRecord

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        class MyIngester(Ingester):
            name = "my-ingester"

            class RuntimeConfig(BaseModel):
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
                yield  # type: ignore[misc]  # pragma: no cover

        convention(
            title="Test",
            version="1.0.0",
            schema=SampleSchema,
            ingester=MyIngester,
            files={},
            hooks=[detect],
        )
        m = generate_manifest()
        assert m.conventions[0].ingester_name == "my-ingester"

    def test_manifest_convention_ingester_name_none_when_no_ingester(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook
        from osa.manifest import generate_manifest

        @hook
        def detect(record: Record[SampleSchema]) -> list[PocketResult]:
            return []

        convention(
            title="Test",
            version="1.0.0",
            schema=SampleSchema,
            files={},
            hooks=[detect],
        )
        m = generate_manifest()
        assert m.conventions[0].ingester_name is None
