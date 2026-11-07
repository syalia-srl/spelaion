"""Tests for the tool registry.

Covers:
- Register and lookup
- Lookup missing returns None
- list_tools returns sorted names
- has() works correctly
"""

from __future__ import annotations

import pytest

from agentsh.runtime.result import CommandResult
from agentsh.tools.registry import AgentTool, ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubTool:
    """Concrete tool implementation for testing."""

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
        return CommandResult(
            exit_code=0,
            stdout=f"executed {self._name} with {args}",
        )


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


# ---------------------------------------------------------------------------
# Register and lookup
# ---------------------------------------------------------------------------


class TestRegisterAndLookup:
    """Tools can be registered and retrieved by name."""

    def test_register_and_lookup(self, registry: ToolRegistry) -> None:
        tool = _StubTool("grep")
        registry.register("grep", tool)
        found = registry.lookup("grep")
        assert found is tool

    def test_register_multiple(self, registry: ToolRegistry) -> None:
        t1 = _StubTool("alpha")
        t2 = _StubTool("beta")
        registry.register("alpha", t1)
        registry.register("beta", t2)
        assert registry.lookup("alpha") is t1
        assert registry.lookup("beta") is t2

    def test_register_overwrites(self, registry: ToolRegistry) -> None:
        t1 = _StubTool("x")
        t2 = _StubTool("x")
        registry.register("x", t1)
        registry.register("x", t2)
        assert registry.lookup("x") is t2

    def test_protocol_check(self) -> None:
        """_StubTool should satisfy the AgentTool protocol."""
        tool = _StubTool("test")
        assert isinstance(tool, AgentTool)


# ---------------------------------------------------------------------------
# Lookup missing returns None
# ---------------------------------------------------------------------------


class TestLookupMissing:
    """Looking up an unregistered name should return None."""

    def test_lookup_missing(self, registry: ToolRegistry) -> None:
        assert registry.lookup("nonexistent") is None

    def test_lookup_empty_registry(self, registry: ToolRegistry) -> None:
        assert registry.lookup("anything") is None

    def test_lookup_after_register_different_name(self, registry: ToolRegistry) -> None:
        registry.register("alpha", _StubTool("alpha"))
        assert registry.lookup("beta") is None


# ---------------------------------------------------------------------------
# list_tools returns sorted names
# ---------------------------------------------------------------------------


class TestListTools:
    """list_tools should return all registered names in sorted order."""

    def test_empty_registry(self, registry: ToolRegistry) -> None:
        assert registry.list_tools() == []

    def test_single_tool(self, registry: ToolRegistry) -> None:
        registry.register("deploy", _StubTool("deploy"))
        assert registry.list_tools() == ["deploy"]

    def test_sorted_order(self, registry: ToolRegistry) -> None:
        for name in ["zebra", "alpha", "middle"]:
            registry.register(name, _StubTool(name))
        assert registry.list_tools() == ["alpha", "middle", "zebra"]

    def test_overwrite_does_not_duplicate(self, registry: ToolRegistry) -> None:
        registry.register("tool", _StubTool("tool"))
        registry.register("tool", _StubTool("tool"))
        assert registry.list_tools() == ["tool"]


# ---------------------------------------------------------------------------
# has() works
# ---------------------------------------------------------------------------


class TestHas:
    """has() should return True for registered tools, False otherwise."""

    def test_has_registered(self, registry: ToolRegistry) -> None:
        registry.register("search", _StubTool("search"))
        assert registry.has("search") is True

    def test_has_unregistered(self, registry: ToolRegistry) -> None:
        assert registry.has("missing") is False

    def test_has_after_multiple_registrations(self, registry: ToolRegistry) -> None:
        registry.register("a", _StubTool("a"))
        registry.register("b", _StubTool("b"))
        assert registry.has("a") is True
        assert registry.has("b") is True
        assert registry.has("c") is False


# ---------------------------------------------------------------------------
# Tool invocation through registry
# ---------------------------------------------------------------------------


class TestToolInvocation:
    """A looked-up tool should be callable."""

    def test_invoke_through_registry(self, registry: ToolRegistry) -> None:
        tool = _StubTool("echo")
        registry.register("echo", tool)
        found = registry.lookup("echo")
        assert found is not None
        result = found.invoke(["hello", "world"])
        assert result.exit_code == 0
        assert "echo" in result.stdout
        assert "hello" in result.stdout

    def test_invoke_with_stdin(self, registry: ToolRegistry) -> None:
        tool = _StubTool("cat")
        registry.register("cat", tool)
        found = registry.lookup("cat")
        assert found is not None
        result = found.invoke([], stdin="input data")
        assert result.exit_code == 0
