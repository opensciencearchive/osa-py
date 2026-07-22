"""Tests for osa deploy CLI: Dockerfile generation."""

from __future__ import annotations

import io
from unittest.mock import patch

import httpx
import pytest


def _quiet_ui():
    from osa.cli.ui import UI

    return UI.create(file=io.StringIO(), force_plain=True)


def _auth_response(status: int, body: dict) -> httpx.Response:
    request = httpx.Request("GET", "http://localhost:8000/api/v1/auth/me")
    return httpx.Response(status, json=body, request=request)


class TestAuthPreflight:
    """`osa deploy` verifies the token against the server before any build."""

    def test_success_returns_quietly(self) -> None:
        from osa.cli.deploy import _check_auth

        resp = _auth_response(200, {"display_name": "Rory", "roles": ["superadmin"]})
        with patch("osa.cli.deploy.httpx.get", return_value=resp):
            # No raise == success.
            _check_auth("http://localhost:8000", "good-token", _quiet_ui())

    def test_invalid_token_raises_with_signature_hint(self) -> None:
        from osa.cli.deploy import DeployError, _check_auth

        resp = _auth_response(401, {"detail": {"code": "invalid_token"}})
        with patch("osa.cli.deploy.httpx.get", return_value=resp):
            with pytest.raises(DeployError) as exc_info:
                _check_auth("http://localhost:8000", "bad-sig", _quiet_ui())
        assert "Authentication failed (401)" in str(exc_info.value)
        assert "signature" in (exc_info.value.hint or "")
        assert "osa start" in (exc_info.value.hint or "")

    def test_expired_token_hint(self) -> None:
        from osa.cli.deploy import DeployError, _check_auth

        resp = _auth_response(401, {"detail": {"code": "token_expired"}})
        with patch("osa.cli.deploy.httpx.get", return_value=resp):
            with pytest.raises(DeployError) as exc_info:
                _check_auth("http://localhost:8000", "stale", _quiet_ui())
        assert "expired" in (exc_info.value.hint or "").lower()

    def test_non_dict_json_body_falls_back_to_default_hint(self) -> None:
        # A proxy may return a bare JSON string / list / null on 401; the code
        # extractor must not raise, and we fall back to the generic hint.
        from osa.cli.deploy import DeployError, _check_auth

        resp = _auth_response(401, "Unauthorized")
        with patch("osa.cli.deploy.httpx.get", return_value=resp):
            with pytest.raises(DeployError) as exc_info:
                _check_auth("http://localhost:8000", "tok", _quiet_ui())
        assert "Authentication failed (401)" in str(exc_info.value)
        assert "osa login" in (exc_info.value.hint or "")

    def test_network_error_raises_unreachable(self) -> None:
        from osa.cli.deploy import DeployError, _check_auth

        with patch(
            "osa.cli.deploy.httpx.get",
            side_effect=httpx.ConnectError("refused"),
        ):
            with pytest.raises(DeployError) as exc_info:
                _check_auth("http://localhost:8000", "tok", _quiet_ui())
        assert "Could not reach" in str(exc_info.value)

    def test_aborts_before_any_build(self) -> None:
        from osa._registry import clear
        from osa.authoring.convention import convention
        from osa.cli.deploy import DeployError, deploy
        from osa.types.schema import MetadataSchema

        clear()

        class PreflightSchema(MetadataSchema):
            __schema_id__ = "preflight-schema"

            organism: str

        from osa import Example

        convention(
            title="Preflight Convention",
            description="x",
            version="1.0.0",
            schema=PreflightSchema,
            files={},
            hooks=[],
            purpose="Test data.",
            example_questions=["q1?", "q2?", "q3?"],
            examples=[
                Example(question="q1?", query="GET /x", interpretation="means x")
            ],
        )

        resp = _auth_response(401, {"detail": {"code": "invalid_token"}})
        with (
            patch("osa.cli.deploy._build_hook_image") as build,
            patch("osa.cli.deploy.httpx.get", return_value=resp),
            patch("osa.cli.deploy.httpx.post") as post,
        ):
            build.side_effect = AssertionError("image build ran before auth gate")
            post.side_effect = AssertionError("registration ran before auth gate")
            with pytest.raises(DeployError, match="Authentication failed"):
                deploy(server="http://localhost:8000", token="bad-token")

        assert build.call_count == 0
        assert post.call_count == 0


