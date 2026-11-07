"""Tests for the agentsh LangChain tool wrappers.

Covers:
- create_agentsh_tools factory
- AgentShParseTool: valid script, invalid syntax
- AgentShPlanTool: plan output with steps
- AgentShRunTool: execution, exit codes, shared state across calls
- ast_to_dict helper
"""

from __future__ import annotations

import json

import pytest

from agentsh.langchain_tools.factory import create_agentsh_tools
from agentsh.langchain_tools.parse_tool import AgentShParseTool, ast_to_dict
from agentsh.langchain_tools.plan_tool import AgentShPlanTool
from agentsh.langchain_tools.run_tool import AgentShRunTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tools():
    """Create a fresh set of agentsh tools with a shared engine."""
    return create_agentsh_tools()


@pytest.fixture()
def parse_tool(tools):
    return tools[0]


@pytest.fixture()
def plan_tool(tools):
    return tools[1]


@pytest.fixture()
def run_tool(tools):
    return tools[2]


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestFactory:
    """Tests for create_agentsh_tools."""

    def test_returns_three_tools(self):
        """Factory returns exactly three tools."""
        result = create_agentsh_tools()
        assert len(result) == 3

    def test_returns_correct_types(self):
        """Factory returns parse, plan, and run tools in order."""
        parse, plan, run = create_agentsh_tools()
        assert isinstance(parse, AgentShParseTool)
        assert isinstance(plan, AgentShPlanTool)
        assert isinstance(run, AgentShRunTool)

    def test_tools_share_engine(self):
        """All three tools share the same ShellEngine instance."""
        parse, plan, run = create_agentsh_tools()
        assert parse.engine is plan.engine
        assert plan.engine is run.engine

    def test_tool_names(self):
        """Each tool should have the expected name."""
        parse, plan, run = create_agentsh_tools()
        assert parse.name == "agentsh_parse"
        assert plan.name == "agentsh_plan"
        assert run.name == "agentsh_run"

    def test_initial_vars(self):
        """Initial variables are accessible from the run tool."""
        _, _, run = create_agentsh_tools(initial_vars={"GREETING": "hi"})
        result = json.loads(run.invoke({"script": "echo $GREETING"}))
        assert result["stdout"] == "hi\n"


# ---------------------------------------------------------------------------
# Parse tool tests
# ---------------------------------------------------------------------------


class TestParseTool:
    """Tests for AgentShParseTool."""

    def test_parse_valid_script(self, parse_tool):
        """Parsing 'echo hello' returns has_errors=false and an ast."""
        raw = parse_tool.invoke({"script": "echo hello"})
        data = json.loads(raw)
        assert data["has_errors"] is False
        assert "ast" in data
        assert data["ast"]["type"] == "Program"

    def test_parse_ast_body_not_empty(self, parse_tool):
        """The AST body for a valid command should be non-empty."""
        data = json.loads(parse_tool.invoke({"script": "echo hello"}))
        assert len(data["ast"]["body"]) >= 1

    def test_parse_invalid_syntax(self, parse_tool):
        """Parsing invalid syntax returns has_errors=true."""
        raw = parse_tool.invoke({"script": "if; then"})
        data = json.loads(raw)
        assert data["has_errors"] is True

    def test_parse_invalid_has_diagnostics(self, parse_tool):
        """Invalid syntax should produce at least one diagnostic."""
        data = json.loads(parse_tool.invoke({"script": "if; then"}))
        assert len(data["diagnostics"]) >= 1

    def test_parse_empty_script(self, parse_tool):
        """Parsing an empty string should succeed with an empty body."""
        data = json.loads(parse_tool.invoke({"script": ""}))
        assert data["has_errors"] is False

    def test_parse_multiline_script(self, parse_tool):
        """Parsing a multiline script produces multiple body entries."""
        data = json.loads(parse_tool.invoke({"script": "echo a\necho b\n"}))
        assert data["has_errors"] is False
        body = data["ast"]["body"]
        assert len(body) >= 2

    def test_parse_assignment(self, parse_tool):
        """Parsing a variable assignment produces a SimpleCommand with assignments."""
        data = json.loads(parse_tool.invoke({"script": "X=hello"}))
        assert data["has_errors"] is False


# ---------------------------------------------------------------------------
# Plan tool tests
# ---------------------------------------------------------------------------


class TestPlanTool:
    """Tests for AgentShPlanTool."""

    def test_plan_valid_script(self, plan_tool):
        """Planning 'echo hello' returns has_errors=false and steps."""
        raw = plan_tool.invoke({"script": "echo hello"})
        data = json.loads(raw)
        assert data["has_errors"] is False
        assert "steps" in data
        assert isinstance(data["steps"], list)

    def test_plan_has_echo_step(self, plan_tool):
        """Plan for 'echo hello' should contain a step for the echo command."""
        data = json.loads(plan_tool.invoke({"script": "echo hello"}))
        commands = [s["command"] for s in data["steps"]]
        assert "echo" in commands

    def test_plan_step_fields(self, plan_tool):
        """Each plan step should have command, resolution, args, effects."""
        data = json.loads(plan_tool.invoke({"script": "echo hello"}))
        step = data["steps"][0]
        assert "command" in step
        assert "resolution" in step
        assert "args" in step
        assert "effects" in step

    def test_plan_invalid_syntax(self, plan_tool):
        """Planning invalid syntax returns has_errors=true."""
        data = json.loads(plan_tool.invoke({"script": "if; then"}))
        assert data["has_errors"] is True

    def test_plan_multiple_commands(self, plan_tool):
        """Plan for two commands should have at least two steps."""
        data = json.loads(plan_tool.invoke({"script": "echo a\necho b"}))
        assert len(data["steps"]) >= 2

    def test_plan_warnings_field(self, plan_tool):
        """Plan output should include a warnings list."""
        data = json.loads(plan_tool.invoke({"script": "echo hello"}))
        assert "warnings" in data
        assert isinstance(data["warnings"], list)


