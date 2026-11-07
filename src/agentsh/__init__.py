"""agentsh — Virtual Bash parser and agent executor."""

__version__ = "0.1.0"

from agentsh.api.bash import (
    Bash,
    CommandContext,
    CustomCommand,
    Limits,
    RunResult,
    define_command,
)

__all__ = [
    "Bash",
    "CommandContext",
    "CustomCommand",
    "Limits",
    "RunResult",
    "define_command",
]
