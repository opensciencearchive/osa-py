"""Example convention: PDB protein structures with validation and ingestion."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from osa import (
    Field,
    IngesterContext,
    IngesterRecord,
    Record,
    Reject,
    Schema,
    convention,
    hook,
)


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
    cif = record.files.glob("*.cif")[0]
    size_kb = cif.size / 1024
    return [Pocket(pocket_id=0, score=round(size_kb / 100, 2), volume=size_kb)]


RCSB_DATA = "https://data.rcsb.org/rest/v1/core/entry"
RCSB_FILES = "https://files.rcsb.org/download"

PDB_IDS = ["4TOS", "1TIM", "6LU7"]


class PDBIngester:
    name = "pdb-rcsb"
    schedule = None
    initial_run = None
    max_file_mb = 50.0

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        since=None,
        limit=None,
        offset=0,
        session=None,
    ):
        import httpx

        ids = PDB_IDS[offset:]
        if limit is not None:
            ids = ids[:limit]

        async with httpx.AsyncClient() as client:
            for pdb_id in ids:
                resp = await client.get(f"{RCSB_DATA}/{pdb_id}")
                resp.raise_for_status()
                entry = resp.json()

                struct = entry.get("struct", {})
                exptl = entry.get("exptl", [{}])[0]
                cell = entry.get("cell", {})
                diffrn = entry.get("rcsb_entry_info", {})

                resolution = None
                for key in ("ls_d_res_high", "resolution_combined"):
                    val = diffrn.get(key)
                    if val is not None:
                        resolution = (
                            float(val[0]) if isinstance(val, list) else float(val)
                        )
                        break

                dep_date = entry.get("rcsb_accession_info", {}).get(
                    "deposit_date", "1970-01-01"
                )[:10]

                file_ref = await ctx.add_file(
                    pdb_id,
                    "structure.cif",
                    url=f"{RCSB_FILES}/{pdb_id}.cif",
                )

                yield IngesterRecord(
                    source_id=pdb_id,
                    metadata={
                        "pdb_id": pdb_id,
                        "title": struct.get("title", ""),
                        "method": exptl.get("method", ""),
                        "resolution": resolution,
                        "deposition_date": dep_date,
                        "molecular_weight": cell.get("formula_weight", 0.0),
                        "chain_count": diffrn.get("polymer_entity_count_protein", 1),
                    },
                    files=[file_ref],
                )


convention(
    title="Protein Structures",
    version="1.0.0",
    schema=PDBStructure,
    ingester=PDBIngester,
    hooks=[validate_structure, find_pockets],
    files={"accepted_types": [".cif", ".pdb"], "max_count": 5},
)
