"""Runtime state and event model package."""

from spelaion.runtime.events import EventKind, ExecutionEvent
from spelaion.runtime.options import ShellOptions
from spelaion.runtime.result import CommandResult
from spelaion.runtime.state import ShellState

__all__ = [
    "CommandResult",
    "EventKind",
    "ExecutionEvent",
    "ShellOptions",
    "ShellState",
]
