"""Tests for osa ingestion start command."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from osa.cli.ingestion import IngestionError, start_ingestion


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
            200, {"srn": "urn:osa:test.example.com:ingest:abc", "status": "started"}
        )

        result = start_ingestion(
            server="http://localhost:8000",
            convention_id="rcsb-pdb",
            token="fake-token",
            http=mock_client,
        )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "http://localhost:8000/api/v1/ingestions"
        assert call_args[1]["json"]["convention_id"] == "rcsb-pdb"
        assert result["status"] == "started"

    def test_default_batch_size_is_1000(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_id="test",
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
            convention_id="test",
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
            convention_id="test",
            token="my-token",
            http=mock_client,
        )

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer my-token"

    def test_raises_on_http_error(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            404, {"detail": "Convention not found"}
        )

        with pytest.raises(IngestionError, match="Convention not found"):
            start_ingestion(
                server="http://localhost:8000",
                convention_id="missing",
                token="fake-token",
                http=mock_client,
            )

    def test_limit_included_when_set(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_id="test",
            token="fake-token",
            limit=50,
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["limit"] == 50

    def test_limit_null_by_default(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000",
            convention_id="test",
            token="fake-token",
            http=mock_client,
        )

        payload = mock_client.post.call_args[1]["json"]
        assert payload["limit"] is None

    def test_strips_trailing_slash_from_server(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "started"})

        start_ingestion(
            server="http://localhost:8000/",
            convention_id="test",
            token="fake-token",
            http=mock_client,
        )

        url = mock_client.post.call_args[0][0]
        assert url == "http://localhost:8000/api/v1/ingestions"
