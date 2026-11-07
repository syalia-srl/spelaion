"""Arithmetic evaluator — AST-safe evaluation of shell arithmetic expressions.

Follows the Oils split-evaluator pattern.  Handles ``$(( expr ))``
contexts including integer arithmetic, variable resolution, and all
standard operators.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.runtime.state import ShellState


class ArithEvaluator:
    """Evaluate shell arithmetic expressions to integer values.

    Supports: integer literals, ``+``, ``-``, ``*``, ``/``, ``%``,
    parentheses, unary ``+``/``-``, and variable references (``$name``,
    ``${name}``, or bare identifiers).
    """

    def __init__(self, state: ShellState) -> None:
        self.state = state

    def eval_expr(self, expression: str) -> int:
        """Evaluate *expression* and return an integer result.

        Variable references are resolved against the current
        :class:`ShellState`.  Unknown variables default to ``0``.
        On any parse/evaluation error the result is ``0``.
        """
        expr = self._expand_braced_expansions(expression)
        expr = self._preprocess(expr)
        expr = self._substitute_variables(expr)

        try:
            tree = ast.parse(expr.strip(), mode="eval")
            return self._walk(tree.body)
        except Exception:
            return 0

    def eval_statement(self, expression: str) -> int:
        """Evaluate a statement expression that may contain assignments.

        Handles comma expressions, pre/post increment/decrement,
        compound assignments (+=, -=, *=, /=, %=), and simple assignment.
        """
        # Comma expressions: evaluate each, return last
        if "," in expression:
            parts = expression.split(",")
            result = 0
            for part in parts:
                result = self.eval_statement(part.strip())
            return result

        expr = expression.strip()

        # Pre-increment: ++var
        if expr.startswith("++"):
            var = expr[2:].strip()
            val = self._get_int_var(var) + 1
            self.state.set_var(var, str(val))
            return val

        # Pre-decrement: --var
        if expr.startswith("--"):
            var = expr[2:].strip()
            val = self._get_int_var(var) - 1
            self.state.set_var(var, str(val))
            return val

        # Post-increment: var++
        if expr.endswith("++"):
            var = expr[:-2].strip()
            val = self._get_int_var(var)
            self.state.set_var(var, str(val + 1))
            return val

        # Post-decrement: var--
        if expr.endswith("--"):
            var = expr[:-2].strip()
            val = self._get_int_var(var)
            self.state.set_var(var, str(val - 1))
            return val

        # Compound assignments: +=, -=, *=, /=, %=
        for compound_op in ("+=", "-=", "*=", "/=", "%="):
            idx = expr.find(compound_op)
            if idx > 0:
                var = expr[:idx].strip()
                rhs = expr[idx + 2 :].strip()
                current = self._get_int_var(var)
                rhs_val = self.eval_expr(rhs)
                if compound_op == "+=":
                    result = current + rhs_val
                elif compound_op == "-=":
                    result = current - rhs_val
                elif compound_op == "*=":
                    result = current * rhs_val
                elif compound_op == "/=":
                    result = current // rhs_val if rhs_val != 0 else 0
                else:  # %=
                    result = current % rhs_val if rhs_val != 0 else 0
                self.state.set_var(var, str(result))
                return result

        # Simple assignment: var=expr
        eq_idx = expr.find("=")
        if eq_idx > 0 and expr[eq_idx - 1] not in ("!", "<", ">", "="):
            var = expr[:eq_idx].strip()
            if var.isidentifier():
                rhs = expr[eq_idx + 1 :].strip()
                val = self.eval_expr(rhs)
                self.state.set_var(var, str(val))
                return val

        return self.eval_expr(expr)

    def _get_int_var(self, name: str) -> int:
        """Get a variable's value as an integer, defaulting to 0."""
        val = self.state.get_var(name) or "0"
        try:
            return int(val)
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    _PY_KEYWORDS: frozenset[str] = frozenset(
        {"and", "or", "not", "if", "else", "True", "False", "None", "in", "is"}
    )

    def _preprocess(self, expression: str) -> str:
        """Convert shell arithmetic syntax to Python-compatible syntax."""
        expr = expression

        # Handle base#number notation: 10#09 → 9, 16#ff → 255, 2#1010 → 10
        def _replace_base(m: re.Match[str]) -> str:
            base = int(m.group(1))
            try:
                return str(int(m.group(2), base))
            except (ValueError, OverflowError):
                return "0"

        expr = re.sub(r"(\d+)#(\w+)", _replace_base, expr)

        # Convert && to and, || to or
        expr = expr.replace("&&", " and ")
        expr = expr.replace("||", " or ")
        # Convert ! to not (but not != which is already valid)
        expr = re.sub(r"(?<!=)!(?!=)", " not ", expr)
        # Convert ternary: cond ? val : val -> val if cond else val
        # Simple single-level ternary
        m = re.match(r"^(.+?)\?(.+?):(.+)$", expr)
        if m:
            cond, true_expr, false_expr = (
                m.group(1).strip(),
                m.group(2).strip(),
                m.group(3).strip(),
            )
            expr = f"({true_expr}) if ({cond}) else ({false_expr})"
        return expr

    def _expand_braced_expansions(self, expression: str) -> str:
        """Expand ${#arr[@]}, ${#var}, ${arr[n]} in arithmetic context."""

        def _replace_braced(m: re.Match[str]) -> str:
            inner = m.group(1)
            # ${#arr[@]} or ${#arr[*]}
            if inner.startswith("#") and ("[" in inner):
                name = inner[1 : inner.index("[")]
                arr = self.state.get_array(name)
                return str(len(arr)) if arr is not None else "0"
            # ${#var}
            if inner.startswith("#"):
                var = inner[1:]
                val = self.state.get_var(var) or ""
                return str(len(val))
            # ${arr[n]}
            if "[" in inner:
                name = inner[: inner.index("[")]
                subscript = inner[inner.index("[") + 1 : inner.index("]")]
                arr = self.state.get_array(name)
                if arr is not None:
                    try:
                        idx = int(subscript)
                        return arr[idx] if 0 <= idx < len(arr) else "0"
                    except ValueError:
                        return "0"
                val = self.state.get_var(name) or "0"
                return val
            val = self.state.get_var(inner) or "0"
            return val if val.lstrip("-").isdigit() else "0"

        return re.sub(r"\$\{([^}]+)\}", _replace_braced, expression)

    def _substitute_variables(self, expression: str) -> str:
        """Replace ``$var``, ``${var}``, and bare identifiers with values."""

        def _replace(m: re.Match[str]) -> str:
            name = m.group(1) or m.group(2) or m.group(3)
            if name in self._PY_KEYWORDS:
                return name
            if name.isdigit():
                idx = int(name)
                if 1 <= idx <= len(self.state.positional_params):
                    val = self.state.positional_params[idx - 1]
                    return val if val.lstrip("-").isdigit() else "0"
                return "0"
            val = self.state.get_var(name) or ""
            return val if val.lstrip("-").isdigit() else "0"

        return re.sub(
            r"\$\{(\w+)\}|\$(\w+)|(?<![0-9])([a-zA-Z_]\w*)(?!\w*\()",
            _replace,
            expression,
        )

    def _walk(self, node: ast.expr) -> int:
        """Recursively evaluate an AST node.  Only arithmetic is allowed."""
        match node:
            case ast.Constant(value=int(v)):
                return v
            case ast.Constant(value=bool(v)):
                return 1 if v else 0
            case ast.UnaryOp(op=ast.USub(), operand=operand):
                return -self._walk(operand)
            case ast.UnaryOp(op=ast.UAdd(), operand=operand):
                return self._walk(operand)
            case ast.UnaryOp(op=ast.Not(), operand=operand):
                return 1 if self._walk(operand) == 0 else 0
            case ast.UnaryOp(op=ast.Invert(), operand=operand):
                return ~self._walk(operand)
            case ast.BinOp(left=left, op=op, right=right):
                return self._eval_binop(left, op, right)
            case ast.Compare():
                return self._eval_compare(node)
            case ast.BoolOp():
                return self._eval_boolop(node)
            case ast.IfExp(test=test, body=body, orelse=orelse):
                return self._walk(body) if self._walk(test) != 0 else self._walk(orelse)
            case _:
                raise ValueError(f"Unsupported arithmetic node: {type(node).__name__}")

    def _eval_binop(self, left: ast.expr, op: ast.operator, right: ast.expr) -> int:
        lv = self._walk(left)
        rv = self._walk(right)
        match op:
            case ast.Add():
                return lv + rv
            case ast.Sub():
                return lv - rv
            case ast.Mult():
                return lv * rv
            case ast.FloorDiv():
                return lv // rv if rv != 0 else 0
            case ast.Div():
                return int(lv / rv) if rv != 0 else 0
            case ast.Mod():
                return lv % rv if rv != 0 else 0
            case ast.BitAnd():
                return lv & rv
            case ast.BitOr():
                return lv | rv
            case ast.BitXor():
                return lv ^ rv
            case ast.LShift():
                return lv << rv
            case ast.RShift():
                return lv >> rv
            case ast.Pow():
                return lv**rv
            case _:
                raise ValueError(
                    f"Unsupported arithmetic operator: {type(op).__name__}"
                )

    def _eval_compare(self, node: ast.Compare) -> int:
        """Evaluate a comparison chain, returning 1 or 0."""
        left = self._walk(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = self._walk(comparator)
            match op:
                case ast.Eq():
                    result = left == right
                case ast.NotEq():
                    result = left != right
                case ast.Lt():
                    result = left < right
                case ast.LtE():
                    result = left <= right
                case ast.Gt():
                    result = left > right
                case ast.GtE():
                    result = left >= right
                case _:
                    return 0
            if not result:
                return 0
            left = right
        return 1

    def _eval_boolop(self, node: ast.BoolOp) -> int:
        """Evaluate 'and' / 'or' boolean operations."""
        match node.op:
            case ast.And():
                for val_node in node.values:
                    if self._walk(val_node) == 0:
                        return 0
                return 1
            case ast.Or():
                for val_node in node.values:
                    if self._walk(val_node) != 0:
                        return 1
                return 0
            case _:
                return 0
