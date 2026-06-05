"""Tests for osa ingestion start command."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import BaseModel

from osa.cli.ingestion import (
    IngestionError,
    build_convention_srn,
    discover_ingestable_conventions,
    start_ingestion,
)
from osa.runtime.ingester_context import IngesterContext
from osa.types.ingester import IngesterRecord
from osa.types.record import Record
from osa.types.schema import MetadataSchema


class _Schema(MetadataSchema):
    __schema_id__ = "test-schema"
    name: str


class _Result(BaseModel):
    score: float


class _TestIngester:
    name = "test-ingester"

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        since: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        yield  # pragma: no cover


class _AnotherIngester:
    name = "another-ingester"

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        since: datetime | None = None,
        limit: int | None = None,
        offset: int = 0,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        yield  # pragma: no cover


def _make_response(status_code: int, json_data: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "http://localhost:8000/api/v1/ingestions"),
    )


class TestStartIngestion:
    def _write_osa_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("domain: test.example.com\n")

    def test_posts_to_ingestions_endpoint(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            200, {"srn": "urn:osa:test.example.com:ingest:abc", "status": "started"}
        )

        result = start_ingestion(
            server="http://localhost:8000",
            convention="rcsb-pdb",
            token="fake-token",
            project_dir=tmp_path,
            http=mock_client,
        )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8000/api/v1/ingestions"
        assert call_args[1]["json"]["convention_srn"].startswith("urn:osa:")
        assert "rcsb-pdb" in call_args[1]["json"]["convention_srn"]
        assert result["status"] == "started"

    def test_default_batch_size_is_1000(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention="test",
            token="fake-token",
            project_dir=tmp_path,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["batch_size"] == 1000

    def test_custom_batch_size(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention="test",
            token="fake-token",
            batch_size=500,
            project_dir=tmp_path,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["batch_size"] == 500

    def test_sends_bearer_token(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention="test",
            token="my-token",
            project_dir=tmp_path,
            http=mock_client,
        )

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-token"

    def test_raises_on_http_error(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        resp = _make_response(404, {"detail": "Convention not found"})
        mock_client.post.return_value = resp

        with pytest.raises(IngestionError, match="Convention not found"):
            start_ingestion(
                server="http://localhost:8000",
                convention="missing",
                token="fake-token",
                project_dir=tmp_path,
                http=mock_client,
            )

    def test_limit_included_when_set(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention="test",
            token="fake-token",
            limit=50,
            project_dir=tmp_path,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["limit"] == 50

    def test_limit_omitted_by_default(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention="test",
            token="fake-token",
            project_dir=tmp_path,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert "limit" not in payload

    def test_strips_trailing_slash_from_server(self, tmp_path: Path) -> None:
        self._write_osa_yaml(tmp_path)
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000/",
            convention="test",
            token="fake-token",
            project_dir=tmp_path,
            http=mock_client,
        )

        url = mock_client.post.call_args[0][0]
        assert url == "http://localhost:8000/api/v1/ingestions"


class TestBuildConventionSrn:
    def test_builds_srn_from_osa_yaml(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("name: pockets\ndomain: pockets.amacr.in\n")

        srn = build_convention_srn(title="PDB Structures", project_dir=tmp_path)
        assert srn == "urn:osa:pockets.amacr.in:conv:PDB Structures@1.0.0"

    def test_custom_version(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("domain: data.mylab.org\n")

        srn = build_convention_srn(
            title="My Conv", project_dir=tmp_path, version="2.0.0"
        )
        assert srn == "urn:osa:data.mylab.org:conv:My Conv@2.0.0"

    def test_raises_when_no_osa_yaml(self, tmp_path: Path) -> None:
        with pytest.raises(IngestionError, match="osa.yaml not found"):
            build_convention_srn(title="Test", project_dir=tmp_path)

    def test_raises_when_no_domain(self, tmp_path: Path) -> None:
        (tmp_path / "osa.yaml").write_text("name: pockets\n")

        with pytest.raises(IngestionError, match="No 'domain' field"):
            build_convention_srn(title="Test", project_dir=tmp_path)


class TestDiscoverIngestableConventions:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def test_returns_empty_when_no_conventions(self) -> None:
        result = discover_ingestable_conventions()
        assert result == []

    def test_filters_out_conventions_without_ingester(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def my_hook(record: Record[_Schema]) -> _Result:
            return _Result(score=1.0)

        convention(
            title="No Ingester",
            version="1.0.0",
            schema=_Schema,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )

        result = discover_ingestable_conventions()
        assert result == []

    def test_returns_convention_with_ingester(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def my_hook(record: Record[_Schema]) -> _Result:
            return _Result(score=1.0)

        convention(
            title="With Ingester",
            version="2.0.0",
            schema=_Schema,
            ingester=_TestIngester,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )

        result = discover_ingestable_conventions()
        assert len(result) == 1
        assert result[0].title == "With Ingester"
        assert result[0].version == "2.0.0"
        assert result[0].ingester_name == "test-ingester"

    def test_filters_mixed_conventions(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def my_hook(record: Record[_Schema]) -> _Result:
            return _Result(score=1.0)

        convention(
            title="No Ingester",
            version="1.0.0",
            schema=_Schema,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )
        convention(
            title="Has Ingester",
            version="1.0.0",
            schema=_Schema,
            ingester=_TestIngester,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )

        result = discover_ingestable_conventions()
        assert len(result) == 1
        assert result[0].title == "Has Ingester"

    def test_returns_multiple_ingestable_conventions(self) -> None:
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        @hook
        def my_hook(record: Record[_Schema]) -> _Result:
            return _Result(score=1.0)

        convention(
            title="First",
            version="1.0.0",
            schema=_Schema,
            ingester=_TestIngester,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )
        convention(
            title="Second",
            version="2.0.0",
            schema=_Schema,
            ingester=_AnotherIngester,
            files={"accepted_types": [".csv"]},
            hooks=[my_hook],
        )

        result = discover_ingestable_conventions()
        assert len(result) == 2
        assert result[0].title == "First"
        assert result[0].ingester_name == "test-ingester"
        assert result[1].title == "Second"
        assert result[1].ingester_name == "another-ingester"
