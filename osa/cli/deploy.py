"""OSA deploy CLI: build hook/ingester images and register conventions with the server."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from osa._registry import ConventionInfo, HookInfo, IngesterInfo, _conventions, _hooks
from osa.cli.proc import run_streamed, tail
from osa.cli.ui import UI, Task
from osa.manifest import generate_columns


class DeployError(RuntimeError):
    """Deploy failure with optional captured output and remediation hint."""

    def __init__(
        self, message: str, *, cause: str | None = None, hint: str | None = None
    ) -> None:
        super().__init__(message)
        self.cause = cause
        self.hint = hint


def _short_digest(digest: str) -> str:
    return digest.removeprefix("sha256:")[:12]


def _read_python_version(project_dir: Path) -> str:
    """Read requires-python from pyproject.toml, default to 3.13."""
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {project_dir}")
    content = pyproject_path.read_text()
    match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', content)
    return match.group(1) if match else "3.13"


def _find_sdk_path(project_dir: Path) -> Path | None:
    """Resolve a local OSA SDK path from ``[tool.uv.sources]`` in pyproject.toml.

    Honours an ``osa-py = { path = "..." }`` source (as written by
    ``uv add path/to/osa-py``) so that `osa deploy` bakes a filesystem WIP SDK
    into the built images instead of pulling ``osa-py`` from PyPI.
    """
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return None

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    source = data.get("tool", {}).get("uv", {}).get("sources", {}).get("osa-py")
    if not isinstance(source, dict):
        return None
    path = source.get("path")
    if not isinstance(path, str):
        return None

    sdk_path = (project_dir / path).resolve()
    return sdk_path if sdk_path.exists() else None


def generate_hook_dockerfile(project_dir: Path) -> str:
    """Generate a Dockerfile for an OCI hook container."""
    python_version = _read_python_version(project_dir)
    sdk_path = _find_sdk_path(project_dir)

    if sdk_path:
        return f"""\
# syntax=docker/dockerfile:1
FROM python:{python_version}-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY .osa-sdk /app/.osa-sdk
RUN --mount=type=cache,target=/root/.cache/pip pip install /app/.osa-sdk
COPY pyproject.toml README.md* .
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .
ENTRYPOINT ["osa-run-hook"]
"""

    return f"""\
# syntax=docker/dockerfile:1
FROM python:{python_version}-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md* .
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .
ENTRYPOINT ["osa-run-hook"]
"""


def generate_ingester_dockerfile(project_dir: Path) -> str:
    """Generate a Dockerfile for an OCI ingester container."""
    python_version = _read_python_version(project_dir)
    sdk_path = _find_sdk_path(project_dir)

    if sdk_path:
        return f"""\
# syntax=docker/dockerfile:1
FROM python:{python_version}-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY .osa-sdk /app/.osa-sdk
RUN --mount=type=cache,target=/root/.cache/pip pip install /app/.osa-sdk
COPY pyproject.toml README.md* .
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .
ENTRYPOINT ["osa-run-ingester"]
"""

    return f"""\