class TestDockerfileGeneration:
    def test_generates_dockerfile_from_pyproject(self, tmp_path) -> None:
        from osa.cli.deploy import generate_hook_dockerfile

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test-hooks"\nrequires-python = ">=3.13"\n'
        )

        dockerfile = generate_hook_dockerfile(tmp_path)
        assert "FROM python:3.13-slim" in dockerfile
        assert "pip install" in dockerfile

    def test_dockerfile_uses_python_version_from_pyproject(self, tmp_path) -> None:
        from osa.cli.deploy import generate_hook_dockerfile

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test-hooks"\nrequires-python = ">=3.12"\n'
        )

        dockerfile = generate_hook_dockerfile(tmp_path)
        assert "FROM python:3.12-slim" in dockerfile

    def test_dockerfile_includes_entrypoint(self, tmp_path) -> None:
        from osa.cli.deploy import generate_hook_dockerfile

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test-hooks"\nrequires-python = ">=3.13"\n'
        )

        dockerfile = generate_hook_dockerfile(tmp_path)
        assert "ENTRYPOINT" in dockerfile
        assert "osa-run-hook" in dockerfile

    def test_raises_if_no_pyproject(self, tmp_path) -> None:
        from osa.cli.deploy import generate_hook_dockerfile

        with pytest.raises(FileNotFoundError):
            generate_hook_dockerfile(tmp_path)

    def test_dockerfile_stages_local_sdk_when_source_present(self, tmp_path) -> None:
        from osa.cli.deploy import generate_ingester_dockerfile

        sdk_dir = tmp_path / "sdk"
        sdk_dir.mkdir()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            'name = "pilot"\n'
            'requires-python = ">=3.13"\n'
            'dependencies = ["osa-py"]\n\n'
            "[tool.uv.sources]\n"
            'osa-py = { path = "sdk", editable = true }\n'
        )

        dockerfile = generate_ingester_dockerfile(tmp_path)
        assert "COPY .osa-sdk /app/.osa-sdk" in dockerfile
        assert "pip install /app/.osa-sdk" in dockerfile
        assert "osa-run-ingester" in dockerfile

    def test_dockerfile_uses_pypi_when_no_source(self, tmp_path) -> None:
        from osa.cli.deploy import generate_hook_dockerfile

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            "[project]\n"
            'name = "pilot"\n'
            'requires-python = ">=3.13"\n'
            'dependencies = ["osa-py"]\n'
        )

        dockerfile = generate_hook_dockerfile(tmp_path)
        assert ".osa-sdk" not in dockerfile


class TestFindSdkPath:
    def test_resolves_osa_py_path_source(self, tmp_path) -> None:
        from osa.cli.deploy import _find_sdk_path

        sdk_dir = tmp_path / "osa" / "sdk" / "py"
        sdk_dir.mkdir(parents=True)
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[tool.uv.sources]\nosa-py = { path = "osa/sdk/py" }\n')

        assert _find_sdk_path(tmp_path) == sdk_dir.resolve()

    def test_handles_inline_table_key_order(self, tmp_path) -> None:
        from osa.cli.deploy import _find_sdk_path

        sdk_dir = tmp_path / "sdk"
        sdk_dir.mkdir()
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.uv.sources]\nosa-py = { editable = true, path = "sdk" }\n'
        )

        assert _find_sdk_path(tmp_path) == sdk_dir.resolve()

    def test_returns_none_without_source(self, tmp_path) -> None:
        from osa.cli.deploy import _find_sdk_path

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "pilot"\n')

        assert _find_sdk_path(tmp_path) is None

    def test_returns_none_when_path_missing_on_disk(self, tmp_path) -> None:
        from osa.cli.deploy import _find_sdk_path

        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[tool.uv.sources]\nosa-py = { path = "does/not/exist" }\n'
        )

        assert _find_sdk_path(tmp_path) is None

    def test_returns_none_without_pyproject(self, tmp_path) -> None:
        from osa.cli.deploy import _find_sdk_path

        assert _find_sdk_path(tmp_path) is None


