"""Tests for osa ingestion start command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from osa.cli.ingestion import IngestionError, build_convention_srn, start_ingestion


def _make_response(status_code: int, json_data: dict) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "http://localhost:8000/api/v1/ingestions"),
    )


class TestStartIngestion:
    def test_posts_to_ingestions_endpoint(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            200, {"srn": "urn:osa:localhost:ingest:abc", "status": "started"}
        )

        result = start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:rcsb-pdb@1.0.0",
            token="fake-token",
            http=mock_client,
        )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8000/api/v1/ingestions"
        assert (
            call_args[1]["json"]["convention_srn"]
            == "urn:osa:localhost:conv:rcsb-pdb@1.0.0"
        )
        assert result["srn"] == "urn:osa:localhost:ingest:abc"

    def test_default_batch_size_is_1000(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="fake-token",
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["batch_size"] == 1000

    def test_custom_batch_size(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="fake-token",
            batch_size=500,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["batch_size"] == 500

    def test_sends_bearer_token(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="my-token",
            http=mock_client,
        )

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-token"

    def test_raises_on_http_error(self) -> None:
        mock_client = MagicMock(spec=httpx)
        resp = _make_response(404, {"detail": "Convention not found"})
        mock_client.post.return_value = resp

        with pytest.raises(IngestionError, match="Convention not found"):
            start_ingestion(
                server="http://localhost:8000",
                convention_srn="urn:osa:localhost:conv:missing@1.0.0",
                token="fake-token",
                http=mock_client,
            )

    def test_limit_included_when_set(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="fake-token",
            limit=50,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["limit"] == 50

    def test_limit_omitted_by_default(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="fake-token",
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert "limit" not in payload

    def test_strips_trailing_slash_from_server(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000/",
            convention_srn="urn:osa:localhost:conv:test@1.0.0",
            token="fake-token",
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
