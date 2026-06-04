"""Test the PDB convention: unit tests with run_hook, integration with run_test."""

from __future__ import annotations

import pytest

from osa import Reject
from osa.testing import run_hook, run_ingester, run_test

from pdb_convention import PDBIngester, validate_structure


# --- Unit tests: test individual hooks with synthetic data ---


def test_valid_structure_passes(tmp_path):
    (tmp_path / "structure.cif").write_text("data_test")
    run_hook(
        validate_structure,
        meta={
            "pdb_id": "TEST",
            "title": "Test structure",
            "method": "X-RAY DIFFRACTION",
            "resolution": 1.8,
            "deposition_date": "2024-01-01",
            "molecular_weight": 50.0,
            "chain_count": 1,
        },
        files=tmp_path,
    )


def test_low_resolution_rejected(tmp_path):
    (tmp_path / "structure.cif").write_text("data_test")
    with pytest.raises(Reject, match="Resolution too low"):
        run_hook(
            validate_structure,
            meta={
                "pdb_id": "TEST",
                "title": "Test structure",
                "method": "X-RAY DIFFRACTION",
                "resolution": 5.0,
                "deposition_date": "2024-01-01",
                "molecular_weight": 50.0,
                "chain_count": 1,
            },
            files=tmp_path,
        )


def test_missing_cif_rejected(tmp_path):
    with pytest.raises(Reject, match="CIF file"):
        run_hook(
            validate_structure,
            meta={
                "pdb_id": "TEST",
                "title": "Test structure",
                "method": "X-RAY DIFFRACTION",
                "resolution": 1.8,
                "deposition_date": "2024-01-01",
                "molecular_weight": 50.0,
                "chain_count": 1,
            },
            files=tmp_path,
        )


# --- Integration: test the ingester pulls real data ---


@pytest.mark.network
def test_ingester_fetches_records():
    result = run_ingester(PDBIngester, limit=1)
    assert len(result.records) == 1
    assert result.records[0].source_id == "4TOS"
    assert (result.files_dir / "4TOS" / "structure.cif").exists()


# --- End-to-end: test the full convention pipeline ---


@pytest.mark.network
def test_full_convention_pipeline():
    from osa._registry import _conventions

    conv = next(c for c in _conventions if c.title == "Protein Structures")
    result = run_test(convention_info=conv, limit=1)

    assert len(result.records) == 1
    record = result.records[0]
    assert record.accepted
    assert record.hooks[0].hook_name == "validate_structure"
    assert record.hooks[0].status == "passed"
    assert record.hooks[1].hook_name == "find_pockets"
    assert record.hooks[1].status == "passed"
    assert len(record.hooks[1].result) > 0
