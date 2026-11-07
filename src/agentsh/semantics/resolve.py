"""Command resolution: function -> builtin -> agent_tool -> not_found.

The virtual shell has no external-binary tier.  Resolution follows a strict
three-tier order:

1. **Shell functions** defined in the current :class:`ShellState`.
2. **Builtins** listed in :data:`BUILTIN_NAMES`.
3. **Agent tools** registered in the :class:`ToolRegistry`.

If none of the tiers match, the command is ``not_found``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from agentsh.commands._registry import COMMANDS

if TYPE_CHECKING:
    from agentsh.runtime.state import ShellState
    from agentsh.tools.registry import ToolRegistry

_SHELL_BUILTINS: frozenset[str] = frozenset(
    {
        "cd",
        "pwd",
        "echo",
        "printf",
        "export",
        "unset",
        "true",
        "false",
        "test",
        "[",
        "[[",
        "exit",
        "source",
        ".",
        "read",
        "shift",
        "return",
        "break",
        "continue",
        "local",
        "declare",
        "set",
        "alias",
        "unalias",
        "type",
        "readonly",
        "let",
        "getopts",
        "hash",
        "help",
        "eval",
        "exec",
        "trap",
        "ulimit",
        "umask",
        "wait",
        "jobs",
        "bg",
        "fg",
        "times",
    }
)

BUILTIN_NAMES: frozenset[str] = _SHELL_BUILTINS | frozenset(COMMANDS.keys())


@dataclass(frozen=True)
class ResolvedCommand:
    """Result of command name resolution.

    Attributes:
        kind: Which tier the command was resolved in.
        name: The original command name.
    """

    kind: Literal["function", "builtin", "agent_tool", "not_found"]
    name: str


def resolve_command(
    name: str,
    state: ShellState,
    tools: ToolRegistry,
) -> ResolvedCommand:
    """Resolve *name* through the three-tier lookup order.

    Parameters:
        name: The command name to resolve.
        state: Current shell state (checked for user-defined functions).
        tools: The agent tool registry.

    Returns:
        A :class:`ResolvedCommand` indicating the resolution tier.
    """
    # 1. Shell function
    if name in state.functions:
        return ResolvedCommand(kind="function", name=name)

    # 2. Builtin
    if name in BUILTIN_NAMES:
        return ResolvedCommand(kind="builtin", name=name)

    # 3. Agent tool
    if tools.has(name):
        return ResolvedCommand(kind="agent_tool", name=name)

    # Not found
    return ResolvedCommand(kind="not_found", name=name)
