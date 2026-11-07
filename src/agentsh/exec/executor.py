"""Thin facade over the split evaluators.

Backward-compatible entry point: ``api/engine.py`` and ``compound.py``
call ``executor.execute_node()``, so this class wires up the evaluator
graph and delegates all work to :class:`CommandEvaluator`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.exec.arith_eval import ArithEvaluator
from agentsh.exec.bool_eval import BoolEvaluator
from agentsh.exec.cmd_eval import CommandEvaluator
from agentsh.exec.redirs import IOContext
from agentsh.exec.word_eval import WordEvaluator
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.ast.nodes import ASTNode
    from agentsh.policy.decisions import PolicyEngine
    from agentsh.runtime.state import ShellState
    from agentsh.tools.registry import ToolRegistry
    from agentsh.vfs.filesystem import VirtualFilesystem


class Executor:
    """Backward-compatible facade that creates and wires the split evaluators.

    External callers (``ShellEngine``, ``compound.py``) interact with
    ``Executor`` exactly as before.  Internally all work is dispatched to
    the evaluator graph.
    """

    def __init__(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        tools: ToolRegistry,
        policy: PolicyEngine,
    ) -> None:
        self.state = state
        self.vfs = vfs
        self.tools = tools
        self.policy = policy

        # --- Wire the evaluator graph ---
        self.arith_ev = ArithEvaluator(state)
        self.bool_ev = BoolEvaluator(state, vfs)

        # WordEvaluator needs its cmdsub_hook set *after* cmd_eval exists,
        # so we create it first with hook=None and patch below.
        self.word_ev = WordEvaluator(
            state=state,
            vfs=vfs,
            arith_ev=self.arith_ev,
            cmdsub_hook=None,
        )

        self.cmd_eval = CommandEvaluator(
            state=state,
            vfs=vfs,
            tools=tools,
            policy=policy,
            word_ev=self.word_ev,
            arith_ev=self.arith_ev,
            bool_ev=self.bool_ev,
        )

        # Close the loop: word_eval needs the cmd_eval's cmdsub hook
        self.word_ev.cmdsub_hook = self.cmd_eval.cmdsub_hook

    # ------------------------------------------------------------------
    # Public API — delegates to CommandEvaluator
    # ------------------------------------------------------------------

    def execute_node(self, node: ASTNode, io: IOContext | None = None) -> CommandResult:
        """Execute an AST node and return the result."""
        return self.cmd_eval.execute_node(node, io)

    def execute_source(self, path: str, io: IOContext) -> CommandResult:
        """Execute a sourced file in the current shell context."""
        return self.cmd_eval.execute_source(path, io)
