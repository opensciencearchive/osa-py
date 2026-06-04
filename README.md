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

Define a schema, write a hook, register a convention:

```python
from osa import Schema, Field, Record, Reject, hook, convention

class Crystal(Schema, id="crystal-structure"):
    pdb_id: str
    resolution: float = Field(unit="Å")
    method: str

@hook
def resolution_check(record: Record[Crystal]) -> None:
    if record.metadata.resolution > 3.5:
        raise Reject("Resolution too low for inclusion")

convention(
    title="Crystal Structures",
    schema=Crystal,
    hooks=[resolution_check],
    files={"extensions": [".cif"], "min_count": 1},
)
```

## Testing

Test hooks in-process without Docker:

```python
from osa.testing import run_hook

run_hook(resolution_check, meta={"pdb_id": "1ABC", "resolution": 2.1, "method": "X-ray"})
```

## Deploy

```bash
osa link --server https://my-archive.org
osa login
osa deploy
```

## CLI reference

| Command | Description |
|---|---|
| `osa link --server <url>` | Link project to an archive server |
| `osa login` | Authenticate via device flow |
| `osa logout` | Remove stored credentials |
| `osa deploy` | Build OCI images and register conventions |
| `osa meta` | Print the convention manifest |
| `osa ingestion start` | Trigger an ingestion run |

## Concepts

**Schema** — a Pydantic model defining typed metadata fields for a convention.

**Hook** — a pure function decorated with `@hook` that receives a `Record[T]` and returns structured results. Hooks run as OCI containers with a filesystem I/O contract.

**Convention** — a bundle of a schema, hooks, file requirements, and an optional ingester.

**Ingester** — an async generator that pulls records from external systems into the archive on a schedule.

**Record\[T\]** — generic container binding a schema type to its metadata, files, and SRN.

## Project structure

```
osa/
├── __init__.py              # Public API
├── authoring/               # @hook, convention(), Reject, Ingester
├── types/                   # Schema, Record, Field, File
├── runtime/                 # OCI entrypoints (osa-run-hook, osa-run-ingester)
├── testing/                 # run_hook() test harness
└── cli/                     # osa command (login, deploy, link, ...)
```

## License

[Apache 2.0](LICENSE)
