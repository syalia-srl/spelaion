"""Tool registry for agent-provided commands."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agentsh.runtime.result import CommandResult


@runtime_checkable
class AgentTool(Protocol):
    """Protocol that every agent tool must satisfy.

    A tool has a *name* (used for command resolution) and an *invoke*
    method that accepts argv-style arguments plus optional stdin text
    and returns a :class:`CommandResult`.
    """

    @property
    def name(self) -> str:
        """The canonical name of this tool."""
        ...

    def invoke(
        self,
        args: list[str],
        stdin: str | None = None,
    ) -> CommandResult:
        """Execute the tool with the given arguments and optional stdin."""
        ...


class ToolRegistry:
    """Registry that maps tool names to :class:`AgentTool` instances.

    Tools are registered by name and looked up during command resolution.
    """

    def __init__(self) -> None:
        self._tools: dict[str, AgentTool] = {}

    def register(self, name: str, tool: AgentTool) -> None:
        """Register a tool under the given *name*."""
        self._tools[name] = tool

    def lookup(self, name: str) -> AgentTool | None:
        """Return the tool registered under *name*, or ``None``."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def has(self, name: str) -> bool:
        """Return True if a tool is registered under *name*."""
        return name in self._tools