# syntax=docker/dockerfile:1
FROM python:{python_version}-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md* .
RUN --mount=type=cache,target=/root/.cache/pip pip install .
COPY . .
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .
ENTRYPOINT ["osa-run-ingester"]
"""


def _stage_sdk(project_dir: Path) -> Path | None:
    """Copy the local SDK into the build context. Returns the staged path or None."""
    sdk_path = _find_sdk_path(project_dir)
    if sdk_path is None:
        return None
    staged = project_dir / ".osa-sdk"
    if staged.exists():
        shutil.rmtree(staged)
    shutil.copytree(
        sdk_path,
        staged,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".venv",
            "*.egg-info",
        ),
    )
    return staged


def _build_image(
    name: str,
    dockerfile_content: str,
    project_dir: Path,
    tag_prefix: str,
    registry: str | None = None,
    *,
    task: Task,
) -> tuple[str, str]:
    """Build a Docker image, optionally push to a registry.

    Returns (image_ref, digest) — image_ref is the registry tag if pushed,
    otherwise the local tag.
    """
    dockerfile_path = project_dir / f".osa-Dockerfile.{name}"
    dockerfile_path.write_text(dockerfile_content)
    staged_sdk = _stage_sdk(project_dir)

    tag = (
        f"{registry.rstrip('/')}/{name}:latest"
        if registry
        else f"{tag_prefix}/{name}:latest"
    )

    try:
        task.detail("building")
        build = run_streamed(
            [
                "docker",
                "build",
                "--platform",
                "linux/amd64",
                "-f",
                str(dockerfile_path),
                "-t",
                tag,
                str(project_dir),
            ],
            task=task,
        )
        if build.returncode != 0:
            raise DeployError(
                f"Docker build failed for {name}",
                cause=tail(build.output, 30),
                hint="Re-run with --verbose for full build output",
            )

        # Get the local image ID
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Id}}", tag],
            check=True,
            capture_output=True,
            text=True,
        )
        local_id = result.stdout.strip()

        if registry:
            # Check if this image was already pushed (Docker keeps RepoDigests)
            result = subprocess.run(
                ["docker", "inspect", "--format", "{{json .RepoDigests}}", tag],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_digests = json.loads(result.stdout.strip() or "null")
            if repo_digests:
                digest = repo_digests[0].split("@", 1)[1]
                task.done(detail=f"{_short_digest(digest)} (unchanged)")
                return tag, digest

            task.detail("pushing")
            push = run_streamed(["docker", "push", tag], task=task)
            if push.returncode != 0:
                raise DeployError(
                    f"Docker push failed for {tag}",
                    cause=tail(push.output, 30),
                    hint="Check registry access (docker login) and OSA_REGISTRY",
                )

            result = subprocess.run(
                ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", tag],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_digest = result.stdout.strip()
            digest = repo_digest.split("@", 1)[1]

            task.done(detail=_short_digest(digest))
            return tag, digest

        task.done(detail=_short_digest(local_id))
        return tag, local_id
    finally:
        dockerfile_path.unlink(missing_ok=True)
        if staged_sdk and staged_sdk.exists():
            shutil.rmtree(staged_sdk)


def _build_hook_image(
    hook: HookInfo,
    project_dir: Path,
    tag_prefix: str,
    registry: str | None = None,
    *,
    task: Task,
) -> tuple[str, str]:
    """Build a Docker image for a hook and return (image_tag, digest)."""
    dockerfile_content = generate_hook_dockerfile(project_dir)
    return _build_image(
        hook.name, dockerfile_content, project_dir, tag_prefix, registry, task=task
    )


def _build_ingester_image(
    ingester: IngesterInfo,
    project_dir: Path,
    tag_prefix: str,
    registry: str | None = None,
    *,
    task: Task,
) -> tuple[str, str]:
    """Build a Docker image for an ingester and return (image_tag, digest)."""
    dockerfile_content = generate_ingester_dockerfile(project_dir)
    return _build_image(
        ingester.name,
        dockerfile_content,
        project_dir,
        f"{tag_prefix}-ingesters",
        registry,
        task=task,
    )


def _resolve_source_ref(project_dir: Path) -> str:
    """Return a reproducibility anchor 'git:<short-sha>' for the project.

    Falls back to 'git:unknown' when no git revision is available (not a
    repository, or no commits yet).
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "git:unknown"
    sha = result.stdout.strip()
    if result.returncode != 0 or not sha:
        return "git:unknown"
    return f"git:{sha}"


def _hook_to_definition(
    hook: HookInfo,
    image: str,
    digest: str,
    source_ref: str,
) -> dict[str, Any]:
    """Build a HookDefinition dict from a HookInfo + image details."""
    columns: list[dict[str, Any]] = []
    if (
        hook.output_type is not None
        and isinstance(hook.output_type, type)
        and issubclass(hook.output_type, BaseModel)
    ):
        columns = [c.model_dump() for c in generate_columns(hook.output_type)]

    return {
        "name": hook.name,
        "feature": {
            "kind": "table",
            "cardinality": hook.cardinality,
            "columns": columns,
        },
        "release": {
            "image": image,
            "digest": digest,
            "config": {},
            "limits": hook.limits.model_dump(),
            "source_ref": source_ref,
        },
    }


