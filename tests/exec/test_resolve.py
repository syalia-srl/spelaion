"""Tests for command resolution ordering.

Verifies the three-tier resolution order:
  function -> builtin -> agent_tool -> not_found
"""

from __future__ import annotations

import pytest

from agentsh.ast.nodes import FunctionDef, Group, SimpleCommand
from agentsh.ast.spans import Point, Span
from agentsh.runtime.result import CommandResult
from agentsh.runtime.state import ShellState
from agentsh.semantics.resolve import BUILTIN_NAMES, ResolvedCommand, resolve_command
from agentsh.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DUMMY_SPAN = Span(0, 0, Point(0, 0), Point(0, 0))


def _dummy_function_def(name: str) -> FunctionDef:
    """Create a minimal FunctionDef for testing."""
    body = Group(
        body=SimpleCommand(words=(), assignments=(), redirections=(), span=_DUMMY_SPAN),
        span=_DUMMY_SPAN,
    )
    return FunctionDef(name=name, body=body, span=_DUMMY_SPAN)


class _FakeTool:
    """Minimal concrete implementation satisfying AgentTool protocol."""

    def __init__(self, tool_name: str) -> None:
        self._name = tool_name

    @property
    def name(self) -> str:
        return self._name

    def invoke(
        self,
        args: list[str],
        stdin: str | None = None,
    ) -> CommandResult:
        return CommandResult(exit_code=0, stdout="", stderr="")


@pytest.fixture()
def empty_state() -> ShellState:
    return ShellState()


@pytest.fixture()
def empty_registry() -> ToolRegistry:
    return ToolRegistry()


# ---------------------------------------------------------------------------
# Function takes precedence over builtin
# ---------------------------------------------------------------------------


class TestFunctionPrecedence:
    """A user-defined function should shadow a builtin of the same name."""

    def test_function_shadows_builtin(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        # "echo" is a builtin, but defining a function named "echo" should win
        empty_state.functions["echo"] = _dummy_function_def("echo")
        result = resolve_command("echo", empty_state, empty_registry)
        assert result.kind == "function"
        assert result.name == "echo"

    def test_function_shadows_agent_tool(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        empty_state.functions["mytool"] = _dummy_function_def("mytool")
        empty_registry.register("mytool", _FakeTool("mytool"))
        result = resolve_command("mytool", empty_state, empty_registry)
        assert result.kind == "function"


# ---------------------------------------------------------------------------
# Builtin takes precedence over agent tool
# ---------------------------------------------------------------------------


class TestBuiltinPrecedence:
    """Builtins should be resolved before agent tools."""

    def test_builtin_shadows_agent_tool(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        # Register an agent tool with the same name as a builtin
        empty_registry.register("cd", _FakeTool("cd"))
        result = resolve_command("cd", empty_state, empty_registry)
        assert result.kind == "builtin"
        assert result.name == "cd"


# ---------------------------------------------------------------------------
# Agent tool resolution
# ---------------------------------------------------------------------------


class TestAgentToolResolution:
    """Agent tools should be found when no function or builtin matches."""

    def test_agent_tool_resolved(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        empty_registry.register("deploy", _FakeTool("deploy"))
        result = resolve_command("deploy", empty_state, empty_registry)
        assert result.kind == "agent_tool"
        assert result.name == "deploy"


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------


class TestNotFound:
    """Unknown commands should return not_found."""

    def test_not_found(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        result = resolve_command("nonexistent", empty_state, empty_registry)
        assert result.kind == "not_found"
        assert result.name == "nonexistent"

    def test_empty_state_and_registry(
        self, empty_state: ShellState, empty_registry: ToolRegistry
    ) -> None:
        result = resolve_command("anything", empty_state, empty_registry)
        assert result.kind == "not_found"


# ---------------------------------------------------------------------------
# All builtins are recognized
# ---------------------------------------------------------------------------


class TestAllBuiltinsRecognized:
    """Every name in BUILTIN_NAMES should resolve as a builtin."""

    @pytest.mark.parametrize("name", sorted(BUILTIN_NAMES))
    def test_builtin_recognized(
        self,
        name: str,
        empty_state: ShellState,
        empty_registry: ToolRegistry,
    ) -> None:
        result = resolve_command(name, empty_state, empty_registry)
        assert result.kind == "builtin"
        assert result.name == name


# ---------------------------------------------------------------------------
# ResolvedCommand is frozen
# ---------------------------------------------------------------------------


class TestResolvedCommandImmutability:
    """ResolvedCommand instances should be immutable."""

    def test_frozen(self) -> None:
        rc = ResolvedCommand(kind="builtin", name="echo")
        with pytest.raises(AttributeError):
            rc.kind = "function"  # type: ignore[misc]
