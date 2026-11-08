"""Tool dispatch for agent tools.

Replaces external.py — no subprocess anywhere. Looks up command
in ToolRegistry. Not found → exit_code=127.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spelaion.runtime.result import CommandResult

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.tools.registry import ToolRegistry


def dispatch_tool(
    name: str,
    args: list[str],
    tools: ToolRegistry,
    io: IOContext,
    state: ShellState | None = None,
) -> CommandResult:
    """Dispatch a command to the tool registry.

    A tool with an ``invoke_in(state, args, stdin)`` method gets the calling
    shell's *state* through it. Returns 127 if not found.
    """
    tool = tools.lookup(name)
    if tool is None:
        io.stderr.write(f"spelaion: {name}: command not found\n")
        return CommandResult(exit_code=127, stderr=f"{name}: command not found")

    stdin_text = io.stdin.read() or None

    invoke_in = getattr(tool, "invoke_in", None)
    if state is not None and invoke_in is not None:
        result: CommandResult = invoke_in(state, args, stdin=stdin_text)
    else:
        result = tool.invoke(args, stdin=stdin_text)

    # Write outputs to IOContext
    if result.stdout:
        io.stdout.write(result.stdout)
    if result.stderr:
        io.stderr.write(result.stderr)

    return result
