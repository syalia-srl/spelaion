"""spelaion: a bash for agents, run from Python, with nothing real behind it."""

__version__ = "0.1.0"

import logging
from typing import TYPE_CHECKING, Any

from spelaion._host import HostContext, HostHandler
from spelaion._tools import Tool, ToolOutput
from spelaion._types import Attachment, Limits, Result
from spelaion.api.bash import (
    Bash,
    CommandContext,
    CustomCommand,
    RunResult,
    define_command,
)
from spelaion.sandbox import Sandbox
from spelaion.vfs.mounts import Mount

if TYPE_CHECKING:
    from spelaion._mcp import McpServer

# A library logs; the application decides where it goes.
logging.getLogger("spelaion").addHandler(logging.NullHandler())


def __getattr__(name: str) -> Any:
    # The child imports this package; mcp and uvicorn load only when asked for.
    if name == "McpServer":
        from spelaion._mcp import McpServer

        return McpServer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(globals()))


__all__ = [
    "Attachment",
    "Bash",
    "CommandContext",
    "CustomCommand",
    "HostContext",
    "HostHandler",
    "Limits",
    "McpServer",
    "Mount",
    "Result",
    "RunResult",
    "Sandbox",
    "Tool",
    "ToolOutput",
    "define_command",
]
