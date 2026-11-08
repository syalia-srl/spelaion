"""spelaion — Virtual Bash parser and agent executor."""

__version__ = "0.1.0"

from spelaion._host import HostContext, HostHandler
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

__all__ = [
    "Attachment",
    "Bash",
    "CommandContext",
    "CustomCommand",
    "HostContext",
    "HostHandler",
    "Limits",
    "Mount",
    "Result",
    "RunResult",
    "Sandbox",
    "define_command",
]
