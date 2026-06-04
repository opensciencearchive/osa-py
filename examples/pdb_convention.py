"""Example convention: PDB protein structures with validation."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from osa import Field, Record, Reject, Schema, convention, hook


class PDBStructure(Schema):
    __schema_id__ = "pdb-structure"

    pdb_id: str
    title: str
    method: str
    resolution: float | None = Field(default=None, unit="Å")
    deposition_date: date
    molecular_weight: float = Field(unit="kDa")
    chain_count: int


@hook
def validate_structure(record: Record[PDBStructure]) -> None:
    if record.metadata.resolution and record.metadata.resolution > 4.0:
        raise Reject("Resolution too low for reliable analysis")
    if not record.files.glob("*.cif"):
        raise Reject("At least one CIF file is required")


class Pocket(BaseModel):
    pocket_id: int
    score: float
    volume: float


@hook
def find_pockets(record: Record[PDBStructure]) -> list[Pocket]:
    cif = record.files["structure.cif"]
    size_kb = cif.size / 1024
    return [Pocket(pocket_id=0, score=round(size_kb / 100, 2), volume=size_kb)]


convention(
    title="Protein Structures",
    version="1.0.0",
    schema=PDBStructure,
    hooks=[validate_structure, find_pockets],
    files={"accepted_types": [".cif", ".pdb"], "max_count": 5},
)