class TestColumnMetadataEmission:
    """#151: hook output column description/unit must reach the deploy payload."""

    def test_generate_columns_emits_description_and_unit(self) -> None:
        from pydantic import BaseModel
        from pydantic import Field as PydanticField

        from osa.manifest import generate_columns

        class DuctilityRow(BaseModel):
            transition_temp: float = PydanticField(
                description="Ductile-brittle transition",
                json_schema_extra={"unit": "°C"},
            )
            batch: str

        columns = {c.name: c for c in generate_columns(DuctilityRow)}
        assert columns["transition_temp"].description == "Ductile-brittle transition"
        assert columns["transition_temp"].unit == "°C"
        assert columns["batch"].description is None
        assert columns["batch"].unit is None

    def test_hook_columns_carry_column_metadata(self) -> None:
        from pydantic import BaseModel
        from pydantic import Field as PydanticField

        from osa._registry import HookInfo
        from osa.cli.deploy import _hook_columns

        class Row(BaseModel):
            score: float = PydanticField(
                description="Pocket score", json_schema_extra={"unit": "kcal/mol"}
            )

        def fn(record):
            pass

        info = HookInfo(
            fn=fn,  # type: ignore[arg-type]
            name="detect",
            hook_type="feature",
            schema_type=None,  # type: ignore[arg-type]
            output_type=Row,
            cardinality="many",
        )
        col = _hook_columns(info)[0]
        assert col.description == "Pocket score"
        assert col.unit == "kcal/mol"


def _find_null(obj, path=""):
    """Return the first JSON path holding a ``None``, else ``None`` (no nulls)."""
    if obj is None:
        return path or "<root>"
    if isinstance(obj, dict):
        for k, v in obj.items():
            hit = _find_null(v, f"{path}.{k}")
            if hit:
                return hit
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hit = _find_null(v, f"{path}[{i}]")
            if hit:
                return hit
    return None


