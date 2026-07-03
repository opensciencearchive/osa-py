"""Worked example for convention documentation (#151)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Example(BaseModel):
    """An author-supplied worked example, rendered verbatim into the node's
    reference documentation.

    ``query`` is opaque to the platform — typically a FilterExpr POST or a URL.
    It is never parsed, executed, or validated.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    query: str
    interpretation: str
