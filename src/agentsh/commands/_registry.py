"""Command registry — @command decorator and COMMANDS dict."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.result import CommandResult
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem

CommandFn = Callable[
    ["list[str]", "ShellState", "VirtualFilesystem", "IOContext"],
    "CommandResult",
]

COMMANDS: dict[str, CommandFn] = {}


def command(*names: str) -> Callable[[CommandFn], CommandFn]:
    """Register a function as a virtual command under one or more names."""

    def decorator(fn: CommandFn) -> CommandFn:
        for name in names:
            COMMANDS[name] = fn
        return fn

    return decorator
