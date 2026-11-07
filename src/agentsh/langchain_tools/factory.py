"""Factory for creating agentsh LangChain tools with a shared engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.api.engine import ShellEngine
from agentsh.langchain_tools.parse_tool import AgentShParseTool
from agentsh.langchain_tools.plan_tool import AgentShPlanTool
from agentsh.langchain_tools.run_tool import AgentShRunTool

if TYPE_CHECKING:
    from agentsh.policy.rules import PolicyConfig
    from agentsh.tools.registry import ToolRegistry


def create_agentsh_tools(
    initial_files: dict[str, str | bytes] | None = None,
    tool_registry: ToolRegistry | None = None,
    policy: PolicyConfig | None = None,
    initial_vars: dict[str, str] | None = None,
) -> tuple[AgentShParseTool, AgentShPlanTool, AgentShRunTool]:
    """Create parse, plan, and run tools sharing a single ShellEngine.

    All three tools share state — variables, VFS, and functions persist
    across calls.
    """
    engine = ShellEngine(
        initial_files=initial_files,
        tools=tool_registry,
        policy=policy,
        initial_vars=initial_vars,
    )

    parse_tool = AgentShParseTool(engine=engine)
    plan_tool = AgentShPlanTool(engine=engine)
    run_tool = AgentShRunTool(engine=engine)

    return parse_tool, plan_tool, run_tool
