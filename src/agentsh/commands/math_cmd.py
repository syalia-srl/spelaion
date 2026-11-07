"""Math commands: expr, bc."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("expr")
def cmd_expr(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("expr: missing operand\n")
        return CommandResult(exit_code=2)

    try:
        result = _compute_expr(args)
    except (ValueError, ZeroDivisionError, IndexError) as e:
        io.stderr.write(f"expr: {e}\n")
        return CommandResult(exit_code=2)

    io.stdout.write(str(result) + "\n")
    # expr returns 1 if result is 0 or empty string
    if result in {0, ""}:
        return CommandResult(exit_code=1)
    return CommandResult(exit_code=0)


def _compute_expr(tokens: list[str]) -> int | str:
    """Process expr expression tokens."""
    if len(tokens) == 1:
        try:
            return int(tokens[0])
        except ValueError:
            return tokens[0]

    # Handle operators in precedence order (lowest first)
    # |, &, comparison, +/-, */%
    for ops in [
        ("|",),
        ("&",),
        ("=", "!=", "<", "<=", ">", ">="),
        ("+", "-"),
        ("*", "/", "%"),
    ]:
        # Scan from right to left for left-associativity
        depth = 0
        for i in range(len(tokens) - 1, -1, -1):
            if tokens[i] == "(":
                depth += 1
            elif tokens[i] == ")":
                depth -= 1
            elif depth == 0 and tokens[i] in ops and i > 0:
                left = _compute_expr(tokens[:i])
                right = _compute_expr(tokens[i + 1 :])
                return _apply_op(tokens[i], left, right)

    # String operations
    if len(tokens) >= 3 and tokens[0] == "match":
        string = str(_compute_expr(tokens[1:2]))
        pattern = str(_compute_expr(tokens[2:3]))
        m = re.match(pattern, string)
        if m:
            if m.groups():
                return m.group(1)
            return len(m.group(0))
        return 0

    if len(tokens) >= 3 and tokens[0] == "length":
        val = str(_compute_expr(tokens[1:]))
        return len(val)

    if len(tokens) >= 4 and tokens[0] == "substr":
        string = str(_compute_expr(tokens[1:2]))
        pos = int(_compute_expr(tokens[2:3]))
        length = int(_compute_expr(tokens[3:4]))
        return string[pos - 1 : pos - 1 + length]

    try:
        return int(tokens[0])
    except ValueError:
        return tokens[0]


def _apply_op(op: str, left: int | str, right: int | str) -> int | str:  # noqa: C901
    if op == "|":
        return left if (left and left != 0) else right
    if op == "&":
        return left if (left and left != 0 and right and right != 0) else 0

    if op in ("=", "!=", "<", "<=", ">", ">="):
        try:
            lv, rv = int(left), int(right)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            lv, rv = str(left), str(right)  # type: ignore[assignment]
        if op == "=":
            return 1 if lv == rv else 0
        if op == "!=":
            return 1 if lv != rv else 0
        if op == "<":
            return 1 if lv < rv else 0  # type: ignore[operator]
        if op == "<=":
            return 1 if lv <= rv else 0  # type: ignore[operator]
        if op == ">":
            return 1 if lv > rv else 0  # type: ignore[operator]
        if op == ">=":
            return 1 if lv >= rv else 0  # type: ignore[operator]

    try:
        li, ri = int(left), int(right)  # type: ignore[arg-type]
    except (ValueError, TypeError) as err:
        raise ValueError(f"non-integer argument: {left!r} {op} {right!r}") from err

    if op == "+":
        return li + ri
    if op == "-":
        return li - ri
    if op == "*":
        return li * ri
    if op == "/":
        if ri == 0:
            raise ValueError("division by zero")
        return li // ri
    if op == "%":
        if ri == 0:
            raise ValueError("division by zero")
        return li % ri

    return 0


@command("bc")
def cmd_bc(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    text = io.stdin.read().strip()
    if not text:
        return CommandResult(exit_code=0)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line in ("quit", "q"):
            break
        try:
            result = _bc_compute(line)
            io.stdout.write(str(result) + "\n")
        except (ValueError, ZeroDivisionError, ArithmeticError):
            io.stderr.write("(standard_in) 1: parse error\n")
            return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


def _bc_compute(expr: str) -> int | float:
    """Process a simple bc expression using safe parsing."""
    expr = expr.strip()

    # Handle scale= and other assignments — just ignore
    if "=" in expr and not any(op in expr for op in ["==", "!=", "<=", ">="]):
        return 0

    return _bc_parse(expr)


def _bc_int_or_float(val: int | float) -> int | float:
    """Return int if the float has no fractional part."""
    if isinstance(val, float) and val == int(val):
        return int(val)
    return val


def _bc_parse(expr: str) -> int | float:
    """Parse and compute a bc expression."""
    expr = expr.strip()

    # Handle parentheses
    while "(" in expr:
        start = expr.rfind("(")
        end = expr.find(")", start)
        if end == -1:
            break
        inner = expr[start + 1 : end]
        result = _bc_parse(inner)
        expr = expr[:start] + str(result) + expr[end + 1 :]

    # Split on +/- (lowest precedence), scanning from right
    for i in range(len(expr) - 1, 0, -1):
        if expr[i] in "+-":
            left = _bc_parse(expr[:i])
            right = _bc_parse(expr[i + 1 :])
            result = left + right if expr[i] == "+" else left - right
            return _bc_int_or_float(result)

    # Split on */% (higher precedence)
    for i in range(len(expr) - 1, 0, -1):
        if expr[i] in "*/":
            left = _bc_parse(expr[:i])
            right = _bc_parse(expr[i + 1 :])
            if expr[i] == "*":
                result = left * right
            else:
                result = left / right if right != 0 else 0
            return _bc_int_or_float(result)

    # Handle ^ (exponentiation)
    if "^" in expr:
        parts = expr.split("^", 1)
        base = _bc_parse(parts[0])
        exp = _bc_parse(parts[1])
        result = base**exp
        return _bc_int_or_float(result)

    # Number
    expr = expr.strip()
    if "." in expr:
        return float(expr)
    return int(expr)
