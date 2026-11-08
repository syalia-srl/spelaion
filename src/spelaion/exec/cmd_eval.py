"""Command evaluator — main AST dispatcher using structural pattern matching.

Follows the Oils split-evaluator pattern.  This is the heart of the
execution engine: it walks AST nodes via ``match``/``case`` and delegates
expansion to :class:`WordEvaluator`, arithmetic to :class:`ArithEvaluator`,
and test expressions to :class:`BoolEvaluator`.

No subprocess.  All execution is virtual: builtins, tool dispatch, VFS I/O.
"""

from __future__ import annotations

import fnmatch as _fnmatch
import time
from collections.abc import Callable
from io import StringIO
from typing import TYPE_CHECKING

from spelaion.ast.nodes import (
    AndOrList,
    ArrayAssignmentWord,
    AssignmentWord,
    ASTNode,
    CaseClause,
    CStyleForLoop,
    ExtendedTest,
    ForLoop,
    FunctionDef,
    Group,
    IfClause,
    Pipeline,
    Program,
    RedirectedCommand,
    Sequence,
    SimpleCommand,
    Subshell,
    UntilLoop,
    WhileLoop,
)
from spelaion.commands._registry import COMMANDS
from spelaion.exec.builtins import (
    BUILTINS,
    BreakSignal,
    ContinueSignal,
    ReturnSignal,
)
from spelaion.exec.compound import (
    execute_and_or,
    execute_function_call,
    execute_function_def,
    execute_group,
    execute_sequence,
    execute_subshell,
)
from spelaion.exec.pipelines import execute_pipeline
from spelaion.exec.redirs import (
    IOContext,
    RedirectionError,
    VFSWriteBuffer,
    apply_redirections,
)
from spelaion.exec.tool_dispatch import dispatch_tool
from spelaion.runtime.result import CommandResult
from spelaion.runtime.state import LoopLimit, TimeoutExpired
from spelaion.semantics.resolve import resolve_command

if TYPE_CHECKING:
    from spelaion.exec.arith_eval import ArithEvaluator
    from spelaion.exec.bool_eval import BoolEvaluator
    from spelaion.exec.word_eval import WordEvaluator
    from spelaion.policy.decisions import PolicyEngine
    from spelaion.runtime.state import ShellState
    from spelaion.tools.registry import ToolRegistry
    from spelaion.vfs.base import Filesystem


