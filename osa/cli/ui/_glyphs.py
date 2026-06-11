"""Glyph vocabulary and shared formatting for CLI output."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GlyphSet:
    check: str
    cross: str
    warn: str
    arrow: str
    skip: str
    bar_done: str
    bar_head: str
    bar_todo: str
    tail: str
    spinner: tuple[str, ...]


UNICODE = GlyphSet(
    check="✓",
    cross="✗",
    warn="⚠",
    arrow="→",
    skip="−",
    bar_done="━",
    bar_head="╸",
    bar_todo="─",
    tail="│",
    spinner=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
)

ASCII = GlyphSet(
    check="+",
    cross="x",
    warn="!",
    arrow="->",
    skip="-",
    bar_done="=",
    bar_head=">",
    bar_todo="-",
    tail="|",
    spinner=("-", "\\", "|", "/"),
)


def glyphs_for(legacy_windows: bool = False) -> GlyphSet:
    return ASCII if legacy_windows else UNICODE


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes}m{rest:02d}s"
