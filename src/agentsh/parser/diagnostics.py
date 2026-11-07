"""Parser diagnostics for syntax errors and warnings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.ast.spans import Span


class DiagnosticSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    severity: DiagnosticSeverity
    message: str
    span: Span

    def __str__(self) -> str:
        loc = f"{self.span.start_point.row + 1}:{self.span.start_point.column}"
        return f"{self.severity.value}: {self.message} at {loc}"


class UnsupportedSyntaxError(Exception):
    """Raised when the parser encounters unsupported syntax."""

    def __init__(self, message: str, node_type: str = "") -> None:
        self.node_type = node_type
        super().__init__(message)