_MIN_DISTINCT_TRIGGER_QUESTIONS = 3


def _docs_gaps(conv: ConventionInfo) -> list[str]:
    """Missing-documentation gaps for one convention (mirror of the server rule)."""
    gaps: list[str] = []
    if not conv.purpose.strip():
        gaps.append("purpose (must be non-empty)")
    distinct = {q.strip() for q in conv.example_questions if q.strip()}
    distinct |= {e.question.strip() for e in conv.examples if e.question.strip()}
    if len(distinct) < _MIN_DISTINCT_TRIGGER_QUESTIONS:
        gaps.append(
            f"trigger questions (need ≥ {_MIN_DISTINCT_TRIGGER_QUESTIONS} distinct "
            f"across example_questions + worked examples, got {len(distinct)})"
        )
    if not conv.examples:
        gaps.append(f"examples (need ≥ 1 Example, got {len(conv.examples)})")
    return gaps


def _check_docs_gate(conventions: list[ConventionInfo]) -> None:
    """Pre-flight mirror of the server's mandatory-docs gate (#151).

    Fails before any image build/push or network call, naming each gap. The
    node's 422 is the source of truth; this is fast feedback only.
    """
    for conv in conventions:
        gaps = _docs_gaps(conv)
        if gaps:
            gap_lines = "\n".join(f"    - {g}" for g in gaps)
            raise DeployError(
                f'deploy blocked: convention "{conv.title}" is missing required '
                f"documentation:\n{gap_lines}",
                hint=(
                    "Supply them on convention(). Documentation is mandatory — "
                    "there is no skip flag."
                ),
            )


def _convention_to_payload(
    conv: ConventionInfo,
    hook_definitions: list[dict[str, Any]],
    ingester_image: tuple[str, str] | None = None,
) -> dict[str, Any]:
    """Build the CreateConvention request payload."""
    schema_fields = conv.schema_type.to_field_definitions()

    file_reqs = conv.file_requirements
    if "min_count" not in file_reqs:
        file_reqs = {**file_reqs, "min_count": 0}

    ingester: dict[str, Any] | None = None
    if ingester_image is not None and conv.ingester_info is not None:
        image, digest = ingester_image
        config = None
        ingester_cls = conv.ingester_info.ingester_cls
        if hasattr(ingester_cls, "RuntimeConfig"):
            config = ingester_cls.RuntimeConfig().model_dump()  # type: ignore[union-attr]

        schedule = None
        initial_run = None
        if conv.ingester_info.schedule is not None:
            schedule = conv.ingester_info.schedule.model_dump()
        if conv.ingester_info.initial_run is not None:
            initial_run = conv.ingester_info.initial_run.model_dump()

        ingester_limits = conv.ingester_info.limits
        ingester = {
            "image": image,
            "digest": digest,
            "runner": "oci",
            "config": config,
            "limits": ingester_limits.model_dump()
            if ingester_limits
            else {"timeout_seconds": 3600, "memory": "512m", "cpu": "0.5"},
            "schedule": schedule,
            "initial_run": initial_run,
        }

    return {
        "title": conv.title,
        "description": conv.description,
        "schema": {
            "id": conv.schema_type.schema_id(),
            "version": conv.version,
            "fields": schema_fields,
        },
        "file_requirements": file_reqs,
        "hooks": hook_definitions,
        "ingester": ingester,
        "docs": {
            "purpose": conv.purpose,
            "example_questions": conv.example_questions,
            "examples": [e.model_dump() for e in conv.examples],
            "when_not_to_use": conv.when_not_to_use,
            "see_also": conv.see_also,
        },
    }