class CommandEvaluator:
    """Central AST dispatcher.  Uses ``match``/``case`` for node dispatch.

    Holds back-pointers to the other split evaluators and delegates
    word expansion, arithmetic, and boolean evaluation to them.
    """

    def __init__(
        self,
        state: ShellState,
        vfs: Filesystem,
        tools: ToolRegistry,
        policy: PolicyEngine,
        word_ev: WordEvaluator,
        arith_ev: ArithEvaluator,
        bool_ev: BoolEvaluator,
    ) -> None:
        self.state = state
        self.vfs = vfs
        self.tools = tools
        self.policy = policy
        self.word_ev = word_ev
        self.arith_ev = arith_ev
        self.bool_ev = bool_ev
        self._recursion_depth = 0
        # The stderr of the node running now: a ``$(...)`` inside it writes
        # its errors there.
        self._stderr = StringIO()
        # The status of the last ``$(...)`` a simple command ran, for ``$?``
        # after a command of assignments only; None when it ran none.
        self._cmdsub_status: int | None = None

    # ------------------------------------------------------------------
    # Main dispatch
    # ------------------------------------------------------------------

    def execute_node(self, node: ASTNode, io: IOContext | None = None) -> CommandResult:
        """Execute an AST node and return the result."""
        if io is None:
            io = IOContext()
        if self.state.deadline is not None and time.monotonic() >= self.state.deadline:
            raise TimeoutExpired
        outer_stderr = self._stderr
        self._stderr = io.stderr
        try:
            return self._dispatch(node, io)
        finally:
            self._stderr = outer_stderr

    def _dispatch(self, node: ASTNode, io: IOContext) -> CommandResult:  # noqa: C901
        match node:
            case Program():
                return self._execute_program(node, io)
            case Sequence():
                return execute_sequence(node, self, io)
            case AndOrList():
                return execute_and_or(node, self, io)
            case Pipeline():
                return self._execute_pipeline(node, io)
            case SimpleCommand():
                return self._execute_simple_command(node, io)
            case Group():
                return execute_group(node, self, io)
            case Subshell():
                return execute_subshell(node, self, io)
            case FunctionDef():
                return execute_function_def(node, self, io)
            case IfClause():
                return self._execute_if(node, io)
            case WhileLoop():
                return self._execute_while(node, io)
            case UntilLoop():
                return self._execute_until(node, io)
            case ForLoop():
                return self._execute_for(node, io)
            case CStyleForLoop():
                return self._execute_c_style_for(node, io)
            case CaseClause():
                return self._execute_case(node, io)
            case ExtendedTest():
                return self._execute_extended_test(node, io)
            case RedirectedCommand():
                return self._execute_redirected_command(node, io)
            case _:
                io.stderr.write(
                    f"spelaion: unsupported node type: {type(node).__name__}\n"
                )
                return CommandResult(exit_code=2)

    # ------------------------------------------------------------------
    # Program
    # ------------------------------------------------------------------

    def _execute_program(self, node: Program, io: IOContext) -> CommandResult:
        result = CommandResult(exit_code=0)
        for cmd in node.body:
            result = self.execute_node(cmd, io)
            self.state.last_status = result.exit_code
            if self.state.options.errexit and result.exit_code != 0:
                break
        return result

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _execute_pipeline(self, node: Pipeline, io: IOContext) -> CommandResult:
        if len(node.commands) == 1:
            result = self.execute_node(node.commands[0], io)
        else:

            def make_stage(
                cmd_node: ASTNode,
            ) -> Callable[[IOContext], CommandResult]:
                def stage(stage_io: IOContext) -> CommandResult:
                    return self.execute_node(cmd_node, stage_io)

                return stage

            stages = [make_stage(cmd) for cmd in node.commands]
            stdin_text = io.stdin.read() if io.stdin else ""
            statuses: list[int] = []
            result = execute_pipeline(
                stages,
                input_text=stdin_text,
                pipefail=self.state.options.pipefail,
                stderr=io.stderr,
                statuses=statuses,
            )
            if result.stdout:
                io.stdout.write(result.stdout)
            self.state.set_array("PIPESTATUS", [str(c) for c in statuses])

        if node.negated:
            result = CommandResult(
                exit_code=0 if result.exit_code != 0 else 1,
                stdout=result.stdout,
                stderr=result.stderr,
            )

        self.state.last_status = result.exit_code
        return result

    # ------------------------------------------------------------------
    # Simple command
    # ------------------------------------------------------------------

    def _execute_simple_command(
        self, node: SimpleCommand, io: IOContext
    ) -> CommandResult:
        # Handle prefix assignments
        self._cmdsub_status = None
        saved_vars: dict[str, str | None] = {}
        for assign in node.assignments:
            if isinstance(assign, ArrayAssignmentWord):
                values: list[str] = []
                for val_word in assign.values:
                    values.extend(self.word_ev.eval_word(val_word))
                self.state.set_array(assign.name, values)
                continue
            if self._handle_subscript_assignment(assign):
                continue
            value = ""
            if assign.value is not None:
                value = self.word_ev.eval_word_single(assign.value)
            saved_vars[assign.name] = self.state.get_var(assign.name)
            self.state.set_var(assign.name, value)

        # If no words, assignments are permanent; their status is the last
        # command substitution's.
        if not node.words:
            status = self._cmdsub_status or 0
            self.state.last_status = status
            return CommandResult(exit_code=status)

        # Expand words
        expanded: list[str] = []
        for word in node.words:
            expanded.extend(self.word_ev.eval_word(word))

        if not expanded or not expanded[0]:
            self.state.last_status = 0
            return CommandResult(exit_code=0)

        cmd_name = expanded[0]
        cmd_args = expanded[1:]

        # Apply redirections — save originals so we can restore after
        saved_stdout = io.stdout
        saved_stderr = io.stderr
        try:
            io = apply_redirections(
                node.redirections, io, self.state, self.vfs, self.cmdsub_hook
            )
        except RedirectionError:
            self._finalize_io(
                io,
                saved_stdout,
                saved_stderr,
                io.stdout is not saved_stdout,
                io.stderr is not saved_stderr,
            )
            self._restore_vars_if_temporary(node, saved_vars)
            self.state.last_status = 1
            self.state.set_array("PIPESTATUS", ["1"])
            return CommandResult(exit_code=1)
        stdout_redirected = io.stdout is not saved_stdout
        stderr_redirected = io.stderr is not saved_stderr

        # Policy check
        decision = self.policy.check_command(cmd_name)
        if decision.action == "deny":
            io.stderr.write(
                f"spelaion: {cmd_name}: denied by policy ({decision.reason})\n"
            )
            result = CommandResult(exit_code=126, stderr=f"denied: {decision.reason}")
            self._finalize_io(
                io,
                saved_stdout,
                saved_stderr,
                stdout_redirected,
                stderr_redirected,
            )
            self._restore_vars_if_temporary(node, saved_vars)
            self.state.last_status = result.exit_code
            return result

        # Resolve command
        resolved = resolve_command(cmd_name, self.state, self.tools)

        # Dispatch
        match resolved.kind:
            case "function":
                result = execute_function_call(cmd_name, cmd_args, self, io)
            case "builtin":
                result = self._dispatch_builtin(cmd_name, cmd_args, io)
            case "agent_tool":
                result = dispatch_tool(cmd_name, cmd_args, self.tools, io, self.state)
            case _:
                io.stderr.write(f"spelaion: {cmd_name}: command not found\n")
                result = CommandResult(exit_code=127)

        if not self._finalize_io(
            io,
            saved_stdout,
            saved_stderr,
            stdout_redirected,
            stderr_redirected,
        ):
            result = CommandResult(exit_code=1)
        self._restore_vars_if_temporary(node, saved_vars)
        self.state.last_status = result.exit_code
        self.state.set_array("PIPESTATUS", [str(result.exit_code)])
        return result

    def _handle_subscript_assignment(self, assign: AssignmentWord) -> bool:
        """Handle ``name[subscript]=value`` assignments.

        Returns ``True`` if this was a subscript assignment (handled),
        ``False`` otherwise.
        """
        aname = assign.name
        if "[" not in aname or not aname.endswith("]"):
            return False
        bracket = aname.index("[")
        base = aname[:bracket]
        idx_str = aname[bracket + 1 : -1]
        value = ""
        if assign.value is not None:
            value = self.word_ev.eval_word_single(assign.value)
        # If the variable is an associative array, use string key
        if self.state.get_assoc(base) is not None:
            self.state.set_assoc_element(base, idx_str, value)
        else:
            try:
                idx = int(idx_str)
            except ValueError:
                idx = self.arith_ev.eval_expr(idx_str)
            self.state.set_array_element(base, idx, value)
        return True

    def _dispatch_builtin(
        self, cmd_name: str, cmd_args: list[str], io: IOContext
    ) -> CommandResult:
        """Dispatch a builtin command, handling source/. specially."""
        if cmd_name in ("source", "."):
            if not cmd_args:
                io.stderr.write(f"spelaion: {cmd_name}: filename argument required\n")
                return CommandResult(exit_code=2)
            return self.execute_source(cmd_args[0], io)

        builtin_fn = BUILTINS.get(cmd_name)
        if builtin_fn is None:
            # Fall through to virtual commands (cat, grep, sed, etc.)
            cmd_fn = COMMANDS.get(cmd_name)
            if cmd_fn is not None:
                io.executor = self
                try:
                    return cmd_fn(cmd_args, self.state, self.vfs, io)
                except OSError as e:
                    io.stderr.write(f"{cmd_name}: {e.strerror or e}\n")
                    return CommandResult(exit_code=1)
            io.stderr.write(f"spelaion: {cmd_name}: builtin not implemented\n")
            return CommandResult(exit_code=2)

        try:
            io.executor = self
            return builtin_fn(cmd_args, self.state, self.vfs, io)
        except SystemExit as e:
            return CommandResult(exit_code=e.code if isinstance(e.code, int) else 0)
        except OSError as e:
            io.stderr.write(f"{cmd_name}: {e.strerror or e}\n")
            return CommandResult(exit_code=1)

    # ------------------------------------------------------------------
    # Control flow
    # ------------------------------------------------------------------

    def _execute_if(self, node: IfClause, io: IOContext) -> CommandResult:
        result = CommandResult(exit_code=0)
        for i, condition in enumerate(node.conditions):
            cond_result = self.execute_node(condition, io)
            if cond_result.exit_code == 0 and i < len(node.bodies):
                return self.execute_node(node.bodies[i], io)
        if node.else_body is not None:
            return self.execute_node(node.else_body, io)
        return result

    def _execute_while(self, node: WhileLoop, io: IOContext) -> CommandResult:
        return self._execute_loop(node, io, break_on_success=False)

    def _execute_until(self, node: UntilLoop, io: IOContext) -> CommandResult:
        return self._execute_loop(node, io, break_on_success=True)

    def _execute_loop(
        self,
        node: WhileLoop | UntilLoop,
        io: IOContext,
        *,
        break_on_success: bool,
    ) -> CommandResult:
        result = CommandResult(exit_code=0)
        iterations = 0
        max_iter = self._max_loop_iterations()
        while True:
            cond_result = self.execute_node(node.condition, io)
            if (cond_result.exit_code == 0) == break_on_success:
                break
            try:
                result = self.execute_node(node.body, io)
            except BreakSignal as sig:
                if sig.levels > 1:
                    raise BreakSignal(sig.levels - 1) from None
                break
            except ContinueSignal as sig:
                if sig.levels > 1:
                    raise ContinueSignal(sig.levels - 1) from None
                iterations += 1
                if iterations > max_iter:
                    self._loop_limit(io, "loop")
                    break
                continue
            iterations += 1
            if iterations > max_iter:
                self._loop_limit(io, "loop")
                break
        return result

    def _max_loop_iterations(self) -> int:
        cap = self.policy.config.max_loop_iterations
        return self.policy.config.max_recursion_depth * 10 if cap is None else cap

    def _loop_limit(self, io: IOContext, kind: str) -> None:
        """Report a loop past its cap; stop the script if the policy says so."""
        io.stderr.write(f"spelaion: {kind} iteration limit reached\n")
        if self.policy.config.max_loop_iterations is not None:
            raise LoopLimit

    def _execute_for(self, node: ForLoop, io: IOContext) -> CommandResult:
        result = CommandResult(exit_code=0)

        if node.words is not None:
            items: list[str] = []
            for word in node.words:
                items.extend(self.word_ev.eval_word(word))
        else:
            items = list(self.state.positional_params)

        for item in items:
            self.state.set_var(node.variable, item)
            try:
                result = self.execute_node(node.body, io)
            except BreakSignal as sig:
                if sig.levels > 1:
                    raise BreakSignal(sig.levels - 1) from None
                break
            except ContinueSignal as sig:
                if sig.levels > 1:
                    raise ContinueSignal(sig.levels - 1) from None
                continue
            if self.state.options.errexit and result.exit_code != 0:
                break
        return result

    def _execute_case(self, node: CaseClause, io: IOContext) -> CommandResult:
        word_values = self.word_ev.eval_word(node.word)
        word_value = word_values[0] if word_values else ""

        for item in node.items:
            for pattern_word in item.patterns:
                pattern_values = self.word_ev.eval_word(pattern_word)
                pattern = pattern_values[0] if pattern_values else ""
                if _fnmatch.fnmatch(word_value, pattern):
                    if item.body is not None:
                        return self.execute_node(item.body, io)
                    return CommandResult(exit_code=0)

        return CommandResult(exit_code=0)

    def _execute_extended_test(
        self, node: ExtendedTest, io: IOContext
    ) -> CommandResult:
        """Execute [[ ... ]] extended test."""
        # Expand words (skip [[ and ]])
        tokens: list[str] = []
        for word in node.words:
            expanded = self.word_ev.eval_word(word)
            tokens.extend(expanded)
        # Strip [[ and ]]
        if tokens and tokens[0] == "[[":
            tokens = tokens[1:]
        if tokens and tokens[-1] == "]]":
            tokens = tokens[:-1]
        result = self.bool_ev.eval_extended_test(tokens)
        exit_code = 0 if result else 1
        self.state.last_status = exit_code
        return CommandResult(exit_code=exit_code)

    def _execute_c_style_for(self, node: CStyleForLoop, io: IOContext) -> CommandResult:
        """Execute a C-style for loop: for (( init; cond; update ))."""
        result = CommandResult(exit_code=0)
        # Execute init
        if node.init:
            self.arith_ev.eval_statement(node.init)
        iterations = 0
        max_iter = self._max_loop_iterations()
        while True:
            # Evaluate condition (empty condition = true)
            if node.condition:
                cond_val = self.arith_ev.eval_expr(node.condition)
                if cond_val == 0:
                    break
            try:
                result = self.execute_node(node.body, io)
            except BreakSignal as sig:
                if sig.levels > 1:
                    raise BreakSignal(sig.levels - 1) from None
                break
            except ContinueSignal as sig:
                if sig.levels > 1:
                    raise ContinueSignal(sig.levels - 1) from None
                iterations += 1
                if iterations > max_iter:
                    self._loop_limit(io, "C-style for loop")
                    break
                # Evaluate update before continuing
                if node.update:
                    self.arith_ev.eval_statement(node.update)
                continue
            iterations += 1
            if iterations > max_iter:
                self._loop_limit(io, "C-style for loop")
                break
            # Evaluate update
            if node.update:
                self.arith_ev.eval_statement(node.update)
        return result

    # ------------------------------------------------------------------
    # Redirected compound command
    # ------------------------------------------------------------------

    def _execute_redirected_command(
        self, node: RedirectedCommand, io: IOContext
    ) -> CommandResult:
        """Execute a compound command with I/O redirections applied."""
        saved_stdin = io.stdin
        saved_stdout = io.stdout
        saved_stderr = io.stderr
        try:
            io = apply_redirections(
                node.redirections, io, self.state, self.vfs, self.cmdsub_hook
            )
            result = self.execute_node(node.body, io)
        except RedirectionError:
            result = CommandResult(exit_code=1)
        if not self._flush_redirects(
            [
                b
                for b, s in ((io.stdout, saved_stdout), (io.stderr, saved_stderr))
                if b is not s
            ],
            saved_stderr,
        ):
            result = CommandResult(exit_code=1)
        # Restore original streams
        io.stdin = saved_stdin
        io.stdout = saved_stdout
        io.stderr = saved_stderr
        self.state.last_status = result.exit_code
        return result

    # ------------------------------------------------------------------
    # Command substitution hook
    # ------------------------------------------------------------------

    def cmdsub_hook(self, command: str) -> str:
        """Command substitution hook — parse and execute the command."""
        self._recursion_depth += 1
        if self._recursion_depth > self.policy.config.max_recursion_depth:
            self._recursion_depth -= 1
            return ""

        try:
            from spelaion.parser.frontend import parse_script
            from spelaion.parser.normalize import normalize

            parse_result = parse_script(command)
            if parse_result.has_errors:
                return ""

            program, _ = normalize(parse_result.root_node, command)
            io = IOContext(stderr=self._stderr)
            try:
                status = self.execute_node(program, io).exit_code
            except (MemoryError, TimeoutExpired, LoopLimit):
                # The call's own limits: they end the call, not this command.
                raise
            except ReturnSignal as sig:
                status = sig.exit_code
            except (BreakSignal, ContinueSignal):
                status = 0
            except Exception as e:
                # Never the message: it may name a host path.
                io.stderr.write(f"spelaion: internal error: {type(e).__name__}\n")
                status = 1
            self._cmdsub_status = status
            return io.stdout.getvalue()
        finally:
            self._recursion_depth -= 1

    # ------------------------------------------------------------------
    # Source
    # ------------------------------------------------------------------

    def execute_source(self, path: str, io: IOContext) -> CommandResult:
        """Execute a sourced file in the current shell context."""
        abs_path = self.vfs.resolve(path, self.state.cwd)
        try:
            content = self.vfs.read(abs_path).decode("utf-8")
        except FileNotFoundError:
            io.stderr.write(f"spelaion: {path}: No such file\n")
            return CommandResult(exit_code=1)

        from spelaion.parser.frontend import parse_script
        from spelaion.parser.normalize import normalize

        parse_result = parse_script(content)
        if parse_result.has_errors:
            io.stderr.write(f"spelaion: {path}: syntax error\n")
            return CommandResult(exit_code=1)

        program, _ = normalize(parse_result.root_node, content)
        return self.execute_node(program, io)

    # ------------------------------------------------------------------
    # Convenience for virtual commands (find -exec, xargs)
    # ------------------------------------------------------------------

    def execute_argv(
        self, argv: list[str], io: IOContext | None = None
    ) -> CommandResult:
        """Execute a command given as a plain argv list.

        Constructs a synthetic :class:`SimpleCommand` AST node internally,
        keeping the command layer decoupled from AST details.
        """
        from spelaion.ast.nodes import SimpleCommand, Word
        from spelaion.ast.spans import Span
        from spelaion.ast.words import LiteralSegment

        if io is None:
            io = IOContext()
        span = Span.unknown()
        words = tuple(
            Word(segments=(LiteralSegment(value=w),), span=span) for w in argv
        )
        node = SimpleCommand(
            words=words,
            assignments=(),
            redirections=(),
            span=span,
        )
        return self.execute_node(node, io)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def _restore_vars_if_temporary(
        self, node: SimpleCommand, saved_vars: dict[str, str | None]
    ) -> None:
        if node.words and saved_vars:
            for name, old_val in saved_vars.items():
                if old_val is None:
                    self.state.scope.unset(name)
                else:
                    self.state.set_var(name, old_val)

    def _finalize_io(
        self,
        io: IOContext,
        saved_stdout: StringIO | None = None,
        saved_stderr: StringIO | None = None,
        stdout_redirected: bool = False,
        stderr_redirected: bool = False,
    ) -> bool:
        """Flush redirections and restore streams; ``False`` if a write failed."""
        err = saved_stderr if saved_stderr is not None else io.stderr
        # Only the files this command opened: an enclosing redirection
        # flushes its own buffer once, when it ends.
        mine = [io.stdout] * stdout_redirected + [io.stderr] * stderr_redirected
        flushed = self._flush_redirects(mine, err)
        # Restore original streams so subsequent commands in the
        # sequence write to the parent IOContext, not the VFS buffer.
        if stdout_redirected and saved_stdout is not None:
            io.stdout = saved_stdout
        if stderr_redirected and saved_stderr is not None:
            io.stderr = saved_stderr
        return flushed

    @staticmethod
    def _flush_redirects(bufs: list[StringIO], err: StringIO) -> bool:
        """Write redirected output to its files; report a refused write on *err*."""
        # ``>>f 2>&1`` puts one buffer on both streams: write it once.
        for buf in dict.fromkeys(bufs):
            if isinstance(buf, VFSWriteBuffer):
                try:
                    buf.flush_to_vfs()
                except OSError as e:
                    err.write(f"spelaion: {buf.path}: {e.strerror or e}\n")
                    return False
        return True
