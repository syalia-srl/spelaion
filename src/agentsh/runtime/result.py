"""Result types for command execution.

Follows the Nushell pattern of span-attributed errors: every error
carries an optional source ``Span`` so callers can pinpoint the
failing construct in the original script.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.ast.spans import Span


@dataclass(frozen=True)
class ShellError:
    """A structured error with optional source location."""

    message: str
    span: Span | None = None
    command: str = ""
    exit_code: int = 1


@dataclass
class CommandResult:
    """Captures exit code, output streams, and optional structured error."""

    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error: ShellError | None = None

    @staticmethod
    def success(stdout: str = "") -> CommandResult:
        return CommandResult(exit_code=0, stdout=stdout)

    @staticmethod
    def fail(
        exit_code: int = 1,
        stderr: str = "",
        error: ShellError | None = None,
    ) -> CommandResult:
        return CommandResult(exit_code=exit_code, stderr=stderr, error=error)
