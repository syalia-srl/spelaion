"""Boolean/test evaluator — implements ``test`` / ``[`` logic.

Follows the Oils split-evaluator pattern.  Extracted from ``builtins.py``
so the evaluation logic can be reused (e.g. inside ``[[ ]]`` in the
future) without depending on the builtin dispatch layer.
"""

from __future__ import annotations

import fnmatch as _fnmatch
import re as _re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


class BoolEvaluator:
    """Evaluate POSIX ``test`` expressions against VFS and shell state.

    Supports unary file tests (``-f``, ``-d``, ``-e``, ``-r``, ``-w``,
    ``-x``, ``-s``), string tests (``-z``, ``-n``), string comparison
    (``=``, ``==``, ``!=``), integer comparison (``-eq``, ``-ne``,
    ``-lt``, ``-gt``, ``-le``, ``-ge``), logical operators (``-a``,
    ``-o``, ``!``), and single-argument truth tests.
    """

    def __init__(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        self.state = state
        self.vfs = vfs

    def eval_test(self, args: list[str]) -> bool:
        """Evaluate *args* as a ``test`` expression.

        The caller is responsible for stripping a trailing ``]`` when
        the command was invoked as ``[``.
        """
        if not args:
            return False

        # Handle leading negation at any length
        if args[0] == "!" and len(args) > 1:
            return not self.eval_test(args[1:])

        if len(args) == 1:
            return len(args[0]) > 0

        if len(args) == 2:
            return self._eval_unary(args[0], args[1])

        if len(args) == 3:
            return self._eval_binary(args[0], args[1], args[2])

        return False

    # ------------------------------------------------------------------
    # Unary operators
    # ------------------------------------------------------------------

    def _eval_unary(self, op: str, operand: str) -> bool:
        match op:
            case "-f":
                return self.vfs.is_file(self.vfs.resolve(operand, self.state.cwd))
            case "-d":
                return self.vfs.is_dir(self.vfs.resolve(operand, self.state.cwd))
            case "-e":
                return self.vfs.exists(self.vfs.resolve(operand, self.state.cwd))
            case "-z":
                return len(operand) == 0
            case "-n":
                return len(operand) > 0
            case "!":
                return not self.eval_test([operand])
            case "-r" | "-w" | "-x":
                return self.vfs.exists(self.vfs.resolve(operand, self.state.cwd))
            case "-s":
                abs_path = self.vfs.resolve(operand, self.state.cwd)
                if self.vfs.is_file(abs_path):
                    return len(self.vfs.read(abs_path)) > 0
                return False
            case _:
                return False

    # ------------------------------------------------------------------
    # Binary operators
    # ------------------------------------------------------------------

    def _eval_binary(self, left: str, op: str, right: str) -> bool:
        match op:
            case "=" | "==":
                return left == right
            case "!=":
                return left != right
            case "-eq" | "-ne" | "-lt" | "-gt" | "-le" | "-ge":
                return self._eval_integer_cmp(left, op, right)
            case "-a":
                return self.eval_test([left]) and self.eval_test([right])
            case "-o":
                return self.eval_test([left]) or self.eval_test([right])
            case _:
                return False

    def _eval_integer_cmp(self, left: str, op: str, right: str) -> bool:
        try:
            lv, rv = int(left), int(right)
        except ValueError:
            return False

        match op:
            case "-eq":
                return lv == rv
            case "-ne":
                return lv != rv
            case "-lt":
                return lv < rv
            case "-gt":
                return lv > rv
            case "-le":
                return lv <= rv
            case "-ge":
                return lv >= rv
            case _:
                return False

    # ------------------------------------------------------------------
    # Extended test: [[ ... ]]
    # ------------------------------------------------------------------

    def eval_extended_test(self, tokens: list[str]) -> bool:
        """Evaluate an extended test expression ([[ ... ]])."""
        self._ext_tokens = tokens
        self._ext_pos = 0
        return self._parse_extended_or()

    def _ext_peek(self) -> str | None:
        if self._ext_pos < len(self._ext_tokens):
            return self._ext_tokens[self._ext_pos]
        return None

    def _ext_consume(self) -> str:
        tok = self._ext_tokens[self._ext_pos]
        self._ext_pos += 1
        return tok

    def _parse_extended_or(self) -> bool:
        """Parse: expr || expr."""
        result = self._parse_extended_and()
        while self._ext_peek() == "||":
            self._ext_consume()
            rhs = self._parse_extended_and()
            result = result or rhs
        return result

    def _parse_extended_and(self) -> bool:
        """Parse: expr && expr."""
        result = self._parse_extended_not()
        while self._ext_peek() == "&&":
            self._ext_consume()
            rhs = self._parse_extended_not()
            result = result and rhs
        return result

    def _parse_extended_not(self) -> bool:
        """Parse: ! expr or primary."""
        if self._ext_peek() == "!":
            self._ext_consume()
            return not self._parse_extended_not()
        return self._parse_extended_primary()

    def _parse_extended_primary(self) -> bool:
        """Parse a primary expression."""
        tok = self._ext_peek()
        if tok is None:
            return False

        # Parenthesised sub-expression
        if tok == "(":
            self._ext_consume()
            result = self._parse_extended_or()
            if self._ext_peek() == ")":
                self._ext_consume()
            return result

        # Unary operators
        if tok in (
            "-f",
            "-d",
            "-e",
            "-r",
            "-w",
            "-x",
            "-s",
            "-z",
            "-n",
            "-L",
            "-h",
            "-p",
            "-S",
            "-b",
            "-c",
            "-t",
        ):
            self._ext_consume()
            operand = self._ext_consume() if self._ext_peek() is not None else ""
            return self._eval_unary(tok, operand)

        # Consume left operand
        left = self._ext_consume()

        # Check for binary operator
        op = self._ext_peek()
        if op is None:
            # Single argument truth test
            return len(left) > 0

        if op in ("==", "=", "!=", "-eq", "-ne", "-lt", "-gt", "-le", "-ge"):
            self._ext_consume()
            right = self._ext_consume() if self._ext_peek() is not None else ""
            return self._eval_extended_binary(left, op, right)

        if op == "=~":
            self._ext_consume()
            # Collect remaining tokens as the regex pattern
            pattern_parts: list[str] = []
            while self._ext_peek() not in (None, "&&", "||", ")"):
                pattern_parts.append(self._ext_consume())
            pattern = " ".join(pattern_parts)
            return self._eval_extended_binary(left, "=~", pattern)

        if op == "<":
            self._ext_consume()
            right = self._ext_consume() if self._ext_peek() is not None else ""
            return left < right

        if op == ">":
            self._ext_consume()
            right = self._ext_consume() if self._ext_peek() is not None else ""
            return left > right

        # Not a known operator — treat as single-argument truth test
        return len(left) > 0

    def _eval_extended_binary(self, left: str, op: str, right: str) -> bool:
        """Evaluate an extended test binary operation."""
        if op in ("=", "=="):
            # Glob matching in [[ ]]
            return _fnmatch.fnmatch(left, right)
        if op == "!=":
            return not _fnmatch.fnmatch(left, right)
        if op == "=~":
            # Regex matching — set BASH_REMATCH on success
            try:
                m = _re.search(right, left)
                if m:
                    self.state.set_var("BASH_REMATCH", m.group(0))
                    # Set BASH_REMATCH[0..n] as array
                    groups = [m.group(0)] + [g or "" for g in m.groups()]
                    self.state.set_array("BASH_REMATCH", groups)
                    return True
                return False
            except _re.error:
                return False
        if op in ("-eq", "-ne", "-lt", "-gt", "-le", "-ge"):
            return self._eval_integer_cmp(left, op, right)
        return False
