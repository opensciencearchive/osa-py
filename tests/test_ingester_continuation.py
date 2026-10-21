"""Continuation is the session, and only the session (#227).

`pull()` used to advertise an `offset` cursor that the server never populated,
so `OSA_OFFSET` was never emitted and the parameter arrived as 0 on every
batch. The two obvious implementations both failed, in opposite directions:
slice by `offset` and set a session and the run loops forever; slice by
`offset` and set none and the run truncates after batch 0 while still logging
success. `since` was dead in exactly the same way.

These pin the argument list `pull()` is actually called with, and pin the
harness's batch loop — the thing that lets an author catch a stall on their
own machine instead of in production.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from osa._registry import IngesterInfo, _ingesters, clear
from osa.authoring.ingester import Ingester
from osa.runtime.ingester_context import IngesterContext
from osa.runtime.ingester_entrypoint import run_ingester_entrypoint
from osa.testing.harness import StalledIngesterError, run_ingester_batches
from osa.types.ingester import IngesterRecord

ITEMS = [f"item-{i}" for i in range(7)]


class RecordingIngester:
    """Records the keyword arguments pull() was handed."""

    name = "recording"
    schedule = None
    initial_run = None
    max_file_mb = None

    calls: list[dict[str, Any]] = []

    def __init__(self, config=None) -> None:
        pass

    async def pull(self, **kwargs: Any) -> AsyncIterator[IngesterRecord]:
        self.__class__.calls.append(kwargs)
        yield IngesterRecord(source_id="rec-1", metadata={}, files=[])


class SessionPaginatingIngester:
    """The contract, done right: read the start position out of `session`."""

    name = "paginating"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        start = int((session or {}).get("offset", 0))
        window = ITEMS[start : start + limit] if limit is not None else ITEMS[start:]
        for item in window:
            yield IngesterRecord(source_id=item, metadata={}, files=[])
        next_start = start + len(window)
        # Setting no session on the final batch is what ends the run.
        if next_start < len(ITEMS):
            ctx.set_session({"offset": next_start, "total": len(ITEMS)})


class StallingIngester:
    """The #227 bug: slices by a position it never advances, always sets a session."""

    name = "stalling"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        window = ITEMS[:limit] if limit is not None else ITEMS
        for item in window:
            yield IngesterRecord(source_id=item, metadata={}, files=[])
        ctx.set_session({"offset": len(window), "total": len(ITEMS)})


class InPlaceSessionIngester:
    """Advances by mutating the session dict it was handed, then setting it.

    Legal — the server hands over a dict parsed from session.json, so mutating
    it mutates nothing the server keeps. The harness has to match that, or it
    reports a stall the production runtime would never see.
    """

    name = "in-place"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        state = session if session is not None else {"offset": 0}
        start = int(state["offset"])
        window = ITEMS[start : start + limit] if limit is not None else ITEMS[start:]
        for item in window:
            yield IngesterRecord(source_id=item, metadata={}, files=[])
        state["offset"] = start + len(window)
        if state["offset"] < len(ITEMS):
            ctx.set_session(state)


class InPlaceRescanIngester:
    """Advances in place while legitimately re-emitting the same ids each page.

    The server compares the session it wrote with the one it read back, so an
    in-place update is plainly an advance. A harness that hands the ingester
    its own copy sees the same thing; one that hands over the object it keeps
    for comparison sees no change at all, and calls this a stall.
    """

    name = "in-place-rescan"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        state = session if session is not None else {"page": 0}
        page = int(state["page"])
        for item in ITEMS[:2]:
            yield IngesterRecord(source_id=item, metadata={}, files=[])
        state["page"] = page + 1
        if state["page"] < 3:
            ctx.set_session(state)


class UnserializableSessionIngester:
    """Sets a session the runtime could not write to session.json."""

    name = "unserializable"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        yield IngesterRecord(source_id="rec-1", metadata={}, files=[])
        ctx.set_session({"cursor": datetime(2026, 1, 1, tzinfo=UTC)})


class EmptyPageIngester:
    """Returns nothing while still setting an advancing session."""

    name = "empty-page"
    schedule = None
    initial_run = None
    max_file_mb = None

    async def pull(
        self,
        *,
        ctx: IngesterContext,
        limit: int | None = None,
        session: dict[str, Any] | None = None,
    ) -> AsyncIterator[IngesterRecord]:
        start = int((session or {}).get("offset", 0))
        if start == 0:
            yield IngesterRecord(source_id="rec-1", metadata={}, files=[])
        ctx.set_session({"offset": start + 1})


class TestPullProtocol:
    def test_protocol_has_no_offset_or_since(self) -> None:
        params = inspect.signature(Ingester.pull).parameters
        assert "offset" not in params
        assert "since" not in params

    def test_protocol_keeps_session(self) -> None:
        assert "session" in inspect.signature(Ingester.pull).parameters


