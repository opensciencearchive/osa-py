"""Tests for osa deploy — convention payload building and server registration."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from osa import Example
from osa._registry import ConventionInfo, HookInfo, IngesterInfo, clear


class FakeSchema:
    """Fake schema class that mimics MetadataSchema."""

    __name__ = "FakeSchema"

    @classmethod
    def schema_id(cls) -> str:
        return "fake-schema"

    @classmethod
    def to_field_definitions(cls) -> list[dict]:
        return [
            {
                "name": "title",
                "type": "text",
                "required": True,
                "cardinality": "exactly_one",
            },
            {
                "name": "score",
                "type": "number",
                "required": False,
                "cardinality": "exactly_one",
                "constraints": {"type": "number", "unit": "\u00c5"},
            },
        ]


class FakeIngester:
    name = "test-ingester"
    schedule = None
    initial_run = None

    class RuntimeConfig:
        def model_dump(self) -> dict:
            return {"email": "", "batch_size": 100}


def fake_hook(record):
    pass


fake_hook.__name__ = "detect_pockets"


class TestConventionToPayload:
    def test_builds_payload_with_schema_fields(self) -> None:
        from osa.cli.deploy import _convention_to_payload

        conv = ConventionInfo(
            title="Test Convention",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={
                "accepted_types": [".csv"],
                "max_count": 10,
                "max_file_size": 1000,
            },
            hooks=[],
            ingester_info=None,
        )

        payload = _convention_to_payload(conv, [])
        assert payload["title"] == "Test Convention"
        assert payload["description"] == "A test convention"
        assert payload["schema"]["id"] == "fake-schema"
        assert payload["schema"]["version"] == "1.0.0"
        assert len(payload["schema"]["fields"]) == 2
        assert payload["schema"]["fields"][0]["name"] == "title"
        assert payload["ingester"] is None

    def test_includes_ingester_definition(self) -> None:
        from osa.cli.deploy import _convention_to_payload

        ingester_info = IngesterInfo(ingester_cls=FakeIngester, name="test-ingester")

        conv = ConventionInfo(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={
                "accepted_types": [".cif"],
                "max_count": 5,
                "max_file_size": 500,
            },
            hooks=[],
            ingester_info=ingester_info,
        )

        payload = _convention_to_payload(
            conv,
            [],
            ingester_image=(
                "osa-hooks-ingesters/test-ingester:latest",
                "sha256:abc123",
            ),
        )
        assert payload["ingester"] is not None
        assert (
            payload["ingester"]["image"] == "osa-hooks-ingesters/test-ingester:latest"
        )
        assert payload["ingester"]["digest"] == "sha256:abc123"
        assert payload["ingester"]["runner"] == "oci"
        assert payload["ingester"]["config"] == {"email": "", "batch_size": 100}
        assert payload["ingester"]["limits"]["timeout_seconds"] == 3600

    def test_ingester_none_when_no_ingester(self) -> None:
        from osa.cli.deploy import _convention_to_payload

        conv = ConventionInfo(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={"accepted_types": [".csv"]},
            hooks=[],
            ingester_info=None,
        )

        payload = _convention_to_payload(conv, [])
        assert payload["ingester"] is None

    def test_ingester_none_when_no_ingester_image_provided(self) -> None:
        """Even with ingester_info, if no ingester_image tuple is given, ingester is None."""
        from osa.cli.deploy import _convention_to_payload

        ingester_info = IngesterInfo(ingester_cls=FakeIngester, name="test-ingester")

        conv = ConventionInfo(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={"accepted_types": [".cif"]},
            hooks=[],
            ingester_info=ingester_info,
        )

        payload = _convention_to_payload(conv, [])
        assert payload["ingester"] is None

    def test_adds_min_count_if_missing(self) -> None:
        from osa.cli.deploy import _convention_to_payload

        conv = ConventionInfo(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={
                "accepted_types": [".csv"],
                "max_count": 10,
                "max_file_size": 1000,
            },
            hooks=[],
            ingester_info=None,
        )

        payload = _convention_to_payload(conv, [])
        assert payload["file_requirements"]["min_count"] == 0

    def test_includes_hook_definitions(self) -> None:
        from osa.cli.deploy import _convention_to_payload

        hook_defs = [
            {
                "name": "detect_pockets",
                "feature": {
                    "kind": "table",
                    "cardinality": "many",
                    "columns": [],
                },
                "release": {
                    "image": "osa-hooks/detect_pockets:latest",
                    "digest": "sha256:abc123",
                    "config": {},
                    "limits": {"timeout_seconds": 300, "memory": "2g", "cpu": "2.0"},
                    "source_ref": "git:abc1234",
                },
            }
        ]

        conv = ConventionInfo(
            title="Test",
            description="A test convention",
            version="1.0.0",
            schema_type=FakeSchema,
            file_requirements={
                "accepted_types": [".csv"],
                "max_count": 10,
                "max_file_size": 1000,
            },
            hooks=[fake_hook],
            ingester_info=None,
        )

        payload = _convention_to_payload(conv, hook_defs)
        assert len(payload["hooks"]) == 1
        assert (
            payload["hooks"][0]["release"]["image"] == "osa-hooks/detect_pockets:latest"
        )


class TestHookToDefinition:
    def test_builds_hook_definition(self) -> None:
        from pydantic import BaseModel

        from osa.cli.deploy import _hook_to_definition

        class Pocket(BaseModel):
            pocket_id: int
            score: float

        hook_info = HookInfo(
            fn=fake_hook,
            name="detect_pockets",
            hook_type="hook",
            schema_type=FakeSchema,
            output_type=Pocket,
            cardinality="many",
        )

        defn = _hook_to_definition(
            hook_info, "osa-hooks/detect_pockets:latest", "sha256:abc", "git:abc1234"
        )
        assert defn["release"]["image"] == "osa-hooks/detect_pockets:latest"
        assert defn["release"]["digest"] == "sha256:abc"
        assert defn["release"]["source_ref"] == "git:abc1234"
        assert defn["name"] == "detect_pockets"
        assert defn["feature"]["cardinality"] == "many"
        assert len(defn["feature"]["columns"]) == 2

    def test_empty_columns_when_no_output_type(self) -> None:
        from osa.cli.deploy import _hook_to_definition

        hook_info = HookInfo(
            fn=fake_hook,
            name="simple_hook",
            hook_type="hook",
            schema_type=FakeSchema,
            output_type=None,
            cardinality="one",
        )

        defn = _hook_to_definition(hook_info, "img:latest", "sha256:xyz", "git:unknown")
        assert defn["feature"]["columns"] == []


class TestResolveSourceRef:
    def test_returns_git_ref_on_success(self) -> None:
        from osa.cli.deploy import _resolve_source_ref

        mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="1a2b3c4\n"))
        with patch("osa.cli.deploy.subprocess.run", mock_run):
            assert _resolve_source_ref(Path(".")) == "git:1a2b3c4"

    def test_falls_back_to_unknown_on_failure(self) -> None:
        from osa.cli.deploy import _resolve_source_ref

        mock_run = MagicMock(return_value=MagicMock(returncode=128, stdout=""))
        with patch("osa.cli.deploy.subprocess.run", mock_run):
            assert _resolve_source_ref(Path(".")) == "git:unknown"

    def test_falls_back_when_git_missing(self) -> None:
        from osa.cli.deploy import _resolve_source_ref

        mock_run = MagicMock(side_effect=FileNotFoundError)
        with patch("osa.cli.deploy.subprocess.run", mock_run):
            assert _resolve_source_ref(Path(".")) == "git:unknown"


class TestDeployRaisesWithoutConventions:
    def setup_method(self) -> None:
        clear()

    def test_raises_if_no_conventions(self) -> None:
        from osa.cli.deploy import deploy

        with pytest.raises(RuntimeError, match="No conventions registered"):
            deploy(server="http://localhost:8000")


class TestDeployEndToEnd:
    def setup_method(self) -> None:
        clear()

    def test_builds_and_registers(self) -> None:
        from osa._registry import _conventions, _hooks

        from osa.cli.deploy import deploy

        ingester_info = IngesterInfo(ingester_cls=FakeIngester, name="test-ingester")

        # Register a fake convention and hook
        _hooks.append(
            HookInfo(
                fn=fake_hook,
                name="detect_pockets",
                hook_type="hook",
                schema_type=FakeSchema,
                output_type=None,
                cardinality="many",
            )
        )
        _conventions.append(
            ConventionInfo(
                title="PDB Structures",
                description="Protein structures from the PDB",
                version="1.0.0",
                schema_type=FakeSchema,
                file_requirements={
                    "accepted_types": [".cif"],
                    "max_count": 5,
                    "max_file_size": 500_000_000,
                },
                hooks=[fake_hook],
                ingester_info=ingester_info,
                purpose="Protein structures for tests.",
                example_questions=["q1?", "q2?", "q3?"],
                examples=[
                    Example(question="q1?", query="GET /x", interpretation="means x")
                ],
            )
        )

        # Mock docker build (streamed) + inspect
        from osa.cli.proc import ProcResult

        mock_streamed = MagicMock(return_value=ProcResult(returncode=0, output=""))
        mock_run = MagicMock()
        mock_run.return_value = MagicMock(returncode=0, stdout="sha256:fakedigest\n")

        # Mock httpx.post
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "slug": "pdb-structures",
            "title": "PDB Structures",
            "description": "Protein structures from the PDB",
            "schema_id": "fake-schema@1.0.0",
            "hooks": ["detect_pockets"],
            "created_at": "2026-06-15T12:00:00Z",
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_httpx.post.return_value = mock_response

        import io

        from osa.cli.ui import UI

        buf = io.StringIO()
        ui = UI.create(file=buf, force_plain=True)

        with (
            patch("osa.cli.deploy.run_streamed", mock_streamed),
            patch("osa.cli.deploy.subprocess.run", mock_run),
            patch("osa.cli.deploy.httpx", mock_httpx),
            patch("osa.cli.deploy.Path.write_text"),
            patch("osa.cli.deploy.Path.unlink"),
        ):
            result = deploy(
                server="http://localhost:8000",
                token="fake-jwt",
                ui=ui,
            )

        assert result["schema_id"] == "fake-schema@1.0.0"

        # Deploy hints how to start ingestion, using the server-minted slug.
        output = buf.getvalue()
        assert "osa ingestion start --convention pdb-structures" in output

        # Verify POST was made to correct URL
        call_args = mock_httpx.post.call_args
        payload = call_args[1]["json"]
        assert "slug" not in payload
        assert payload["title"] == "PDB Structures"
        assert payload["schema"]["id"] == "fake-schema"
        assert payload["hooks"][0]["release"]["source_ref"].startswith("git:")
        assert payload["ingester"] is not None
        assert payload["ingester"]["runner"] == "oci"
        assert payload["ingester"]["config"] == {"email": "", "batch_size": 100}
        assert "Bearer fake-jwt" in call_args[1]["headers"]["Authorization"]
