"""Tests for SDK Ingester types (IngesterFileRef, IngesterRecord)."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError


class TestIngesterFileRef:
    def test_creates_with_name_and_relative_path(self) -> None:
        from osa.types.ingester import IngesterFileRef

        sf = IngesterFileRef(
            name="structure.cif", relative_path="4HHB/structure.cif", size_mb=12.3
        )
        assert sf.name == "structure.cif"
        assert sf.relative_path == "4HHB/structure.cif"
        assert sf.size_mb == 12.3

    def test_is_frozen(self) -> None:
        from osa.types.ingester import IngesterFileRef

        sf = IngesterFileRef(
            name="structure.cif", relative_path="4HHB/structure.cif", size_mb=1.0
        )
        with pytest.raises(ValidationError):
            sf.name = "other.cif"  # type: ignore[misc]

    def test_size_mb_required(self) -> None:
        from osa.types.ingester import IngesterFileRef

        sf = IngesterFileRef(name="f.cif", relative_path="x/f.cif", size_mb=38.5)
        assert sf.size_mb == 38.5

    def test_size_mb_serializes_correctly(self) -> None:
        from osa.types.ingester import IngesterFileRef

        sf = IngesterFileRef(name="f.cif", relative_path="x/f.cif", size_mb=38.5)
        data = sf.model_dump()
        assert data["size_mb"] == 38.5

    def test_size_mb_missing_raises(self) -> None:
        from osa.types.ingester import IngesterFileRef

        with pytest.raises(ValidationError):
            IngesterFileRef(name="f.cif", relative_path="x/f.cif")


class TestIngesterRecord:
    def test_creates_with_required_fields(self) -> None:
        from osa.types.ingester import IngesterRecord

        sr = IngesterRecord(
            source_id="4HHB",
            metadata={"pdb_id": "4HHB", "title": "Deoxy Human Hemoglobin"},
        )
        assert sr.source_id == "4HHB"
        assert sr.metadata["pdb_id"] == "4HHB"
        assert sr.files == []
        assert sr.fetched_at is None

    def test_creates_with_files(self) -> None:
        from osa.types.ingester import IngesterFileRef, IngesterRecord

        sr = IngesterRecord(
            source_id="4HHB",
            metadata={"pdb_id": "4HHB"},
            files=[
                IngesterFileRef(
                    name="structure.cif",
                    relative_path="4HHB/structure.cif",
                    size_mb=10.5,
                ),
                IngesterFileRef(
                    name="structure.pdb",
                    relative_path="4HHB/structure.pdb",
                    size_mb=8.2,
                ),
            ],
        )
        assert len(sr.files) == 2
        assert sr.files[0].name == "structure.cif"

    def test_creates_with_fetched_at(self) -> None:
        from osa.types.ingester import IngesterRecord

        now = datetime(2025, 6, 15, 12, 0, 0)
        sr = IngesterRecord(source_id="4HHB", metadata={}, fetched_at=now)
        assert sr.fetched_at == now

    def test_is_frozen(self) -> None:
        from osa.types.ingester import IngesterRecord

        sr = IngesterRecord(source_id="4HHB", metadata={})
        with pytest.raises(ValidationError):
            sr.source_id = "other"  # type: ignore[misc]