# ---------------------------------------------------------------------------
# Run tool tests
# ---------------------------------------------------------------------------


class TestRunTool:
    """Tests for AgentShRunTool."""

    def test_run_echo(self, run_tool):
        """Running 'echo hello' returns exit_code=0 and stdout='hello\\n'."""
        raw = run_tool.invoke({"script": "echo hello"})
        data = json.loads(raw)
        assert data["exit_code"] == 0
        assert data["stdout"] == "hello\n"

    def test_run_exit_0(self, run_tool):
        """Running 'exit 0' returns exit_code=0."""
        data = json.loads(run_tool.invoke({"script": "exit 0"}))
        assert data["exit_code"] == 0

    def test_run_exit_1(self, run_tool):
        """Running 'exit 1' returns a non-zero exit code."""
        data = json.loads(run_tool.invoke({"script": "exit 1"}))
        assert data["exit_code"] != 0

    def test_run_exit_42(self, run_tool):
        """Running 'exit 42' returns exit_code=42."""
        data = json.loads(run_tool.invoke({"script": "exit 42"}))
        assert data["exit_code"] == 42

    def test_run_stderr(self, run_tool):
        """Running 'echo err >&2' writes to stderr."""
        data = json.loads(run_tool.invoke({"script": "echo err >&2"}))
        assert data["exit_code"] == 0
        assert "err" in data["stderr"]

    def test_run_invalid_syntax(self, run_tool):
        """Running invalid syntax returns a non-zero exit code."""
        data = json.loads(run_tool.invoke({"script": "if; then"}))
        assert data["exit_code"] != 0

    def test_run_true(self, run_tool):
        """Running 'true' returns exit_code=0."""
        data = json.loads(run_tool.invoke({"script": "true"}))
        assert data["exit_code"] == 0

    def test_run_false(self, run_tool):
        """Running 'false' returns a non-zero exit code."""
        data = json.loads(run_tool.invoke({"script": "false"}))
        assert data["exit_code"] != 0


# ---------------------------------------------------------------------------
# Shared state tests
# ---------------------------------------------------------------------------


class TestSharedState:
    """Tests that tools sharing an engine preserve state between calls."""

    def test_variable_persists_across_runs(self):
        """Set a variable in one run, read it in the next."""
        _, _, run = create_agentsh_tools()
        run.invoke({"script": "X=hello"})
        result = json.loads(run.invoke({"script": "echo $X"}))
        assert result["stdout"] == "hello\n"

    def test_multiple_variables_persist(self):
        """Multiple variable assignments persist."""
        _, _, run = create_agentsh_tools()
        run.invoke({"script": "A=foo"})
        run.invoke({"script": "B=bar"})
        result = json.loads(run.invoke({"script": "echo $A $B"}))
        assert result["stdout"] == "foo bar\n"

    def test_separate_tool_sets_have_isolated_state(self):
        """Two separate tool sets do not share state."""
        _, _, run1 = create_agentsh_tools()
        _, _, run2 = create_agentsh_tools()
        run1.invoke({"script": "X=from_run1"})
        result = json.loads(run2.invoke({"script": "echo $X"}))
        # X should be empty/unset in run2's engine.
        assert result["stdout"].strip() == ""


# ---------------------------------------------------------------------------
# ast_to_dict helper tests
# ---------------------------------------------------------------------------


class TestAstToDict:
    """Tests for the ast_to_dict helper function."""

    def test_simple_command(self):
        """ast_to_dict converts a Program with a SimpleCommand."""
        from agentsh.api.engine import ShellEngine

        engine = ShellEngine()
        parsed = engine.parse("echo hello")
        assert parsed.ast is not None
        d = ast_to_dict(parsed.ast)
        assert d["type"] == "Program"
        assert isinstance(d["body"], list)
        assert len(d["body"]) >= 1

    def test_pipeline(self):
        """ast_to_dict converts a pipeline."""
        from agentsh.api.engine import ShellEngine

        engine = ShellEngine()
        parsed = engine.parse("echo hello | cat")
        assert parsed.ast is not None
        d = ast_to_dict(parsed.ast)
        assert d["type"] == "Program"
        # Find a Pipeline node somewhere in the tree.
        assert _find_type(d, "Pipeline")

    def test_roundtrip_json_serializable(self):
        """ast_to_dict output must be JSON-serializable."""
        from agentsh.api.engine import ShellEngine

        engine = ShellEngine()
        parsed = engine.parse("echo hello world")
        assert parsed.ast is not None
        d = ast_to_dict(parsed.ast)
        # Should not raise.
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_function_def(self):
        """ast_to_dict handles function definitions."""
        from agentsh.api.engine import ShellEngine

        engine = ShellEngine()
        parsed = engine.parse("f() { echo hi; }")
        assert parsed.ast is not None
        d = ast_to_dict(parsed.ast)
        assert _find_type(d, "FunctionDef")

    def test_unknown_node_type(self):
        """ast_to_dict falls back to type name for unknown node types."""

        # Create a dummy object that is not a known AST node.
        class FakeNode:
            pass

        result = ast_to_dict(FakeNode())
        assert result["type"] == "FakeNode"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_type(node_dict: dict, type_name: str) -> bool:
    """Recursively search a dict-based AST for a node with given type."""
    if node_dict.get("type") == type_name:
        return True
    for v in node_dict.values():
        if isinstance(v, dict):
            if _find_type(v, type_name):
                return True
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _find_type(item, type_name):
                    return True
    return False
