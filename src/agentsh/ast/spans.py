"""Source span model for tracking positions in parsed Bash source text."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    """A zero-indexed line/column position in the source text."""

    row: int
    column: int

    def __str__(self) -> str:
        return f"{self.row}:{self.column}"


@dataclass(frozen=True, slots=True)
class Span:
    """A byte-offset range with line/column endpoints.

    Maps directly to tree-sitter's node range representation so that
    every AST node can be traced back to its source text.
    """

    start_byte: int
    end_byte: int
    start_point: Point
    end_point: Point

    @staticmethod
    def unknown() -> Span:
        """Return a sentinel span for synthetically created nodes."""
        return Span(0, 0, Point(0, 0), Point(0, 0))

    @property
    def length(self) -> int:
        """Byte length of the spanned region."""
        return self.end_byte - self.start_byte

    def __str__(self) -> str:
        return f"[{self.start_point}..{self.end_point}]"
