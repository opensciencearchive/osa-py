"""Tests for the mandatory-docs deploy gate (#151, US2).

``purpose`` and ``examples`` are required parameters of ``convention()`` — an
undocumented convention cannot even be registered. The deploy pre-flight
mirrors the server rule (purpose non-empty ∧ ≥3 distinct trigger questions
counting worked-example questions ∧ ≥1 Example) and fails **before any network
call or image build**, naming each gap. There is no skip flag.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from osa._registry import clear
from osa.types.schema import MetadataSchema


class GateSchema(MetadataSchema):
    __schema_id__ = "gate-schema"

    organism: str


class TestExampleModel:
    def test_construct(self) -> None:
        from osa import Example

        ex = Example(
            question="Which alloys stay ductile below -40C?",
            query='POST /api/v1/data/alloy-tests/records {"filter": {}}',
            interpretation="Rows are individual test coupons.",
        )
        assert ex.question.startswith("Which alloys")
        assert ex.query.startswith("POST")
        assert ex.interpretation

    def test_frozen(self) -> None:
        from osa import Example

        ex = Example(question="q?", query="GET /x", interpretation="means x")
        with pytest.raises(Exception):
            ex.question = "other"  # type: ignore[misc]


def _examples(n: int = 1) -> list:
    from osa import Example

    return [
        Example(question=f"question {i}?", query="GET /x", interpretation="means x")
        for i in range(n)
    ]


def _register(purpose: str = "Test data.", *, example_questions=None, examples=None):
    from osa.authoring.convention import convention

    convention(
        title="Gate Convention",
        description="A gated convention",
        version="1.0.0",
        schema=GateSchema,
        files={"accepted_types": [".csv"], "max_count": 5, "max_file_size": 1000},
        hooks=[],
        purpose=purpose,
        example_questions=(
            example_questions
            if example_questions is not None
            else ["q1?", "q2?", "q3?"]
        ),
        examples=examples if examples is not None else _examples(),
    )


class TestConventionRequiresDocs:
    def setup_method(self) -> None:
        clear()

    def test_purpose_and_examples_are_required_parameters(self) -> None:
        from osa.authoring.convention import convention

        with pytest.raises(TypeError):
            convention(
                title="No Docs",
                description="x",
                version="1.0.0",
                schema=GateSchema,
                files={},
                hooks=[],
            )

    def test_registers_docs_on_convention_info(self) -> None:
        from osa._registry import _conventions

        _register()
        conv = _conventions[0]
        assert conv.purpose == "Test data."
        assert conv.example_questions == ["q1?", "q2?", "q3?"]
        assert len(conv.examples) == 1
        assert conv.when_not_to_use is None
        assert conv.see_also is None


class TestDeployPreFlightGate:
    def setup_method(self) -> None:
        clear()

    def _deploy(self):
        from osa.cli.deploy import deploy

        with (
            patch("osa.cli.deploy._build_hook_image") as build,
            patch("osa.cli.deploy.httpx.post") as post,
        ):
            build.side_effect = AssertionError("image build ran before docs gate")
            post.side_effect = AssertionError("network call ran before docs gate")
            deploy(server="http://localhost:8000")

    def test_blocks_empty_purpose_before_any_network_call(self) -> None:
        from osa.cli.deploy import DeployError

        _register(purpose="   ")
        with pytest.raises(DeployError, match="purpose"):
            self._deploy()

    def test_blocks_too_few_distinct_questions(self) -> None:
        from osa.cli.deploy import DeployError

        _register(example_questions=["q1?"], examples=_examples(1))
        # 1 trigger + 1 distinct worked-example question = 2 distinct < 3.
        with pytest.raises(DeployError, match="trigger questions"):
            self._deploy()

    def test_worked_example_questions_count_toward_three(self) -> None:
        # 2 trigger + 1 distinct worked-example question = 3 distinct → gate passes
        # (deploy then proceeds and fails on the mocked network — proving the
        # gate itself let it through).
        _register(example_questions=["q1?", "q2?"], examples=_examples(1))
        with pytest.raises(AssertionError, match="network call"):
            self._deploy()

    def test_error_names_each_gap(self) -> None:
        from osa.cli.deploy import DeployError

        _register(purpose="", example_questions=[], examples=[])
        with pytest.raises(DeployError) as exc_info:
            self._deploy()
        message = str(exc_info.value)
        assert "purpose" in message
        assert "trigger questions" in message
        assert "examples" in message
        assert "Gate Convention" in message


class TestDeployPayloadEmitsDocs:
    def setup_method(self) -> None:
        clear()

    def test_payload_carries_required_docs_block(self) -> None:
        from osa._registry import _conventions
        from osa.cli.deploy import build_manifest

        _register()
        docs = build_manifest(_conventions[0]).docs
        assert docs.purpose == "Test data."
        assert docs.example_questions == ["q1?", "q2?", "q3?"]
        assert [e.model_dump() for e in docs.examples] == [
            {"question": "question 0?", "query": "GET /x", "interpretation": "means x"}
        ]

    def test_payload_carries_optional_docs_fields(self) -> None:
        from osa._registry import _conventions
        from osa.authoring.convention import convention

        convention(
            title="Full Docs",
            description="x",
            version="1.0.0",
            schema=GateSchema,
            files={},
            hooks=[],
            purpose="Full docs data.",
            example_questions=["q1?", "q2?", "q3?"],
            examples=_examples(),
            when_not_to_use="Not for X.",
            see_also=["https://other-node.example.org"],
        )
        from osa.cli.deploy import build_manifest

        docs = build_manifest(_conventions[0]).docs
        assert docs.when_not_to_use == "Not for X."
        assert docs.see_also == ["https://other-node.example.org"]
