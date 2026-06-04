<img src="https://opensciencearchive.org/osa_logo.svg" alt="OSA" width="64" />

# OSA Python SDK

The developer toolkit for the [Open Science Archive](https://github.com/opensciencearchive/server) — define metadata schemas, write validation hooks, build ingesters, and deploy conventions.

[![License](https://img.shields.io/badge/license-Apache%202.0-blue?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-≥3.13-blue?style=flat-square)](https://python.org)

> **Pre-release** — APIs will change without notice.

---

## Install

```bash
pip install osa-py
```

## Quickstart

A convention defines what data your archive accepts. Here's a stripped-down example that archives protein structures from the RCSB PDB and detects binding pockets:

```python
from datetime import date
from pydantic import BaseModel
from osa import Schema, Field, Record, Reject, hook, convention, Ingester

# 1. Define the metadata schema
class PDBStructure(Schema, id="pdb-structure"):
    pdb_id: str
    title: str
    organism: str
    method: str
    resolution: float | None = Field(default=None, unit="Å")
    deposition_date: date
    molecular_weight: float = Field(unit="kDa")
    chain_count: int

# 2. Define hook output
class Pocket(BaseModel):
    pocket_id: int
    score: float
    volume: float
    center_x: float
    center_y: float
    center_z: float

# 3. Write a hook
@hook
def pockets(record: Record[PDBStructure]) -> list[Pocket]:
    """Detect binding pockets in a protein structure."""
    import pocketeer as pt

    cif = record.files["structure.cif"]
    atoms = pt.load_structure(str(cif.path))
    found = pt.find_pockets(atoms)

    return [
        Pocket(
            pocket_id=i,
            score=p.score,
            volume=p.volume,
            center_x=float(p.centroid[0]),
            center_y=float(p.centroid[1]),
            center_z=float(p.centroid[2]),
        )
        for i, p in enumerate(found)
    ]

# 4. Register the convention
convention(
    title="RCSB PDB Protein Structures",
    version="1.0.0",
    schema=PDBStructure,
    hooks=[pockets],
    files={"accepted_types": [".cif", ".pdb"], "max_count": 5},
)
```

Register the convention as a setuptools entry point in `pyproject.toml`:

```toml
[project.entry-points."osa.conventions"]
pockets = "pockets"
```

## Testing

Test hooks in-process without Docker:

```python
from osa.testing import run_hook

result = run_hook(
    pockets,
    meta={
        "pdb_id": "4TOS",
        "title": "Thermolysin",
        "organism": "Bacillus thermoproteolyticus",
        "method": "X-RAY DIFFRACTION",
        "resolution": 1.65,
        "deposition_date": "1982-06-14",
        "molecular_weight": 34.6,
        "chain_count": 1,
    },
    files_dir="tests/fixtures/4TOS",
)
```

## Local development

Run a full OSA stack locally with Docker:

```bash
osa init my-archive
cd my-archive
osa start
```

This scaffolds a project directory with `osa.yaml`, `.env`, and a Docker Compose stack (Postgres, OSA server, docker-socket-proxy). Authentication is handled automatically — `osa start` mints a dev JWT so `osa deploy` and `osa ingestion start` work immediately.

To build the server from a local checkout instead of pulling the published image:

```bash
osa start --source ../path/to/server
```

## Deploy

Deploy conventions to a running archive:

```bash
osa deploy
```

This builds OCI images for your hooks and ingesters, pushes them to the server's registry, and registers the convention.

## CLI

### Local instance

| Command | Description |
|---|---|
| `osa init [dir]` | Scaffold a new project (osa.yaml, .env, .gitignore) |
| `osa start` | Start the local OSA stack |
| `osa stop` | Stop the local stack |
| `osa logs [-f] [service]` | View container logs |
| `osa status` | Show running containers |

### Convention workflow

| Command | Description |
|---|---|
| `osa deploy` | Build OCI images and register conventions |
| `osa meta` | Print the convention manifest as JSON |
| `osa ingestion start` | Trigger an ingestion run |

### Authentication

| Command | Description |
|---|---|
| `osa login` | Authenticate via ORCID device flow |
| `osa logout` | Remove stored credentials |
| `osa link --server <url>` | Link project to a remote archive |

## Concepts

**Schema** — a Pydantic model defining typed metadata fields. Each field can carry units and constraints. The schema is the contract between depositors, hooks, and the archive.

**Hook** — a pure function decorated with `@hook` that receives a `Record[T]` and returns structured results. Hooks run as OCI containers — the SDK builds the image, the server orchestrates execution.

**Convention** — a bundle of a schema, hooks, file requirements, and an optional ingester. Conventions are the unit of deployment.

**Ingester** — an async generator that pulls records from external systems (APIs, databases, file servers) into the archive on a schedule.

**Record\[T\]** — generic container binding a schema type `T` to its metadata, files, and SRN (Scientific Resource Name).

## License

[Apache 2.0](LICENSE)
