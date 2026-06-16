"""Tests for osa deploy CLI: Dockerfile generation."""

from __future__ import annotations


import pytest


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
