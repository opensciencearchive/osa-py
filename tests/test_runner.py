"""Tests for the convention test runner (run_test service layer)."""

from __future__ import annotations

from pydantic import BaseModel

from osa.types.record import Record
from osa.types.schema import MetadataSchema


class RunnerSchema(MetadataSchema):
    __schema_id__ = "runner-test"

    title: str
    score: float


class FeatureOutput(BaseModel):
    label: str
    value: float


class TestRunTest:
    def setup_method(self) -> None:
        from osa._registry import clear

        clear()

    def _register_convention(
        self, *, hooks=None, ingester_cls=None, title="Test Convention"
    ):
        from osa.authoring.convention import convention
        from osa.authoring.hook import hook

        registered_hooks = []
        if hooks:
            for fn in hooks:
                registered_hooks.append(fn)
        else:

            @hook
            def noop_hook(record: Record[RunnerSchema]) -> None:
                pass

            registered_hooks.append(noop_hook)

        convention(
            title=title,
            version="1.0.0",
            schema=RunnerSchema,
            hooks=registered_hooks,
            ingester=ingester_cls,
            files={"accepted_types": [".txt"], "max_count": 1},
        )

        from osa._registry import _conventions

        return _conventions[-1]

    def _make_ingester(self, records_data=None):
        class TestIngester:
            name = "test-ingester"
            schedule = None
            initial_run = None
            max_file_mb = None

            async def pull(
                self, *, ctx, since=None, limit=None, offset=0, session=None
            ):
                from osa.types.ingester import IngesterRecord

                data = records_data or [
                    {"source_id": "R1", "title": "First", "score": 0.9},
                    {"source_id": "R2", "title": "Second", "score": 0.1},
                ]
                for item in data[:limit]:
                    source_id = str(item["source_id"])
                    file_ref = await ctx.add_bytes(source_id, "data.txt", data=b"test")
                    yield IngesterRecord(
                        source_id=source_id,
                        metadata={"title": item["title"], "score": item["score"]},
                        files=[file_ref],
                    )

        return TestIngester

    def test_runs_ingester_and_hooks(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.runner import run_test

        @hook
        def check(record: Record[RunnerSchema]) -> None:
            pass

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[check], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=1)
        assert result.convention_title == "Test Convention"
        assert result.ingester_name == "test-ingester"
        assert len(result.records) == 1
        assert result.records[0].source_id == "R1"

    def test_hook_pass_status(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.runner import run_test

        @hook
        def check(record: Record[RunnerSchema]) -> None:
            pass

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[check], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=1)
        assert result.records[0].hooks[0].status == "passed"

    def test_hook_reject_status(self) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.testing.runner import run_test

        @hook
        def check(record: Record[RunnerSchema]) -> None:
            raise Reject("Bad data")

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[check], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=1)
        assert result.records[0].hooks[0].status == "rejected"
        assert result.records[0].hooks[0].reason == "Bad data"

    def test_skip_after_reject(self) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.testing.runner import run_test

        @hook
        def validate(record: Record[RunnerSchema]) -> None:
            raise Reject("Nope")

        @hook
        def extract(record: Record[RunnerSchema]) -> list[FeatureOutput]:
            return [FeatureOutput(label="x", value=1.0)]

        ingester_cls = self._make_ingester()
        conv = self._register_convention(
            hooks=[validate, extract], ingester_cls=ingester_cls
        )

        result = run_test(convention_info=conv, limit=1)
        hooks = result.records[0].hooks
        assert hooks[0].status == "rejected"
        assert hooks[1].status == "skipped"

    def test_skip_after_error(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.runner import run_test

        @hook
        def broken(record: Record[RunnerSchema]) -> None:
            raise RuntimeError("crash")

        @hook
        def after(record: Record[RunnerSchema]) -> None:
            pass

        ingester_cls = self._make_ingester()
        conv = self._register_convention(
            hooks=[broken, after], ingester_cls=ingester_cls
        )

        result = run_test(convention_info=conv, limit=1)
        hooks = result.records[0].hooks
        assert hooks[0].status == "error"
        assert hooks[0].reason is not None
        assert "crash" in hooks[0].reason
        assert hooks[1].status == "skipped"

    def test_feature_hook_captures_result(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.runner import run_test

        @hook
        def extract(record: Record[RunnerSchema]) -> list[FeatureOutput]:
            return [FeatureOutput(label="pocket", value=42.0)]

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[extract], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=1)
        outcome = result.records[0].hooks[0]
        assert outcome.status == "passed"
        assert len(outcome.result) == 1
        assert outcome.result[0].value == 42.0

    def test_accepted_property(self) -> None:
        from osa.authoring.hook import hook
        from osa.authoring.validator import Reject
        from osa.testing.runner import run_test

        @hook
        def check(record: Record[RunnerSchema]) -> None:
            if record.metadata.score < 0.5:
                raise Reject("Score too low")

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[check], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=2)
        assert result.records[0].accepted is True
        assert result.records[1].accepted is False

    def test_no_ingester_raises(self) -> None:
        import pytest

        from osa.testing.runner import TestError, run_test

        conv = self._register_convention()

        with pytest.raises(TestError, match="no ingester"):
            run_test(convention_info=conv, limit=1)

    def test_multiple_records(self) -> None:
        from osa.authoring.hook import hook
        from osa.testing.runner import run_test

        @hook
        def check(record: Record[RunnerSchema]) -> None:
            pass

        ingester_cls = self._make_ingester()
        conv = self._register_convention(hooks=[check], ingester_cls=ingester_cls)

        result = run_test(convention_info=conv, limit=2)
        assert len(result.records) == 2
        assert result.records[0].source_id == "R1"
        assert result.records[1].source_id == "R2"
