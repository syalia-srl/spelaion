"""Compound command execution: sequences, and/or lists, groups, subshells, functions."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.ast.nodes import (
        AndOrList,
        FunctionDef,
        Group,
        Sequence,
        Subshell,
    )
    from agentsh.exec.cmd_eval import CommandEvaluator
    from agentsh.exec.executor import Executor
    from agentsh.exec.redirs import IOContext


def execute_sequence(
    node: Sequence,
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Execute commands in sequence (separated by ; or newline)."""
    result = CommandResult(exit_code=0)
    for cmd in node.commands:
        result = executor.execute_node(cmd, io)
        # errexit check
        if executor.state.options.errexit and result.exit_code != 0:
            break
    return result


def execute_and_or(
    node: AndOrList,
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Execute and/or list with short-circuit evaluation."""
    if not node.commands:
        return CommandResult(exit_code=0)

    result = executor.execute_node(node.commands[0], io)

    for i, operator in enumerate(node.operators):
        if i + 1 >= len(node.commands):
            break

        if operator == "&&":
            if result.exit_code == 0:
                result = executor.execute_node(node.commands[i + 1], io)
            # else: short-circuit, skip
        elif operator == "||" and result.exit_code != 0:
            result = executor.execute_node(node.commands[i + 1], io)
            # else: short-circuit, skip

    return result


def execute_group(
    node: Group,
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Execute group { ...; } in current shell context."""
    return executor.execute_node(node.body, io)


def execute_subshell(
    node: Subshell,
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Execute subshell ( ... ) with copied state but shared VFS."""
    from agentsh.exec.executor import Executor

    sub_state = executor.state.copy()
    sub_executor = Executor(
        state=sub_state,
        vfs=executor.vfs,  # shared!
        tools=executor.tools,
        policy=executor.policy,
    )
    return sub_executor.execute_node(node.body, io)


def execute_function_def(
    node: FunctionDef,
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Register a function definition in shell state."""
    executor.state.functions[node.name] = node
    return CommandResult(exit_code=0)


def execute_function_call(
    name: str,
    args: list[str],
    executor: Executor | CommandEvaluator,
    io: IOContext,
) -> CommandResult:
    """Execute a function call with positional parameter setup and local scope."""
    from agentsh.exec.builtins import ReturnSignal

    func_def = executor.state.functions.get(name)
    if func_def is None:
        io.stderr.write(f"agentsh: {name}: function not found\n")
        return CommandResult(exit_code=127)

    # Save and set positional params
    saved_params = executor.state.positional_params
    executor.state.positional_params = args

    # Push a new scope for local variables
    executor.state.push_scope()

    try:
        result = executor.execute_node(func_def.body, io)
    except ReturnSignal as ret:
        result = CommandResult(exit_code=ret.exit_code)
    finally:
        executor.state.pop_scope()
        executor.state.positional_params = saved_params

    return result