class TestEntrypointArguments:
    def setup_method(self) -> None:
        clear()
        RecordingIngester.calls = []
        _ingesters.append(
            IngesterInfo(
                ingester_cls=RecordingIngester, name="recording", max_file_mb=None
            )
        )

    def _run(self, tmp_path: Path) -> dict[str, Any]:
        input_dir = tmp_path / "in"
        input_dir.mkdir()
        (input_dir / "config.json").write_text("{}")
        assert (
            run_ingester_entrypoint(
                input_dir=input_dir,
                output_dir=tmp_path / "out",
                files_dir=tmp_path / "files",
            )
            == 0
        )
        return RecordingIngester.calls[-1]

    def test_pull_is_not_handed_an_offset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stale OSA_OFFSET in the environment must not resurrect the trap.
        monkeypatch.setenv("OSA_OFFSET", "500")
        assert "offset" not in self._run(tmp_path)

    def test_pull_is_not_handed_a_since(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OSA_SINCE", "2026-01-01T00:00:00+00:00")
        assert "since" not in self._run(tmp_path)

    def test_pull_is_handed_the_session_and_limit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OSA_LIMIT", "25")
        call = self._run(tmp_path)
        assert call["limit"] == 25
        assert call["session"] is None
        assert "ctx" in call


class TestRunIngesterBatches:
    """The harness drives the server's loop, so a stall fails on the laptop."""

    def test_paginates_through_every_record(self) -> None:
        result = run_ingester_batches(SessionPaginatingIngester, batch_size=3)
        assert [r.source_id for r in result.records] == ITEMS

    def test_reports_each_batch(self) -> None:
        result = run_ingester_batches(SessionPaginatingIngester, batch_size=3)
        assert [len(batch) for batch in result.batches] == [3, 3, 1]

    def test_stops_when_no_session_is_set(self) -> None:
        result = run_ingester_batches(SessionPaginatingIngester, batch_size=7)
        assert len(result.batches) == 1

    def test_a_single_batch_ingester_still_works(self) -> None:
        result = run_ingester_batches(SessionPaginatingIngester, batch_size=100)
        assert [r.source_id for r in result.records] == ITEMS

    def test_a_stalled_ingester_raises_instead_of_looping(self) -> None:
        with pytest.raises(StalledIngesterError) as exc:
            run_ingester_batches(StallingIngester, batch_size=3)
        assert "ctx.set_session" in str(exc.value)

    def test_stall_is_caught_on_the_second_batch(self) -> None:
        # Not after N batches of wasted work: the repeat is provable at once.
        with pytest.raises(StalledIngesterError) as exc:
            run_ingester_batches(StallingIngester, batch_size=3)
        assert "batch 1" in str(exc.value)

    def test_max_batches_bounds_a_pathological_ingester(self) -> None:
        with pytest.raises(StalledIngesterError):
            run_ingester_batches(StallingIngester, batch_size=3, max_batches=2)

    def test_limit_caps_the_total_pulled(self) -> None:
        result = run_ingester_batches(SessionPaginatingIngester, batch_size=3, limit=4)
        assert len(result.records) == 4


class TestBatchLoopMatchesTheRuntime:
    """The harness is only useful if a pass here means a pass in production.

    Each of these was a way the loop could disagree with the server: a limit
    met on the last allowed batch reported a stall, an in-place session update
    looked like no update at all, and a session the runtime cannot write to
    session.json sailed through.
    """

    def test_a_limit_met_on_the_last_allowed_batch_is_not_a_stall(self) -> None:
        # The limit used to be checked only at the top of the next iteration —
        # which never came, so the loop fell through to the exhaustion error.
        result = run_ingester_batches(
            SessionPaginatingIngester, batch_size=1, limit=1, max_batches=1
        )

        assert len(result.records) == 1

    def test_the_limit_still_stops_short_of_max_batches(self) -> None:
        result = run_ingester_batches(
            SessionPaginatingIngester, batch_size=2, limit=4, max_batches=100
        )

        assert len(result.records) == 4
        assert len(result.batches) == 2

    def test_an_in_place_session_update_is_not_a_stall(self) -> None:
        result = run_ingester_batches(InPlaceSessionIngester, batch_size=3)

        assert [r.source_id for r in result.records] == ITEMS

    def test_an_in_place_update_that_rescans_is_not_a_stall(self) -> None:
        # Advances the session in place, and re-emits the same ids every page —
        # the one case where comparing against a mutated input is a false stall.
        result = run_ingester_batches(InPlaceRescanIngester, batch_size=2)

        assert len(result.batches) == 3

    def test_a_session_the_runtime_cannot_write_is_rejected(self) -> None:
        # The runtime json.dumps()es the session between batches; a datetime
        # would blow up there, in a container, mid-run.
        with pytest.raises(TypeError, match="JSON-serializable"):
            run_ingester_batches(UnserializableSessionIngester, batch_size=1)

    def test_an_empty_batch_ends_the_run_like_the_server(self) -> None:
        # The server's has_more is `session is not None AND records > 0`, so an
        # empty page ends the run even with a cursor set. The harness mirrors
        # that deliberately: continuing instead would reopen the #227 loop,
        # since a repeated *empty* window is not evidence of a stall.
        result = run_ingester_batches(EmptyPageIngester, batch_size=1, max_batches=5)

        assert len(result.batches) == 2
        assert len(result.records) == 1
