"""Tool dispatch for agent tools.

Replaces external.py — no subprocess anywhere. Looks up command
in ToolRegistry. Not found → exit_code=127.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.tools.registry import ToolRegistry


def dispatch_tool(
    name: str,
    args: list[str],
    tools: ToolRegistry,
    io: IOContext,
) -> CommandResult:
    """Dispatch a command to the tool registry.

    Returns 127 if not found.
    """
    tool = tools.lookup(name)
    if tool is None:
        io.stderr.write(f"agentsh: {name}: command not found\n")
        return CommandResult(exit_code=127, stderr=f"{name}: command not found")

    stdin_text = io.stdin.read() or None

    result = tool.invoke(args, stdin=stdin_text)

    # Write outputs to IOContext
    if result.stdout:
        io.stdout.write(result.stdout)
    if result.stderr:
        io.stderr.write(result.stderr)

    return result
