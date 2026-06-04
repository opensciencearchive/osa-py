"""Run the example hooks against a real PDB structure."""

from __future__ import annotations

from pathlib import Path

import pytest

from osa import Reject
from osa.testing import run_hook

from pdb_convention import find_pockets, validate_structure

META = {
    "pdb_id": "4TOS",
    "title": "Crystal structure of Tankyrase 1 with 355",
    "method": "X-RAY DIFFRACTION",
    "resolution": 1.8,
    "deposition_date": "2014-06-06",
    "molecular_weight": 54.44,
    "chain_count": 1,
}

FIXTURES = Path(__file__).parent / "fixtures" / "4TOS"


def test_valid_structure_passes():
    run_hook(validate_structure, meta=META, files=FIXTURES)


def test_low_resolution_rejected():
    bad = {**META, "resolution": 5.0}
    with pytest.raises(Reject, match="Resolution too low"):
        run_hook(validate_structure, meta=bad, files=FIXTURES)


def test_find_pockets_returns_results():
    result = run_hook(find_pockets, meta=META, files=FIXTURES)
    assert len(result) > 0
    assert result[0].pocket_id == 0
    assert result[0].volume > 0


if __name__ == "__main__":
    from osa import Reject  # noqa: F811

    run_hook(validate_structure, meta=META, files=FIXTURES)
    print("PASS: valid structure accepted")

    try:
        run_hook(validate_structure, meta={**META, "resolution": 5.0}, files=FIXTURES)
        assert False, "Should have rejected"
    except Reject:
        print("PASS: low resolution rejected")

    result = run_hook(find_pockets, meta=META, files=FIXTURES)
    assert len(result) > 0
    print(f"PASS: found {len(result)} pocket(s)")
