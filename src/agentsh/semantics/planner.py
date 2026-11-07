"""Planner / dry-run mode.

Traverses the AST and produces an ExecutionPlan without executing side effects.
Effects adapted for virtual context: VFSRead, VFSWrite, VFSGlob, StateChange,
ToolInvocation, UnresolvedCommand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from agentsh.ast.nodes import (
    AndOrList,
    ASTNode,
    FunctionDef,
    Group,
    Pipeline,
    Program,
    Sequence,
    SimpleCommand,
    Subshell,
)
from agentsh.semantics.resolve import resolve_command

if TYPE_CHECKING:
    from agentsh.policy.decisions import PolicyEngine
    from agentsh.runtime.state import ShellState
    from agentsh.tools.registry import ToolRegistry


@dataclass(frozen=True)
class PlannedEffect:
    """A single planned effect from dry-run analysis."""

    kind: Literal[
        "vfs_read",
        "vfs_write",
        "vfs_glob",
        "state_change",
        "tool_invocation",
        "builtin_call",
        "function_call",
        "unresolved_command",
        "policy_denied",
    ]
    description: str
    target: str = ""  # path, variable name, command name
    details: dict[str, str] = field(default_factory=lambda: {})


@dataclass
class PlannedStep:
    """A single step in the execution plan."""

    command: str
    resolution: str  # "builtin", "function", "agent_tool", "not_found"
    args: list[str] = field(default_factory=lambda: [])
    effects: list[PlannedEffect] = field(default_factory=lambda: [])
    children: list[PlannedStep] = field(default_factory=lambda: [])


@dataclass
class ExecutionPlan:
    """Complete execution plan for a script."""

    steps: list[PlannedStep] = field(default_factory=lambda: [])
    effects: list[PlannedEffect] = field(default_factory=lambda: [])
    warnings: list[str] = field(default_factory=lambda: [])


class Planner:
    """Produces an ExecutionPlan from an AST without executing anything."""

    def __init__(
        self,
        state: ShellState,
        tools: ToolRegistry,
        policy: PolicyEngine,
    ) -> None:
        self.state = state
        self.tools = tools
        self.policy = policy

    def plan(self, node: ASTNode) -> ExecutionPlan:
        """Analyze an AST and return an execution plan."""
        plan = ExecutionPlan()
        self._plan_node(node, plan)
        return plan

    def _plan_node(self, node: ASTNode, plan: ExecutionPlan) -> None:
        if isinstance(node, Program):
            for cmd in node.body:
                self._plan_node(cmd, plan)
        elif isinstance(node, (Sequence, AndOrList, Pipeline)):
            for cmd in node.commands:
                self._plan_node(cmd, plan)
        elif isinstance(node, SimpleCommand):
            self._plan_simple_command(node, plan)
        elif isinstance(node, Group):
            self._plan_node(node.body, plan)
        elif isinstance(node, Subshell):
            step = PlannedStep(command="(subshell)", resolution="subshell")
            sub_plan = ExecutionPlan()
            self._plan_node(node.body, sub_plan)
            step.children = sub_plan.steps
            plan.steps.append(step)
        elif isinstance(node, FunctionDef):
            plan.effects.append(
                PlannedEffect(
                    kind="state_change",
                    description=f"Define function: {node.name}",
                    target=node.name,
                )
            )

    def _plan_simple_command(self, node: SimpleCommand, plan: ExecutionPlan) -> None:  # noqa: C901
        # Plan assignments
        for assign in node.assignments:
            from agentsh.ast.nodes import ArrayAssignmentWord

            if isinstance(assign, ArrayAssignmentWord):
                plan.effects.append(
                    PlannedEffect(
                        kind="state_change",
                        description=f"Set array: {assign.name}=(...)",
                        target=assign.name,
                        details={"value": "<array>"},
                    )
                )
                continue

            value_text = "<unknown>"
            if assign.value is not None:
                # Try to extract literal value
                from agentsh.ast.words import LiteralSegment, SingleQuotedSegment

                parts: list[str] = []
                for seg in assign.value.segments:
                    if isinstance(seg, (LiteralSegment, SingleQuotedSegment)):
                        parts.append(seg.value)
                    else:
                        parts.append("<dynamic>")
                value_text = "".join(parts)

            plan.effects.append(
                PlannedEffect(
                    kind="state_change",
                    description=f"Set variable: {assign.name}={value_text}",
                    target=assign.name,
                    details={"value": value_text},
                )
            )

        if not node.words:
            return

        # Try to determine command name
        cmd_name = "<unknown>"
        from agentsh.ast.words import LiteralSegment, SingleQuotedSegment

        first_word = node.words[0]
        if first_word.segments:
            seg = first_word.segments[0]
            if isinstance(seg, (LiteralSegment, SingleQuotedSegment)):
                cmd_name = seg.value

        # Try to determine args
        arg_texts: list[str] = []
        for word in node.words[1:]:
            parts: list[str] = []
            for seg in word.segments:
                if isinstance(seg, (LiteralSegment, SingleQuotedSegment)):
                    parts.append(seg.value)
                else:
                    parts.append("<dynamic>")
            arg_texts.append("".join(parts))

        # Resolve
        resolved = resolve_command(cmd_name, self.state, self.tools)

        step = PlannedStep(
            command=cmd_name,
            resolution=resolved.kind,
            args=arg_texts,
        )

        # Check policy
        decision = self.policy.check_command(cmd_name)
        if decision.action == "deny":
            step.effects.append(
                PlannedEffect(
                    kind="policy_denied",
                    description=f"Command denied by policy: {decision.reason}",
                    target=cmd_name,
                )
            )
            plan.warnings.append(f"Command '{cmd_name}' denied: {decision.reason}")

        if decision.action == "warn":
            plan.warnings.append(f"Command '{cmd_name}' has warning: {decision.reason}")

        # Plan redirections
        for redir in node.redirections:
            target_text = "<unknown>"
            if redir.target.segments:
                seg = redir.target.segments[0]
                if isinstance(seg, (LiteralSegment, SingleQuotedSegment)):
                    target_text = seg.value

            if redir.op in (">", ">>"):
                step.effects.append(
                    PlannedEffect(
                        kind="vfs_write",
                        description=f"Write to: {target_text}",
                        target=target_text,
                        details={"op": redir.op},
                    )
                )
            elif redir.op == "<":
                step.effects.append(
                    PlannedEffect(
                        kind="vfs_read",
                        description=f"Read from: {target_text}",
                        target=target_text,
                    )
                )

        # Note tool invocations
        if resolved.kind == "agent_tool":
            step.effects.append(
                PlannedEffect(
                    kind="tool_invocation",
                    description=f"Invoke tool: {cmd_name}",
                    target=cmd_name,
                )
            )
        elif resolved.kind == "not_found":
            step.effects.append(
                PlannedEffect(
                    kind="unresolved_command",
                    description=f"Command not found: {cmd_name}",
                    target=cmd_name,
                )
            )

        plan.steps.append(step)
        plan.effects.extend(step.effects)
