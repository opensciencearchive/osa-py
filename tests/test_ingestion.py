"""Tests for osa ingestion start command."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from osa.cli.ingestion import IngestionError, cancel_ingestion, start_ingestion


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


class TestCancelIngestion:
    """`osa ingestion cancel` — the operator's stop lever (#227).

    Before this, a runaway run could only be stopped by stopping the server.
    """

    def test_posts_to_the_cancel_endpoint(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            200, {"id": "run-1", "status": "cancelled", "published_count": 1000}
        )

        result = cancel_ingestion(
            server="http://localhost:8000",
            ingest_run_id="run-1",
            token="fake-token",
            http=mock_client,
        )

        assert (
            mock_client.post.call_args[0][0]
            == "http://localhost:8000/api/v1/ingestions/run-1/cancel"
        )
        assert result["status"] == "cancelled"

    def test_sends_the_bearer_token(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "cancelled"})

        cancel_ingestion(
            server="http://localhost:8000",
            ingest_run_id="run-1",
            token="fake-token",
            http=mock_client,
        )

        headers = mock_client.post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer fake-token"

    def test_strips_a_trailing_slash_from_the_server(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(200, {"status": "cancelled"})

        cancel_ingestion(
            server="http://localhost:8000/",
            ingest_run_id="run-1",
            token="fake-token",
            http=mock_client,
        )

        assert (
            mock_client.post.call_args[0][0]
            == "http://localhost:8000/api/v1/ingestions/run-1/cancel"
        )

    def test_conflict_is_reported_with_the_server_detail(self) -> None:
        # Cancelling a run that already finished is a 409, not a silent no-op.
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            409, {"detail": "Ingest run run-1 is already finished"}
        )

        with pytest.raises(IngestionError, match="already finished"):
            cancel_ingestion(
                server="http://localhost:8000",
                ingest_run_id="run-1",
                token="fake-token",
                http=mock_client,
            )

    def test_not_found_is_reported(self) -> None:
        mock_client = MagicMock(spec=httpx)
        mock_client.post.return_value = _make_response(
            404, {"detail": "Ingest run not found: nope"}
        )

        with pytest.raises(IngestionError, match="not found"):
            cancel_ingestion(
                server="http://localhost:8000",
                ingest_run_id="nope",
                token="fake-token",
                http=mock_client,
            )
