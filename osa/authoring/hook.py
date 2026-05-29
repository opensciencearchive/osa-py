"""Unified @hook decorator — replaces @validator and @transform."""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import overload

from osa._registry import register
from osa.types.ingester import Limits


@overload
def hook(fn: types.FunctionType, /) -> types.FunctionType: ...
@overload
def hook(*, limits: Limits) -> Callable[[types.FunctionType], types.FunctionType]: ...


def hook(
    fn: types.FunctionType | None = None, /, *, limits: Limits | None = None
) -> types.FunctionType | Callable[[types.FunctionType], types.FunctionType]:
    """Decorator that marks a function as an OSA hook.

    Registers the function in the global hook registry and
    introspects type hints to extract the schema type, output type,
    and cardinality (``-> T`` = one, ``-> list[T]`` = many).

    Can be used bare (``@hook``) or with limits (``@hook(limits=Limits(memory="2g"))``).
    """

    def _register(f: types.FunctionType) -> types.FunctionType:
        register(f, "hook", limits=limits)
        return f

    if fn is not None:
        return _register(fn)
    return _register
