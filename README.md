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

A convention defines what data your archive accepts. Here's an example that archives protein structures and runs analysis on the deposited files:

```python
from datetime import date
from pydantic import BaseModel
from osa import Schema, Field, Record, Reject, hook, convention

# 1. Define the metadata schema
class PDBStructure(Schema):
    __schema_id__ = "pdb-structure"

    pdb_id: str
    title: str
    method: str
    resolution: float | None = Field(default=None, unit="Å")
    deposition_date: date
    molecular_weight: float = Field(unit="kDa")
    chain_count: int

# 2. Validate incoming records
@hook
def validate_structure(record: Record[PDBStructure]) -> None:
    if record.metadata.resolution and record.metadata.resolution > 4.0:
        raise Reject("Resolution too low for reliable analysis")
    if not record.files.glob("*.cif"):
        raise Reject("At least one CIF file is required")

# 3. Extract features from the data
class Pocket(BaseModel):
    pocket_id: int
    score: float
    volume: float

@hook
def find_pockets(record: Record[PDBStructure]) -> list[Pocket]:
    cif = record.files["structure.cif"]
    size_kb = cif.size / 1024
    return [Pocket(pocket_id=0, score=round(size_kb / 100, 2), volume=size_kb)]

# 4. Register the convention
convention(
    title="Protein Structures",
    version="1.0.0",
    schema=PDBStructure,
    hooks=[validate_structure, find_pockets],
    files={"accepted_types": [".cif", ".pdb"], "max_count": 5},
)
```

Register the convention as a setuptools entry point in `pyproject.toml`:

```toml
[project.entry-points."osa.conventions"]
my_convention = "my_package"
```

## Testing

Test hooks in-process without Docker:

```python
from pathlib import Path
from osa import Reject
from osa.testing import run_hook

meta = {
    "pdb_id": "4TOS",
    "title": "Crystal structure of Tankyrase 1 with 355",
    "method": "X-RAY DIFFRACTION",
    "resolution": 1.8,
    "deposition_date": "2014-06-06",
    "molecular_weight": 54.44,
    "chain_count": 1,
}

# Passes validation
run_hook(validate_structure, meta=meta, files=Path("fixtures/4TOS"))

# Raises Reject for low resolution
run_hook(validate_structure, meta={**meta, "resolution": 5.0}, files=Path("fixtures/4TOS"))
# => Reject: Resolution too low for reliable analysis

# Returns extracted features
pockets = run_hook(find_pockets, meta=meta, files=Path("fixtures/4TOS"))
assert len(pockets) > 0
```

## Local development

Run a full OSA stack locally with Docker:

```bash
osa init my-archive
cd my-archive
osa start
```

This scaffolds a project directory with `osa.yaml`, `.env`, and a Docker Compose stack (Postgres, OSA server, docker-socket-proxy). Authentication is handled automatically — `osa start` mints a dev JWT so `osa deploy` and `osa ingestion start` work immediately.

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