def _resolve_existing_image(tag: str) -> tuple[str, str]:
    """Look up an already-pushed image's registry digest. Raises if not found."""
    result = subprocess.run(
        ["docker", "manifest", "inspect", tag, "--verbose"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise DeployError(
            f"Image not found in registry: {tag}",
            hint="Run deploy without --skip-build first",
        )
    data = json.loads(result.stdout)
    # docker manifest inspect --verbose returns a dict with Descriptor.digest
    if isinstance(data, list):
        data = data[0]
    digest = data.get("Descriptor", {}).get("digest", "")
    if not digest:
        raise DeployError(
            f"Could not resolve digest for {tag}",
            hint="Run deploy without --skip-build first",
        )
    return tag, digest


_AUTH_HINTS = {
    "token_expired": (
        "Your token has expired. Run `osa login` (or `osa start` for a local dev "
        "archive) to refresh it."
    ),
    "invalid_token": (
        "The server rejected the token signature — it was minted for a different JWT "
        "secret. For a local archive run `osa stop && osa start`; otherwise `osa login`."
    ),
    "missing_token": "Run `osa login` to authenticate.",
}


def _check_auth(server: str, token: str, ui: UI) -> None:
    """Verify the token against the server before any build (pre-flight).

    Probes ``GET /api/v1/auth/me``, which returns distinct 401 codes
    (``missing_token`` / ``token_expired`` / ``invalid_token``) so we can give a
    code-specific remediation hint. Raises ``DeployError`` on any auth or network
    failure; returns quietly (with a confirming UI line) on success.
    """
    url = f"{server.rstrip('/')}/api/v1/auth/me"
    headers = {"Authorization": f"Bearer {token}"}
    with ui.task("Verifying credentials") as task:
        try:
            resp = httpx.get(url, headers=headers, timeout=15.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (401, 403):
                code = _auth_error_code(e.response)
                task.fail("authentication failed")
                raise DeployError(
                    f"Authentication failed ({status})",
                    cause=e.response.text[:2000],
                    hint=_AUTH_HINTS.get(code, _AUTH_HINTS["missing_token"]),
                ) from e
            task.fail(f"auth check failed ({status})")
            raise DeployError(
                f"Auth check failed ({status})",
                cause=e.response.text[:2000],
            ) from e
        except httpx.HTTPError as e:
            task.fail("could not reach server")
            raise DeployError(
                f"Could not reach {server}",
                cause=str(e),
                hint="Check the server URL and your network connection",
            ) from e
        task.done(detail=_identity_detail(resp))


def _auth_error_code(response: httpx.Response) -> str | None:
    """Extract the server's structured auth error ``code``, if present."""
    try:
        detail = response.json().get("detail")
    except ValueError:
        return None
    if isinstance(detail, dict):
        code = detail.get("code")
        return code if isinstance(code, str) else None
    return None


def _identity_detail(response: httpx.Response) -> str | None:
    """A short 'who am I' label from the /auth/me body, or None if unavailable."""
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    name = body.get("display_name") or body.get("external_id")
    roles = body.get("roles")
    if name and isinstance(roles, list) and roles:
        return f"{name} ({', '.join(str(r) for r in roles)})"
    return str(name) if name else None


def _register_convention(
    conv: ConventionInfo,
    payload: dict[str, Any],
    server: str,
    token: str | None,
) -> dict[str, Any]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{server.rstrip('/')}/api/v1/conventions"
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        hint = (
            "Run `osa login` to refresh credentials" if status in (401, 403) else None
        )
        raise DeployError(
            f"Server rejected convention '{conv.title}' ({status})",
            cause=e.response.text[:2000],
            hint=hint,
        ) from e
    except httpx.HTTPError as e:
        raise DeployError(
            f"Could not reach {server}",
            cause=str(e),
            hint="Check the server URL and your network connection",
        ) from e
    return resp.json()


def deploy(
    server: str,
    project_dir: Path | None = None,
    tag_prefix: str = "osa-hooks",
    token: str | None = None,
    registry: str | None = None,
    skip_build: bool = False,
    ui: UI | None = None,
) -> dict[str, Any]:
    """Build hook/ingester images and register conventions with the OSA server.

    Returns the server response for the created convention.
    """
    ui = ui or UI.create()
    if project_dir is None:
        project_dir = Path.cwd()

    if not _conventions:
        raise RuntimeError(
            "No conventions registered. "
            "Make sure the convention package is imported before calling deploy."
        )

    # Mandatory-docs pre-flight — before any image build/push or network call.
    _check_docs_gate(_conventions)

    # Auth pre-flight — verify the token against the server before any build, so a
    # bad/expired token fails in ~1s instead of after 10 image builds.
    if token:
        _check_auth(server, token, ui)

    started_at = time.monotonic()
    ingester_names = list(
        dict.fromkeys(
            conv.ingester_info.name
            for conv in _conventions
            if conv.ingester_info is not None
        )
    )
    image_count = len(_hooks) + len(ingester_names)
    reuse_images = skip_build and registry is not None
    phase_title = "Resolving images" if reuse_images else "Building images"

    hook_images: dict[str, tuple[str, str]] = {}
    ingester_images: dict[str, tuple[str, str]] = {}

    with ui.phase(phase_title, count=image_count) as build_phase:
        for hook in _hooks:
            if reuse_images:
                assert registry is not None
                tag = f"{registry.rstrip('/')}/{hook.name}:latest"
                resolved = _resolve_existing_image(tag)
                hook_images[hook.name] = resolved
                build_phase.task(hook.name).skip(
                    f"reusing {_short_digest(resolved[1])}"
                )
            else:
                with build_phase.task(hook.name) as task:
                    hook_images[hook.name] = _build_hook_image(
                        hook, project_dir, tag_prefix, registry, task=task
                    )

        for conv in _conventions:
            if conv.ingester_info is None:
                continue
            name = conv.ingester_info.name
            if name in ingester_images:
                continue
            if reuse_images:
                assert registry is not None
                tag = f"{registry.rstrip('/')}/{name}:latest"
                resolved = _resolve_existing_image(tag)
                ingester_images[name] = resolved
                build_phase.task(name).skip(f"reusing {_short_digest(resolved[1])}")
            else:
                with build_phase.task(name) as task:
                    ingester_images[name] = _build_ingester_image(
                        conv.ingester_info,
                        project_dir,
                        tag_prefix,
                        registry,
                        task=task,
                    )

    results: list[dict[str, Any]] = []
    ingestable: list[tuple[str, str]] = []  # (title, slug) for conventions w/ ingester
    source_ref = _resolve_source_ref(project_dir)

    with ui.phase("Registering conventions", count=len(_conventions)) as reg_phase:
        for conv in _conventions:
            hook_defs = []
            for h in conv.hooks:
                name = h.__name__
                if name in hook_images:
                    image, digest = hook_images[name]
                    hook_info = next(hi for hi in _hooks if hi.name == name)
                    hook_defs.append(
                        _hook_to_definition(hook_info, image, digest, source_ref)
                    )

            ingester_img = None
            if (
                conv.ingester_info is not None
                and conv.ingester_info.name in ingester_images
            ):
                ingester_img = ingester_images[conv.ingester_info.name]

            payload = _convention_to_payload(conv, hook_defs, ingester_img)

            with reg_phase.task(conv.title) as task:
                result = _register_convention(conv, payload, server, token)
                task.done(detail=str(result.get("schema_id", "")))
            results.append(result)

            if conv.ingester_info is not None:
                slug = result.get("slug")
                if slug:
                    ingestable.append((conv.title, slug))

    noun = "convention" if len(results) == 1 else "conventions"
    ui.success(
        f"Deployed {len(results)} {noun}",
        elapsed=time.monotonic() - started_at,
    )

    for title, slug in ingestable:
        ui.info(f"Ingester ready for {title} — start a run with:")
        ui.detail(f"osa ingestion start --convention {slug}")

    return results[0] if len(results) == 1 else {"conventions": results}
