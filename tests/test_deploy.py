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

    def test_hook_definition_carries_column_metadata(self) -> None:
        from pydantic import BaseModel
        from pydantic import Field as PydanticField

        from osa._registry import HookInfo
        from osa.cli.deploy import _hook_to_definition

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
        definition = _hook_to_definition(info, "img:latest", "sha256:abc", "git:abc")
        col = definition["feature"]["columns"][0]
        assert col["description"] == "Pocket score"
        assert col["unit"] == "kcal/mol"
