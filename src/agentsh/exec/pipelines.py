"""Pipeline execution using in-memory string buffers.

No subprocess. stdout→stdin between stages via StringIO.
"""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO

from agentsh.exec.redirs import IOContext
from agentsh.runtime.result import CommandResult


def execute_pipeline(
    commands: list[Callable[[IOContext], CommandResult]],
    input_text: str = "",
    pipefail: bool = False,
) -> CommandResult:
    """Execute a pipeline of commands connected by in-memory buffers.

    Each command is a callable that takes an IOContext and returns CommandResult.
    """
    if not commands:
        return CommandResult(exit_code=0)

    if len(commands) == 1:
        io = IOContext(stdin=StringIO(input_text))
        return commands[0](io)

    statuses: list[int] = []
    current_input = input_text

    for cmd_fn in commands:
        io = IOContext(stdin=StringIO(current_input))
        result = cmd_fn(io)
        statuses.append(result.exit_code)
        current_input = io.stdout.getvalue()

    all_stdout = current_input  # last command's stdout

    # pipefail: exit status is the rightmost non-zero status
    if pipefail:
        for status in reversed(statuses):
            if status != 0:
                return CommandResult(exit_code=status, stdout=all_stdout)

    return CommandResult(
        exit_code=statuses[-1] if statuses else 0,
        stdout=all_stdout,
    )