class TestConventionManifest:
    """One symmetric model: `build_manifest` + `bind_releases` + edge dump.

    Hooks and ingesters are both `Component`s (authored config/limits + an
    optional nested build `release`); the wire is produced by plain
    `model_dump(by_alias=True, exclude_none=True)` — no custom serializers.
    """

    def _manifest(self):
        from osa.cli.deploy import (
            ConventionDocs,
            ConventionManifest,
            Feature,
            Hook,
            Ingester,
            SchemaRef,
        )
        from osa.types.ingester import IngesterSchedule, Limits

        return ConventionManifest(
            title="T",
            description="d",
            schema=SchemaRef(id="s", version="1.0.0", fields=[]),
            file_requirements={
                "accepted_types": [".csv"],
                "max_count": 3,
                "max_file_size": 100,
                "min_count": 0,
            },
            hooks=[
                Hook(
                    name="detect",
                    config={},
                    limits=Limits(memory="512m"),
                    feature=Feature(cardinality="many", columns=[]),
                )
            ],
            ingester=Ingester(
                name="ingest",
                config={"k": "v"},
                limits=Limits(),
                schedule=IngesterSchedule(cron="0 0 * * *"),
                initial_run=None,
            ),
            docs=ConventionDocs(purpose="p", example_questions=[], examples=[]),
        )

    # --- structure / symmetry -------------------------------------------------

    def test_hook_and_ingester_share_component_base(self) -> None:
        from osa.cli.deploy import Component, Hook, Ingester

        assert issubclass(Hook, Component) and issubclass(Ingester, Component)
        for f in ("name", "config", "limits", "release"):
            assert f in Component.model_fields
        assert "feature" in Hook.model_fields
        assert {"schedule", "initial_run"} <= set(Ingester.model_fields)

    def test_manifest_has_no_build_or_cloud_fields(self) -> None:
        from osa.cli.deploy import Component, ConventionManifest

        # Build artifacts live only under `release`; cloud policy never here.
        for f in ("image", "digest", "source_ref"):
            assert f not in Component.model_fields
        for f in ("slug", "runtime_version"):
            assert f not in ConventionManifest.model_fields

    # --- bind_releases (uniform across hooks + ingester) ----------------------

    def test_bind_sets_release_on_hook_and_ingester(self) -> None:
        from osa.cli.deploy import ComponentRelease, bind_releases

        m = self._manifest()
        bound = bind_releases(
            m,
            {"detect": ComponentRelease(image="i", digest="d", source_ref="g")},
            ComponentRelease(image="ii", digest="dd", source_ref="g"),
        )
        assert bound.hooks[0].release.image == "i"
        assert bound.ingester.release.image == "ii"
        assert bound.ingester.release.source_ref == "g"
        # bind copies — the input manifest is untouched.
        assert m.hooks[0].release is None and m.ingester.release is None

    def test_bind_missing_release_stays_none(self) -> None:
        from osa.cli.deploy import ComponentRelease, bind_releases

        bound = bind_releases(
            self._manifest(),
            {"detect": ComponentRelease(image="i", digest="d", source_ref="g")},
            None,
        )
        assert bound.hooks[0].release is not None  # only detect was built
        assert bound.ingester.release is None

    def test_same_name_hook_and_ingester_do_not_collide(self) -> None:
        # A hook and the ingester sharing a name must not clobber each other in a
        # shared keyspace (regression: they used to share one name-keyed map).
        from osa.cli.deploy import (
            ComponentRelease,
            ConventionDocs,
            ConventionManifest,
            Feature,
            Hook,
            Ingester,
            SchemaRef,
            bind_releases,
        )
        from osa.types.ingester import Limits

        m = ConventionManifest(
            title="T",
            description="d",
            schema=SchemaRef(id="s", version="1.0.0", fields=[]),
            file_requirements={"min_count": 0},
            hooks=[
                Hook(
                    name="shared",
                    config={},
                    limits=Limits(),
                    feature=Feature(cardinality="many", columns=[]),
                )
            ],
            ingester=Ingester(name="shared", config={}, limits=Limits()),
            docs=ConventionDocs(purpose="p", example_questions=[], examples=[]),
        )
        bound = bind_releases(
            m,
            {"shared": ComponentRelease(image="hook-img", digest="hd", source_ref="g")},
            ComponentRelease(image="ing-img", digest="id", source_ref="g"),
        )
        assert bound.hooks[0].release.image == "hook-img"
        assert bound.ingester.release.image == "ing-img"

    # --- edge serialization ---------------------------------------------------

    def test_release_less_wire_omits_release_and_has_no_nulls(self) -> None:
        wire = self._manifest().model_dump(by_alias=True, exclude_none=True)
        hook = wire["hooks"][0]
        assert "release" not in hook
        assert hook["config"] == {} and "limits" in hook and "feature" in hook
        ing = wire["ingester"]
        assert "release" not in ing and ing["config"] == {"k": "v"}
        # ingester is symmetric with hooks: no flat image/digest/runner.
        assert not ({"image", "digest", "runner"} & set(ing))
        assert _find_null(wire) is None, f"unexpected null at {_find_null(wire)}"

    def test_bound_wire_nests_release_on_both_symmetrically(self) -> None:
        from osa.cli.deploy import ComponentRelease, bind_releases

        wire = bind_releases(
            self._manifest(),
            {"detect": ComponentRelease(image="i", digest="d", source_ref="g")},
            ComponentRelease(image="ii", digest="dd", source_ref="g"),
        ).model_dump(by_alias=True, exclude_none=True)
        assert wire["hooks"][0]["release"] == {
            "image": "i",
            "digest": "d",
            "source_ref": "g",
        }
        assert wire["ingester"]["release"] == {
            "image": "ii",
            "digest": "dd",
            "source_ref": "g",
        }
        # config/limits stay on the component, never inside release.
        assert "config" not in wire["hooks"][0]["release"]
        assert wire["hooks"][0]["config"] == {}
        assert wire["ingester"]["config"] == {"k": "v"}
        assert _find_null(wire) is None

    def test_schema_alias_and_ingester_none(self) -> None:
        m = self._manifest().model_copy(update={"ingester": None})
        wire = m.model_dump(by_alias=True, exclude_none=True)
        assert "schema" in wire and "record_schema" not in wire
        assert "ingester" not in wire  # None → omitted by exclude_none

    def test_build_manifest_release_free(self) -> None:
        from osa import Example, Field, Schema
        from osa._registry import _conventions, clear
        from osa.authoring.convention import convention
        from osa.cli.deploy import ConventionManifest, build_manifest

        clear()

        class Cell(Schema):
            __schema_id__ = "cell-schema"

            organism: str = Field(description="Organism")

        convention(
            title="Cell Convention",
            description="x",
            version="1.0.0",
            schema=Cell,
            files={"accepted_types": [".csv"], "max_count": 1, "max_file_size": 1},
            hooks=[],
            purpose="Test data.",
            example_questions=["q1?", "q2?", "q3?"],
            examples=[Example(question="q1?", query="GET /x", interpretation="x")],
        )

        manifest = build_manifest(_conventions[0])
        assert isinstance(manifest, ConventionManifest)
        assert manifest.title == "Cell Convention"
        assert manifest.docs.purpose == "Test data."
        assert isinstance(manifest.record_schema.fields, list)
        # release-less by construction; clean wire.
        wire = manifest.model_dump(by_alias=True, exclude_none=True)
        assert _find_null(wire) is None
