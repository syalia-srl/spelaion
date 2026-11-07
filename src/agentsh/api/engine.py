"""ShellEngine — the main facade for parse/plan/run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentsh.exec.executor import Executor
from agentsh.exec.redirs import IOContext
from agentsh.parser.diagnostics import Diagnostic
from agentsh.parser.frontend import parse_script
from agentsh.parser.normalize import normalize
from agentsh.policy.decisions import PolicyEngine
from agentsh.policy.rules import PolicyConfig
from agentsh.runtime.result import CommandResult
from agentsh.runtime.state import ShellState
from agentsh.semantics.planner import ExecutionPlan, Planner
from agentsh.tools.registry import ToolRegistry
from agentsh.vfs.filesystem import VirtualFilesystem


@dataclass
class ParseOutput:
    """Result of parse() — AST + diagnostics."""

    ast: Any  # Program node
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])
    has_errors: bool = False
    source: str = ""


@dataclass
class PlanOutput:
    """Result of plan() — execution plan + diagnostics."""

    plan: ExecutionPlan
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])
    has_errors: bool = False


@dataclass
class RunOutput:
    """Result of run() — execution result + stdout/stderr."""

    result: CommandResult
    stdout: str = ""
    stderr: str = ""
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])


class ShellEngine:
    """Main facade: parse, plan, run shell scripts in a virtual environment."""

    def __init__(
        self,
        initial_files: dict[str, str | bytes] | None = None,
        tools: ToolRegistry | None = None,
        policy: PolicyConfig | None = None,
        initial_vars: dict[str, str] | None = None,
    ) -> None:
        self.vfs = VirtualFilesystem(initial_files=initial_files)
        self.tools = tools or ToolRegistry()
        self.policy_engine = PolicyEngine(config=policy)
        self.state = ShellState()

        if initial_vars:
            for name, value in initial_vars.items():
                self.state.set_var(name, value)

        # Set some defaults
        if not self.state.get_var("HOME"):
            self.state.set_var("HOME", "/home/user")
        if not self.state.get_var("PWD"):
            self.state.set_var("PWD", self.state.cwd)

    def parse(self, script: str) -> ParseOutput:
        """Parse a script and return the AST."""
        parse_result = parse_script(script)

        if parse_result.has_errors:
            return ParseOutput(
                ast=None,
                diagnostics=parse_result.diagnostics,
                has_errors=True,
                source=script,
            )

        program, norm_diagnostics = normalize(parse_result.root_node, script)
        all_diags = parse_result.diagnostics + norm_diagnostics

        return ParseOutput(
            ast=program,
            diagnostics=all_diags,
            has_errors=any(d.severity.value == "error" for d in all_diags),
            source=script,
        )

    def plan(self, script: str) -> PlanOutput:
        """Parse and plan a script without executing it."""
        parsed = self.parse(script)
        if parsed.has_errors or parsed.ast is None:
            return PlanOutput(
                plan=ExecutionPlan(),
                diagnostics=parsed.diagnostics,
                has_errors=True,
            )

        planner = Planner(
            state=self.state,
            tools=self.tools,
            policy=self.policy_engine,
        )
        plan = planner.plan(parsed.ast)

        return PlanOutput(
            plan=plan,
            diagnostics=parsed.diagnostics,
            has_errors=False,
        )

    def run(self, script: str) -> RunOutput:
        """Parse and execute a script."""
        parsed = self.parse(script)
        if parsed.has_errors or parsed.ast is None:
            return RunOutput(
                result=CommandResult(exit_code=2),
                diagnostics=parsed.diagnostics,
            )

        executor = Executor(
            state=self.state,
            vfs=self.vfs,
            tools=self.tools,
            policy=self.policy_engine,
        )

        io = IOContext()

        try:
            result = executor.execute_node(parsed.ast, io)
        except SystemExit as e:
            result = CommandResult(
                exit_code=e.code if isinstance(e.code, int) else 0,
            )

        stdout = io.stdout.getvalue()
        stderr = io.stderr.getvalue()

        return RunOutput(
            result=CommandResult(
                exit_code=result.exit_code,
                stdout=stdout,
                stderr=stderr,
            ),
            stdout=stdout,
            stderr=stderr,
            diagnostics=parsed.diagnostics,
        )
