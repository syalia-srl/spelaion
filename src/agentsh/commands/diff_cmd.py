"""Diff command using Python difflib."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

from agentsh.commands._io import read_text
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("diff")
def cmd_diff(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    unified = False
    files: list[str] = []

    for a in args:
        if a == "-u":
            unified = True
        else:
            files.append(a)

    if len(files) < 2:
        io.stderr.write("diff: missing operand\n")
        return CommandResult(exit_code=1)

    content1 = read_text(files[0], state, vfs, io, "diff")
    content2 = read_text(files[1], state, vfs, io, "diff")
    if content1 is None or content2 is None:
        return CommandResult(exit_code=2)
    lines1 = content1.splitlines(keepends=True)
    lines2 = content2.splitlines(keepends=True)
    if unified:
        diff = difflib.unified_diff(lines1, lines2, fromfile=files[0], tofile=files[1])
    else:
        diff = difflib.ndiff(lines1, lines2)

    output = "".join(diff)
    if output:
        io.stdout.write(output)
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)
