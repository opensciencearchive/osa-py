"""OSA deploy CLI: build hook/ingester images and register conventions with the server."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from osa._registry import ConventionInfo, HookInfo, IngesterInfo, _conventions, _hooks
from osa.manifest import generate_columns


def _read_python_version(project_dir: Path) -> str:
    """Read requires-python from pyproject.toml, default to 3.13."""
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        raise FileNotFoundError(f"pyproject.toml not found in {project_dir}")
    content = pyproject_path.read_text()
    match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', content)
    return match.group(1) if match else "3.13"


def _find_sdk_path(project_dir: Path) -> Path | None:
    """Resolve the local OSA SDK path from [tool.uv.sources] in pyproject.toml."""
    pyproject_path = project_dir / "pyproject.toml"
    if not pyproject_path.exists():
        return None
    content = pyproject_path.read_text()
    match = re.search(r'osa\s*=\s*\{\s*path\s*=\s*"([^"]+)"', content)
    if match:
        sdk_path = (project_dir / match.group(1)).resolve()
        if sdk_path.exists():
            return sdk_path
    return None


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
        print(f"Building image for {name} → {tag}")
        build = subprocess.run(
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
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            print(
                f"Docker build failed for {name}:\n{build.stderr or build.stdout}",
                file=sys.stderr,
            )
            build.check_returncode()

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
                print(f"Image unchanged, skipping push for {tag}")
                return tag, digest

            print(f"Pushing {tag}")
            push = subprocess.run(
                ["docker", "push", tag],
                capture_output=True,
                text=True,
            )
            if push.returncode != 0:
                print(
                    f"Docker push failed for {tag}:\n{push.stderr or push.stdout}",
                    file=sys.stderr,
                )
                push.check_returncode()

            result = subprocess.run(
                ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", tag],
                check=True,
                capture_output=True,
                text=True,
            )
            repo_digest = result.stdout.strip()
            digest = repo_digest.split("@", 1)[1]

            print(f"Pushed {tag} → {digest}")
            return tag, digest

        print(f"Built {tag} → {local_id}")
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
) -> tuple[str, str]:
    """Build a Docker image for a hook and return (image_tag, digest)."""
    dockerfile_content = generate_hook_dockerfile(project_dir)
    return _build_image(
        hook.name, dockerfile_content, project_dir, tag_prefix, registry
    )


def _build_ingester_image(
    ingester: IngesterInfo,
    project_dir: Path,
    tag_prefix: str,
    registry: str | None = None,
) -> tuple[str, str]:
    """Build a Docker image for an ingester and return (image_tag, digest)."""
    dockerfile_content = generate_ingester_dockerfile(project_dir)
    return _build_image(
        ingester.name,
        dockerfile_content,
        project_dir,
        f"{tag_prefix}-ingesters",
        registry,
    )


def _hook_to_definition(
    hook: HookInfo,
    image: str,
    digest: str,
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
        "runtime": {
            "type": "oci",
            "image": image,
            "digest": digest,
            "config": {},
            "limits": hook.limits.model_dump(),
        },
        "feature": {
            "kind": "table",
            "cardinality": hook.cardinality,
            "columns": columns,
        },
    }


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
    if ingester_image is not None and conv.ingester_type is not None:
        image, digest = ingester_image
        config = None
        if hasattr(conv.ingester_type, "RuntimeConfig"):
            config = conv.ingester_type.RuntimeConfig().model_dump()  # type: ignore[union-attr]

        schedule = None
        initial_run = None
        if conv.ingester_info is not None:
            if conv.ingester_info.schedule is not None:
                schedule = conv.ingester_info.schedule.model_dump()
            if conv.ingester_info.initial_run is not None:
                initial_run = conv.ingester_info.initial_run.model_dump()

        ingester_limits = conv.ingester_info.limits if conv.ingester_info else None
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
        "id": conv.schema_type.schema_id(),
        "title": conv.title,
        "version": conv.version,
        "schema": schema_fields,
        "file_requirements": file_reqs,
        "hooks": hook_definitions,
        "ingester": ingester,
    }


def _resolve_existing_image(tag: str) -> tuple[str, str]:
    """Look up an already-pushed image's registry digest. Raises if not found."""
    result = subprocess.run(
        ["docker", "manifest", "inspect", tag, "--verbose"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Image not found in registry: {tag}. Run deploy without --skip-build first."
        )
    data = json.loads(result.stdout)
    # docker manifest inspect --verbose returns a dict with Descriptor.digest
    if isinstance(data, list):
        data = data[0]
    digest = data.get("Descriptor", {}).get("digest", "")
    if not digest:
        raise RuntimeError(
            f"Could not resolve digest for {tag}. Run deploy without --skip-build first."
        )
    print(f"Reusing {tag} ({digest[:19]}...)")
    return tag, digest


def deploy(
    server: str,
    project_dir: Path | None = None,
    tag_prefix: str = "osa-hooks",
    token: str | None = None,
    registry: str | None = None,
    skip_build: bool = False,
) -> dict[str, Any]:
    """Build hook/ingester images and register conventions with the OSA server.

    Returns the server response for the created convention.
    """
    if project_dir is None:
        project_dir = Path.cwd()

    if not _conventions:
        raise RuntimeError(
            "No conventions registered. "
            "Make sure the convention package is imported before calling deploy."
        )

    # Build images for each hook
    hook_images: dict[str, tuple[str, str]] = {}
    for hook in _hooks:
        if skip_build and registry:
            tag = f"{registry.rstrip('/')}/{hook.name}:latest"
            hook_images[hook.name] = _resolve_existing_image(tag)
        else:
            image, digest = _build_hook_image(hook, project_dir, tag_prefix, registry)
            hook_images[hook.name] = (image, digest)

    # Build images for ingesters
    ingester_images: dict[str, tuple[str, str]] = {}
    for conv in _conventions:
        if conv.ingester_info is not None:
            name = conv.ingester_info.name
            if name not in ingester_images:
                if skip_build and registry:
                    tag = f"{registry.rstrip('/')}/{name}:latest"
                    ingester_images[name] = _resolve_existing_image(tag)
                else:
                    image, digest = _build_ingester_image(
                        conv.ingester_info, project_dir, tag_prefix, registry
                    )
                    ingester_images[name] = (image, digest)

    results: list[dict[str, Any]] = []

    for conv in _conventions:
        # Match hooks to this convention
        hook_defs = []
        for h in conv.hooks:
            name = h.__name__
            if name in hook_images:
                image, digest = hook_images[name]
                hook_info = next(hi for hi in _hooks if hi.name == name)
                hook_defs.append(_hook_to_definition(hook_info, image, digest))

        # Get ingester image if applicable
        ingester_img = None
        if (
            conv.ingester_info is not None
            and conv.ingester_info.name in ingester_images
        ):
            ingester_img = ingester_images[conv.ingester_info.name]

        payload = _convention_to_payload(conv, hook_defs, ingester_img)

        print(f"Registering convention '{conv.title}' with {server}")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{server.rstrip('/')}/api/v1/conventions"
        resp = httpx.post(url, json=payload, headers=headers, timeout=30.0)
        resp.raise_for_status()
        result = resp.json()
        results.append(result)

        print(f"Convention registered: {result.get('srn', '')}")

    return results[0] if len(results) == 1 else {"conventions": results}
