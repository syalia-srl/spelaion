"""Structured execution events for tracing and debugging."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class EventKind(Enum):
    """Categories of execution events."""

    PARSE = "parse"
    NORMALIZE = "normalize"
    EXPAND = "expand"
    RESOLVE = "resolve"
    PLAN = "plan"
    EXECUTE = "execute"
    BUILTIN = "builtin"
    TOOL_DISPATCH = "tool_dispatch"
    REDIRECT = "redirect"
    POLICY = "policy"


@dataclass
class ExecutionEvent:
    """A single event emitted during command execution."""

    kind: EventKind
    message: str
    data: dict[str, Any] | None = None
