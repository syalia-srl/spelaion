"""python and python3: run by the sandbox child when it has python, else absent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from spelaion.commands._registry import CommandFn, command
from spelaion.runtime.result import CommandResult

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem

# Holds the runner once the sandbox child installs one.
_runner: list[CommandFn] = []


def install(runner: CommandFn) -> None:
    """Run ``python`` and ``python3`` with *runner* in this process."""
    _runner[:] = [runner]


def _register(name: str) -> None:
    def run(
        args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
    ) -> CommandResult:
        if not _runner:
            io.stderr.write(f"{name}: not available in this sandbox\n")
            return CommandResult(exit_code=127)
        return _runner[0](args, state, vfs, io)

    command(name)(run)


_register("python")
_register("python3")
