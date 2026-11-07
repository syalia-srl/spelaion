"""Structured data commands: jq, yq, patch.

The jq/yq implementations are inherently dynamic-typed (JSON values are Any).
Pyright's strict mode would require pervasive casts throughout the evaluator
for no real safety gain, so we suppress the relevant diagnostics here.
"""
# pyright: reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import base64
import json
import math
import re
import tomllib
import urllib.parse
from typing import TYPE_CHECKING, Any

import yaml

from agentsh.commands._io import read_text, read_text_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# =====================================================================
# jq — JSON processor
# =====================================================================

# -- jq AST node types ------------------------------------------------


class _JqNode:
    """Base class for jq filter AST nodes."""


class _Identity(_JqNode):
    pass


class _Literal(_JqNode):
    def __init__(self, value: Any) -> None:
        self.value = value


class _Field(_JqNode):
    def __init__(self, name: str, optional: bool = False) -> None:
        self.name = name
        self.optional = optional


class _Index(_JqNode):
    def __init__(self, index: _JqNode, optional: bool = False) -> None:
        self.index = index
        self.optional = optional


class _Iterate(_JqNode):
    def __init__(self, optional: bool = False) -> None:
        self.optional = optional


class _Slice(_JqNode):
    def __init__(
        self, start: _JqNode | None, end: _JqNode | None, optional: bool = False
    ) -> None:
        self.start = start
        self.end = end
        self.optional = optional


class _Pipe(_JqNode):
    def __init__(self, left: _JqNode, right: _JqNode) -> None:
        self.left = left
        self.right = right


class _Comma(_JqNode):
    def __init__(self, exprs: list[_JqNode]) -> None:
        self.exprs = exprs


class _FuncCall(_JqNode):
    def __init__(self, name: str, args: list[_JqNode]) -> None:
        self.name = name
        self.args = args


class _ObjectConstruct(_JqNode):
    def __init__(self, pairs: list[tuple[_JqNode | str, _JqNode | None]]) -> None:
        self.pairs = pairs


class _ArrayConstruct(_JqNode):
    def __init__(self, expr: _JqNode | None) -> None:
        self.expr = expr


class _BinOp(_JqNode):
    def __init__(self, op: str, left: _JqNode, right: _JqNode) -> None:
        self.op = op
        self.left = left
        self.right = right


class _UnaryNot(_JqNode):
    def __init__(self, expr: _JqNode) -> None:
        self.expr = expr


class _IfThenElse(_JqNode):
    def __init__(self, cond: _JqNode, then_: _JqNode, else_: _JqNode | None) -> None:
        self.cond = cond
        self.then_ = then_
        self.else_ = else_


class _TryCatch(_JqNode):
    def __init__(self, try_: _JqNode, catch: _JqNode | None) -> None:
        self.try_ = try_
        self.catch = catch


class _StringInterpolation(_JqNode):
    def __init__(self, parts: list[str | _JqNode]) -> None:
        self.parts = parts


class _VarRef(_JqNode):
    def __init__(self, name: str) -> None:
        self.name = name


class _EnvRef(_JqNode):
    def __init__(self, name: str) -> None:
        self.name = name


class _Format(_JqNode):
    def __init__(self, name: str) -> None:
        self.name = name


class _Label(_JqNode):
    """label $name | expr -- used with break for control flow."""

    def __init__(self, name: str, body: _JqNode) -> None:
        self.name = name
        self.body = body


class _Empty(_JqNode):
    pass


class _FuncDef(_JqNode):
    def __init__(
        self, name: str, params: list[str], body: _JqNode, rest: _JqNode
    ) -> None:
        self.name = name
        self.params = params
        self.body = body
        self.rest = rest


class _Recurse(_JqNode):
    pass


class _Optional(_JqNode):
    def __init__(self, expr: _JqNode) -> None:
        self.expr = expr


class _PathExpr(_JqNode):
    def __init__(self, expr: _JqNode) -> None:
        self.expr = expr


class _ReduceExpr(_JqNode):
    def __init__(self, expr: _JqNode, var: str, init: _JqNode, update: _JqNode) -> None:
        self.expr = expr
        self.var = var
        self.init = init
        self.update = update


class _AsPattern(_JqNode):
    def __init__(self, expr: _JqNode, var: str, body: _JqNode) -> None:
        self.expr = expr
        self.var = var
        self.body = body


class _DebugNode(_JqNode):
    pass


class _InputNode(_JqNode):
    pass


class _InputsNode(_JqNode):
    pass


# -- jq lexer ---------------------------------------------------------


class _JqLexError(Exception):
    pass


class _JqParseError(Exception):
    pass


class _JqRuntimeError(Exception):
    pass


class _JqBreak(Exception):
    def __init__(self, label: str) -> None:
        self.label = label


_KEYWORDS = frozenset(
    {
        "if",
        "then",
        "elif",
        "else",
        "end",
        "and",
        "or",
        "not",
        "true",
        "false",
        "null",
        "try",
        "catch",
        "def",
        "as",
        "reduce",
        "empty",
        "label",
        "break",
    }
)

# Keywords that terminate expressions in structural positions.
# These must NOT be consumed as field names after DOT.
_JQ_STRUCTURAL_KW = frozenset(
    {"then", "else", "elif", "end", "catch", "as", "and", "or"}
)


def _jq_tokenize(source: str) -> list[tuple[str, str]]:  # noqa: C901
    """Tokenize a jq filter expression.

    Returns a list of (type, value) tuples where type is one of:
    DOT, LBRACKET, RBRACKET, LBRACE, RBRACE, LPAREN, RPAREN,
    PIPE, COMMA, COLON, SEMICOLON, QUESTION,
    STRING, NUMBER, IDENT, OP, FORMAT, DOLLAR, EOF
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(source)

    while i < n:
        c = source[i]

        # Skip whitespace
        if c in " \t\n\r":
            i += 1
            continue

        # Skip comments
        if c == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue

        # Two-char operators
        if i + 1 < n:
            two = source[i : i + 2]
            if two == "//":
                tokens.append(("OP", "//"))
                i += 2
                continue
            if two in ("==", "!=", "<=", ">="):
                tokens.append(("OP", two))
                i += 2
                continue
            if two == "?/":
                tokens.append(("OP", "?/"))
                i += 2
                continue

        # Single-char tokens
        if c == ".":
            # Check if it's .foo (field access) or .[...] or just .
            if i + 1 < n and (source[i + 1].isalpha() or source[i + 1] == "_"):
                tokens.append(("DOT", "."))
                i += 1
                continue
            if i + 1 < n and source[i + 1] == "[":
                tokens.append(("DOT", "."))
                i += 1
                continue
            # Check if it's a number like .5
            if i + 1 < n and source[i + 1].isdigit():
                j = i + 1
                while j < n and (source[j].isdigit() or source[j] == "."):
                    j += 1
                tokens.append(("NUMBER", source[i:j]))
                i = j
                continue
            tokens.append(("DOT", "."))
            i += 1
            continue

        if c == "[":
            tokens.append(("LBRACKET", "["))
            i += 1
            continue
        if c == "]":
            tokens.append(("RBRACKET", "]"))
            i += 1
            continue
        if c == "{":
            tokens.append(("LBRACE", "{"))
            i += 1
            continue
        if c == "}":
            tokens.append(("RBRACE", "}"))
            i += 1
            continue
        if c == "(":
            tokens.append(("LPAREN", "("))
            i += 1
            continue
        if c == ")":
            tokens.append(("RPAREN", ")"))
            i += 1
            continue
        if c == "|":
            tokens.append(("PIPE", "|"))
            i += 1
            continue
        if c == ",":
            tokens.append(("COMMA", ","))
            i += 1
            continue
        if c == ":":
            tokens.append(("COLON", ":"))
            i += 1
            continue
        if c == ";":
            tokens.append(("SEMICOLON", ";"))
            i += 1
            continue
        if c == "?":
            tokens.append(("QUESTION", "?"))
            i += 1
            continue
        if c == "+":
            tokens.append(("OP", "+"))
            i += 1
            continue
        if c == "-":
            # Could be unary minus or subtraction
            # If preceded by a value token, it's subtraction
            if tokens and tokens[-1][0] in (
                "NUMBER",
                "RBRACKET",
                "RPAREN",
                "IDENT",
                "STRING",
                "DOT",
            ):
                tokens.append(("OP", "-"))
                i += 1
                continue
            # Otherwise check if it's a negative number
            if i + 1 < n and source[i + 1].isdigit():
                j = i + 1
                while j < n and source[j].isdigit():
                    j += 1
                if j < n and source[j] == ".":
                    j += 1
                    while j < n and source[j].isdigit():
                        j += 1
                tokens.append(("NUMBER", source[i:j]))
                i = j
                continue
            tokens.append(("OP", "-"))
            i += 1
            continue
        if c == "*":
            tokens.append(("OP", "*"))
            i += 1
            continue
        if c == "/":
            tokens.append(("OP", "/"))
            i += 1
            continue
        if c == "%":
            tokens.append(("OP", "%"))
            i += 1
            continue
        if c == "<":
            tokens.append(("OP", "<"))
            i += 1
            continue
        if c == ">":
            tokens.append(("OP", ">"))
            i += 1
            continue

        # Strings
        if c == '"':
            s, end = _jq_lex_string(source, i)
            tokens.append(("STRING", s))
            i = end
            continue

        # Numbers
        if c.isdigit():
            j = i
            while j < n and source[j].isdigit():
                j += 1
            if j < n and source[j] == ".":
                j += 1
                while j < n and source[j].isdigit():
                    j += 1
            if j < n and source[j] in "eE":
                j += 1
                if j < n and source[j] in "+-":
                    j += 1
                while j < n and source[j].isdigit():
                    j += 1
            tokens.append(("NUMBER", source[i:j]))
            i = j
            continue

        # @format strings
        if c == "@":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            tokens.append(("FORMAT", source[i:j]))
            i = j
            continue

        # $ variable references
        if c == "$":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            if j == i + 1:
                tokens.append(("DOLLAR", "$"))
            else:
                tokens.append(("DOLLAR", source[i:j]))
            i = j
            continue

        # Identifiers and keywords
        if c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            tokens.append(("IDENT", word))
            i = j
            continue

        raise _JqLexError(f"Unexpected character: {c!r}")

    tokens.append(("EOF", ""))
    return tokens


def _jq_lex_string(source: str, start: int) -> tuple[str, int]:
    """Lex a double-quoted string, handling escapes and interpolations.

    Returns (raw_content_including_quotes, end_position).
    """
    i = start + 1
    n = len(source)
    result: list[str] = ['"']

    while i < n:
        c = source[i]
        if c == '"':
            result.append('"')
            return "".join(result), i + 1
        if c == "\\" and i + 1 < n:
            nc = source[i + 1]
            if nc == "(":
                # String interpolation \(...)
                result.append("\\(")
                i += 2
                depth = 1
                while i < n and depth > 0:
                    if source[i] == "(":
                        depth += 1
                    elif source[i] == ")":
                        depth -= 1
                        if depth == 0:
                            result.append(")")
                            i += 1
                            break
                    result.append(source[i])
                    i += 1
                continue
            result.append("\\")
            result.append(nc)
            i += 2
            continue
        result.append(c)
        i += 1

    result.append('"')
    return "".join(result), i


# -- jq parser --------------------------------------------------------


class _JqParser:
    """Recursive descent parser for jq filter expressions."""

    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> tuple[str, str]:
        if self.pos < len(self.tokens):
            return self.tokens[self.pos]
        return ("EOF", "")

    def advance(self) -> tuple[str, str]:
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, ttype: str, tval: str | None = None) -> tuple[str, str]:
        tok = self.advance()
        if tok[0] != ttype:
            raise _JqParseError(f"Expected {ttype}({tval}), got {tok[0]}({tok[1]})")
        if tval is not None and tok[1] != tval:
            raise _JqParseError(f"Expected {ttype}({tval}), got {tok[0]}({tok[1]})")
        return tok

    def parse(self) -> _JqNode:
        node = self._parse_pipe()
        return node

    def _parse_pipe(self) -> _JqNode:
        node = self._parse_comma()
        while self.peek() == ("PIPE", "|"):
            self.advance()
            right = self._parse_comma()
            node = _Pipe(node, right)
        return node

    def _parse_comma(self) -> _JqNode:
        node = self._parse_assign()
        parts = [node]
        while self.peek() == ("COMMA", ","):
            self.advance()
            parts.append(self._parse_assign())
        if len(parts) == 1:
            return parts[0]
        return _Comma(parts)

    def _parse_assign(self) -> _JqNode:
        return self._parse_as()

    def _parse_as(self) -> _JqNode:
        node = self._parse_alternative()
        if self.peek() == ("IDENT", "as"):
            self.advance()
            _, var_name = self.expect("DOLLAR")
            self.expect("PIPE", "|")
            body = self._parse_pipe()
            return _AsPattern(node, var_name, body)
        return node

    def _parse_alternative(self) -> _JqNode:
        node = self._parse_or()
        while self.peek() == ("OP", "//"):
            self.advance()
            right = self._parse_or()
            node = _BinOp("//", node, right)
        return node

    def _parse_or(self) -> _JqNode:
        node = self._parse_and()
        while self.peek() == ("IDENT", "or"):
            self.advance()
            right = self._parse_and()
            node = _BinOp("or", node, right)
        return node

    def _parse_and(self) -> _JqNode:
        node = self._parse_not()
        while self.peek() == ("IDENT", "and"):
            self.advance()
            right = self._parse_not()
            node = _BinOp("and", node, right)
        return node

    def _parse_not(self) -> _JqNode:
        # In jq, 'not' is a postfix builtin, not a prefix operator.
        # It is handled as a primary/builtin in _parse_primary.
        return self._parse_comparison()

    def _parse_comparison(self) -> _JqNode:
        node = self._parse_addition()
        if self.peek()[0] == "OP" and self.peek()[1] in (
            "==",
            "!=",
            "<",
            ">",
            "<=",
            ">=",
        ):
            op = self.advance()[1]
            right = self._parse_addition()
            node = _BinOp(op, node, right)
        return node

    def _parse_addition(self) -> _JqNode:
        node = self._parse_multiplication()
        while self.peek()[0] == "OP" and self.peek()[1] in ("+", "-"):
            op = self.advance()[1]
            right = self._parse_multiplication()
            node = _BinOp(op, node, right)
        return node

    def _parse_multiplication(self) -> _JqNode:
        node = self._parse_postfix()
        while self.peek()[0] == "OP" and self.peek()[1] in ("*", "/", "%"):
            op = self.advance()[1]
            right = self._parse_postfix()
            node = _BinOp(op, node, right)
        return node

    def _parse_postfix(self) -> _JqNode:
        node = self._parse_primary()
        while True:
            tt, _tv = self.peek()
            if tt == "DOT" and self.pos + 1 < len(self.tokens):
                next_tt, next_tv = self.tokens[self.pos + 1]
                if next_tt == "IDENT" and next_tv not in _JQ_STRUCTURAL_KW:
                    self.advance()  # DOT
                    _, field_name = self.advance()  # IDENT
                    optional = False
                    if self.peek() == ("QUESTION", "?"):
                        self.advance()
                        optional = True
                    field_node = _Field(field_name, optional=optional)
                    node = _Pipe(node, field_node)
                    continue
                if next_tt == "LBRACKET":
                    self.advance()  # DOT
                    bracket_node = self._parse_bracket_suffix()
                    node = _Pipe(node, bracket_node)
                    continue
            if tt == "LBRACKET":
                bracket_node = self._parse_bracket_suffix()
                node = _Pipe(node, bracket_node)
                continue
            if tt == "QUESTION":
                self.advance()
                node = _Optional(node)
                continue
            break
        return node

    def _parse_bracket_suffix(self) -> _JqNode:
        """Parse [...] suffix, which may be index, iterate, or slice."""
        self.expect("LBRACKET")
        optional = False

        # Check for empty brackets: []
        if self.peek() == ("RBRACKET", "]"):
            self.advance()
            if self.peek() == ("QUESTION", "?"):
                self.advance()
                optional = True
            return _Iterate(optional=optional)

        # Check for slice: [start:end]
        first: _JqNode | None = None
        if self.peek() != ("COLON", ":"):
            first = self._parse_pipe()

        if self.peek() == ("COLON", ":"):
            self.advance()
            end: _JqNode | None = None
            if self.peek() != ("RBRACKET", "]"):
                end = self._parse_pipe()
            self.expect("RBRACKET")
            if self.peek() == ("QUESTION", "?"):
                self.advance()
                optional = True
            return _Slice(first, end, optional=optional)

        self.expect("RBRACKET")
        if self.peek() == ("QUESTION", "?"):
            self.advance()
            optional = True
        if first is None:
            return _Iterate(optional=optional)
        return _Index(first, optional=optional)

    def _parse_primary(self) -> _JqNode:  # noqa: C901
        tt, tv = self.peek()

        # Identity
        if tt == "DOT":
            self.advance()
            # Check for .field (but not keywords)
            ntt, ntv = self.peek()
            if ntt == "IDENT" and ntv not in _JQ_STRUCTURAL_KW:
                self.advance()
                optional = False
                if self.peek() == ("QUESTION", "?"):
                    self.advance()
                    optional = True
                return _Field(ntv, optional=optional)
            if ntt == "LBRACKET":
                bracket_node = self._parse_bracket_suffix()
                return _Pipe(_Identity(), bracket_node)
            return _Identity()

        # Negative number
        if tt == "OP" and tv == "-":
            self.advance()
            _, numval = self.expect("NUMBER")
            return _Literal(_parse_number("-" + numval))

        # Number
        if tt == "NUMBER":
            self.advance()
            return _Literal(_parse_number(tv))

        # String
        if tt == "STRING":
            self.advance()
            return _parse_jq_string(tv)

        # Format string @base64, @uri, etc.
        if tt == "FORMAT":
            self.advance()
            # Check if followed by a string for "format string" usage
            if self.peek()[0] == "STRING":
                _, sv = self.advance()
                str_node = _parse_jq_string(sv)
                return _Pipe(str_node, _Format(tv))
            return _Format(tv)

        # Variable reference $NAME
        if tt == "DOLLAR":
            self.advance()
            return _VarRef(tv)

        # Array construction [...]
        if tt == "LBRACKET":
            self.advance()
            if self.peek() == ("RBRACKET", "]"):
                self.advance()
                return _ArrayConstruct(None)
            inner = self._parse_pipe()
            self.expect("RBRACKET")
            return _ArrayConstruct(inner)

        # Object construction {...}
        if tt == "LBRACE":
            return self._parse_object_construct()

        # Parenthesized expression
        if tt == "LPAREN":
            self.advance()
            inner = self._parse_pipe()
            self.expect("RPAREN")
            return inner

        # Keywords and builtins
        if tt == "IDENT":
            if tv == "if":
                return self._parse_if()
            if tv == "try":
                return self._parse_try()
            if tv == "def":
                return self._parse_def()
            if tv == "reduce":
                return self._parse_reduce()
            if tv == "label":
                return self._parse_label()
            if tv == "true":
                self.advance()
                return _Literal(True)
            if tv == "false":
                self.advance()
                return _Literal(False)
            if tv == "null":
                self.advance()
                return _Literal(None)
            if tv == "empty":
                self.advance()
                return _Empty()
            if tv == "not":
                self.advance()
                return _UnaryNot(_Identity())
            if tv == "env":
                self.advance()
                # env.NAME
                if self.peek() == ("DOT", "."):
                    self.advance()
                    _, name = self.expect("IDENT")
                    return _EnvRef(name)
                return _FuncCall("env", [])
            if tv == "recurse":
                self.advance()
                return _Recurse()
            if tv == "debug":
                self.advance()
                return _DebugNode()
            if tv == "input":
                self.advance()
                return _InputNode()
            if tv == "inputs":
                self.advance()
                return _InputsNode()
            if tv == "break":
                self.advance()
                _, label = self.expect("DOLLAR")
                return _FuncCall("break", [_VarRef(label)])
            if tv == "path":
                self.advance()
                self.expect("LPAREN")
                expr = self._parse_pipe()
                self.expect("RPAREN")
                return _PathExpr(expr)

            # Generic function / builtin call
            self.advance()
            name = tv
            args: list[_JqNode] = []
            if self.peek() == ("LPAREN", "("):
                self.advance()
                if self.peek() != ("RPAREN", ")"):
                    args.append(self._parse_pipe())
                    while self.peek() == ("SEMICOLON", ";"):
                        self.advance()
                        args.append(self._parse_pipe())
                self.expect("RPAREN")
            return _FuncCall(name, args)

        raise _JqParseError(f"Unexpected token: {tt}({tv})")

    def _parse_object_construct(self) -> _JqNode:
        self.expect("LBRACE")
        pairs: list[tuple[_JqNode | str, _JqNode | None]] = []

        while self.peek() != ("RBRACE", "}"):
            if pairs:
                self.expect("COMMA")
                if self.peek() == ("RBRACE", "}"):
                    break

            tt, tv = self.peek()

            # String key: "key": value
            if tt == "STRING":
                self.advance()
                key_str = _unescape_jq_string(tv)
                if self.peek() == ("COLON", ":"):
                    self.advance()
                    val = self._parse_alternative()
                    pairs.append((key_str, val))
                else:
                    pairs.append((key_str, None))
            elif tt == "IDENT":
                self.advance()
                key_name = tv
                if self.peek() == ("COLON", ":"):
                    self.advance()
                    val = self._parse_alternative()
                    pairs.append((key_name, val))
                else:
                    # Shorthand: {name} = {name: .name}
                    pairs.append((key_name, _Field(key_name)))
            elif tt == "LPAREN":
                # Computed key: (expr): value
                self.advance()
                key_expr = self._parse_pipe()
                self.expect("RPAREN")
                self.expect("COLON")
                val = self._parse_alternative()
                pairs.append((key_expr, val))
            elif tt == "DOT":
                # .field shorthand or .field: value
                field_node = self._parse_primary()
                if self.peek() == ("COLON", ":"):
                    self.advance()
                    val = self._parse_alternative()
                    # Extract key name from field node
                    if isinstance(field_node, _Field):
                        pairs.append((field_node.name, val))
                    else:
                        pairs.append((field_node, val))
                elif isinstance(field_node, _Field):
                    pairs.append((field_node.name, field_node))
                else:
                    pairs.append((field_node, None))
            else:
                raise _JqParseError(f"Unexpected token in object: {tt}({tv})")

        self.expect("RBRACE")
        return _ObjectConstruct(pairs)

    def _parse_if(self) -> _JqNode:
        self.expect("IDENT", "if")
        cond = self._parse_pipe()
        self.expect("IDENT", "then")
        then_ = self._parse_pipe()
        else_: _JqNode | None = None

        if self.peek() == ("IDENT", "elif"):
            # Desugar elif to nested if
            else_ = self._parse_if()
            # Don't expect "end" since the inner if already consumed it
            return _IfThenElse(cond, then_, else_)

        if self.peek() == ("IDENT", "else"):
            self.advance()
            else_ = self._parse_pipe()

        self.expect("IDENT", "end")
        return _IfThenElse(cond, then_, else_)

    def _parse_try(self) -> _JqNode:
        self.expect("IDENT", "try")
        try_expr = self._parse_postfix()
        catch_expr: _JqNode | None = None
        if self.peek() == ("IDENT", "catch"):
            self.advance()
            catch_expr = self._parse_postfix()
        return _TryCatch(try_expr, catch_expr)

    def _parse_def(self) -> _JqNode:
        self.expect("IDENT", "def")
        _, name = self.expect("IDENT")
        params: list[str] = []
        if self.peek() == ("LPAREN", "("):
            self.advance()
            if self.peek() != ("RPAREN", ")"):
                _, p = self.advance()
                params.append(p)
                while self.peek() == ("SEMICOLON", ";"):
                    self.advance()
                    _, p = self.advance()
                    params.append(p)
            self.expect("RPAREN")
        self.expect("COLON")
        body = self._parse_pipe()
        self.expect("SEMICOLON")
        rest = self._parse_pipe()
        return _FuncDef(name, params, body, rest)

    def _parse_reduce(self) -> _JqNode:
        self.expect("IDENT", "reduce")
        expr = self._parse_postfix()
        self.expect("IDENT", "as")
        _, var_name = self.expect("DOLLAR")
        self.expect("LPAREN")
        init = self._parse_pipe()
        self.expect("SEMICOLON")
        update = self._parse_pipe()
        self.expect("RPAREN")
        return _ReduceExpr(expr, var_name, init, update)

    def _parse_label(self) -> _JqNode:
        self.expect("IDENT", "label")
        _, label_name = self.expect("DOLLAR")
        self.expect("PIPE", "|")
        body = self._parse_pipe()
        return _Label(label_name, body)


def _parse_number(s: str) -> int | float:
    if "." in s or "e" in s.lower():
        return float(s)
    return int(s)


def _unescape_jq_string(s: str) -> str:
    """Unescape a jq string token (with surrounding quotes)."""
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    result: list[str] = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            nc = s[i + 1]
            if nc == "n":
                result.append("\n")
            elif nc == "t":
                result.append("\t")
            elif nc == "r":
                result.append("\r")
            elif nc == "\\":
                result.append("\\")
            elif nc == '"':
                result.append('"')
            elif nc == "/":
                result.append("/")
            elif nc == "(":
                # String interpolation marker
                result.append("\\(")
            elif nc == "u" and i + 5 < len(s):
                hex_str = s[i + 2 : i + 6]
                try:
                    result.append(chr(int(hex_str, 16)))
                except ValueError:
                    result.append("\\u" + hex_str)
                i += 4
            else:
                result.append(nc)
            i += 2
        else:
            result.append(s[i])
            i += 1
    return "".join(result)


def _parse_jq_string(s: str) -> _JqNode:
    """Parse a jq string literal, handling interpolation."""
    if "\\(" not in s:
        return _Literal(_unescape_jq_string(s))

    # Has interpolation: split into parts
    inner = s[1:-1] if s.startswith('"') and s.endswith('"') else s
    parts: list[str | _JqNode] = []
    i = 0
    current: list[str] = []

    while i < len(inner):
        if inner[i] == "\\" and i + 1 < len(inner) and inner[i + 1] == "(":
            # Flush current text
            if current:
                parts.append(_unescape_jq_string('"' + "".join(current) + '"'))
                current = []
            # Find matching )
            i += 2
            depth = 1
            expr_chars: list[str] = []
            while i < len(inner) and depth > 0:
                if inner[i] == "(":
                    depth += 1
                elif inner[i] == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                expr_chars.append(inner[i])
                i += 1
            expr_src = "".join(expr_chars)
            tokens = _jq_tokenize(expr_src)
            parser = _JqParser(tokens)
            node = parser.parse()
            parts.append(node)
        elif inner[i] == "\\" and i + 1 < len(inner):
            current.append(inner[i])
            current.append(inner[i + 1])
            i += 2
        else:
            current.append(inner[i])
            i += 1

    if current:
        parts.append(_unescape_jq_string('"' + "".join(current) + '"'))

    if len(parts) == 1 and isinstance(parts[0], str):
        return _Literal(parts[0])

    return _StringInterpolation(parts)


# -- jq evaluator -----------------------------------------------------


class _JqEvaluator:
    """Evaluates a jq AST against JSON data, yielding multiple outputs."""

    def __init__(
        self,
        variables: dict[str, Any] | None = None,
        env_vars: dict[str, str] | None = None,
        user_funcs: dict[str, tuple[list[str], _JqNode]] | None = None,
        all_inputs: list[Any] | None = None,
        input_index: int = 0,
        stderr: Any | None = None,
    ) -> None:
        self.variables: dict[str, Any] = dict(variables or {})
        self.env_vars: dict[str, str] = dict(env_vars or {})
        self.user_funcs: dict[str, tuple[list[str], _JqNode]] = dict(user_funcs or {})
        self.all_inputs: list[Any] = list(all_inputs or [])
        self.input_index = input_index
        self.stderr = stderr

    def run(self, node: _JqNode, data: Any) -> list[Any]:  # noqa: C901
        """Evaluate a node and return list of output values."""
        if isinstance(node, _Identity):
            return [data]

        if isinstance(node, _Literal):
            return [node.value]

        if isinstance(node, _Field):
            return self._eval_field(node, data)

        if isinstance(node, _Index):
            idx_vals = self.run(node.index, data)
            results: list[Any] = []
            for idx in idx_vals:
                try:
                    results.extend(self._do_index(data, idx, node.optional))
                except _JqRuntimeError:
                    if node.optional:
                        continue
                    raise
            return results

        if isinstance(node, _Iterate):
            return self._eval_iterate(node, data)

        if isinstance(node, _Slice):
            return self._eval_slice(node, data)

        if isinstance(node, _Pipe):
            left_results = self.run(node.left, data)
            all_results: list[Any] = []
            for val in left_results:
                all_results.extend(self.run(node.right, val))
            return all_results

        if isinstance(node, _Comma):
            results = []
            for expr in node.exprs:
                results.extend(self.run(expr, data))
            return results

        if isinstance(node, _FuncCall):
            return self._eval_func(node, data)

        if isinstance(node, _ObjectConstruct):
            return self._eval_object(node, data)

        if isinstance(node, _ArrayConstruct):
            if node.expr is None:
                return [[]]
            inner = self.run(node.expr, data)
            return [inner]

        if isinstance(node, _BinOp):
            return self._eval_binop(node, data)

        if isinstance(node, _UnaryNot):
            vals = self.run(node.expr, data)
            return [not _is_truthy(v) for v in vals]

        if isinstance(node, _IfThenElse):
            return self._eval_if(node, data)

        if isinstance(node, _TryCatch):
            return self._eval_try(node, data)

        if isinstance(node, _StringInterpolation):
            return self._eval_interpolation(node, data)

        if isinstance(node, _VarRef):
            name = node.name
            if name in self.variables:
                return [self.variables[name]]
            raise _JqRuntimeError(f"Undefined variable: {name}")

        if isinstance(node, _EnvRef):
            return [self.env_vars.get(node.name, None)]

        if isinstance(node, _Format):
            return self._eval_format(node, data)

        if isinstance(node, _Empty):
            return []

        if isinstance(node, _FuncDef):
            self.user_funcs[node.name] = (node.params, node.body)
            return self.run(node.rest, data)

        if isinstance(node, _Recurse):
            return self._eval_recurse(data)

        if isinstance(node, _Optional):
            try:
                return self.run(node.expr, data)
            except (_JqRuntimeError, TypeError, KeyError, IndexError):
                return []

        if isinstance(node, _PathExpr):
            return self._eval_path(node.expr, data)

        if isinstance(node, _ReduceExpr):
            return self._eval_reduce(node, data)

        if isinstance(node, _AsPattern):
            return self._eval_as(node, data)

        if isinstance(node, _DebugNode):
            if self.stderr is not None:
                self.stderr.write(f'["DEBUG:",{json.dumps(data)}]\n')
            return [data]

        if isinstance(node, _InputNode):
            if self.input_index < len(self.all_inputs):
                val = self.all_inputs[self.input_index]
                self.input_index += 1
                return [val]
            return []

        if isinstance(node, _InputsNode):
            results = list(self.all_inputs[self.input_index :])
            self.input_index = len(self.all_inputs)
            return results

        if isinstance(node, _Label):
            try:
                return self.run(node.body, data)
            except _JqBreak as brk:
                if brk.label == node.name:
                    return []
                raise

        raise _JqRuntimeError(f"Unknown node type: {type(node).__name__}")

    def _eval_field(self, node: _Field, data: Any) -> list[Any]:
        if isinstance(data, dict):
            if node.name in data:
                return [data[node.name]]
            if node.optional:
                return []
            return [None]
        if data is None:
            return [None]
        if node.optional:
            return []
        raise _JqRuntimeError(
            f'Cannot index {_jq_type(data)} with string "{node.name}"'
        )

    def _do_index(self, data: Any, idx: Any, optional: bool) -> list[Any]:
        if isinstance(data, list) and isinstance(idx, (int, float)):
            i = int(idx)
            if i < 0:
                i += len(data)
            if 0 <= i < len(data):
                return [data[i]]
            return [None]
        if isinstance(data, dict) and isinstance(idx, str):
            return [data.get(idx, None)]
        if data is None:
            return [None]
        if optional:
            return []
        raise _JqRuntimeError(f"Cannot index {_jq_type(data)} with {_jq_type(idx)}")

    def _eval_iterate(self, node: _Iterate, data: Any) -> list[Any]:
        if isinstance(data, list):
            return list(data)
        if isinstance(data, dict):
            return list(data.values())
        if data is None:
            if node.optional:
                return []
            return []
        if node.optional:
            return []
        raise _JqRuntimeError(f"Cannot iterate over {_jq_type(data)}")

    def _eval_slice(self, node: _Slice, data: Any) -> list[Any]:
        if not isinstance(data, (list, str)):
            raise _JqRuntimeError(f"Cannot slice {_jq_type(data)}")
        start = None
        end = None
        if node.start is not None:
            sv = self.run(node.start, data)
            if sv:
                start = int(sv[0])
        if node.end is not None:
            ev = self.run(node.end, data)
            if ev:
                end = int(ev[0])
        return [data[start:end]]

    def _eval_func(self, node: _FuncCall, data: Any) -> list[Any]:  # noqa: C901
        name = node.name
        args = node.args

        # User-defined functions
        if name in self.user_funcs:
            params, body = self.user_funcs[name]
            saved = dict(self.variables)
            for i, param_name in enumerate(params):
                if i < len(args):
                    # In jq, function params are filters, not values.
                    # For simplicity, evaluate them and bind.
                    vals = self.run(args[i], data)
                    self.variables[param_name] = vals[0] if vals else None
            try:
                return self.run(body, data)
            finally:
                self.variables = saved

        # Built-in functions
        if name == "length":
            return [_jq_length(data)]
        if name in ("keys", "keys_unsorted"):
            return self._eval_keys(data, name == "keys")
        if name == "values":
            if isinstance(data, dict):
                return [list(data.values())]
            if isinstance(data, list):
                return [list(data)]
            raise _JqRuntimeError(f"Cannot get values of {_jq_type(data)}")
        if name == "type":
            return [_jq_type(data)]
        if name == "to_entries":
            if not isinstance(data, dict):
                raise _JqRuntimeError(f"Cannot convert {_jq_type(data)} to entries")
            return [[{"key": k, "value": v} for k, v in data.items()]]
        if name == "from_entries":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot convert {_jq_type(data)} from entries")
            result_fe: dict[str, Any] = {}
            for entry in data:
                if isinstance(entry, dict):
                    k = entry.get("key", entry.get("name", ""))
                    v = entry.get("value", None)
                    result_fe[str(k)] = v
            return [result_fe]
        if name == "with_entries":
            if not isinstance(data, dict):
                raise _JqRuntimeError(f"Cannot use with_entries on {_jq_type(data)}")
            if not args:
                return [data]
            entries = [{"key": k, "value": v} for k, v in data.items()]
            new_entries: list[Any] = []
            for entry in entries:
                new_entries.extend(self.run(args[0], entry))
            result_we: dict[str, Any] = {}
            for entry in new_entries:
                if isinstance(entry, dict):
                    k = entry.get("key", entry.get("name", ""))
                    v = entry.get("value", None)
                    result_we[str(k)] = v
            return [result_we]
        if name == "has":
            if not args:
                raise _JqRuntimeError("has requires 1 argument")
            key_vals = self.run(args[0], data)
            for k in key_vals:
                if isinstance(data, dict):
                    return [k in data]
                if isinstance(data, list) and isinstance(k, (int, float)):
                    return [0 <= int(k) < len(data)]
            return [False]
        if name == "in":
            if not args:
                raise _JqRuntimeError("in requires 1 argument")
            containers = self.run(args[0], data)
            for container in containers:
                if isinstance(container, dict):
                    key = str(data) if not isinstance(data, str) else data
                    return [key in container]
                if isinstance(container, list):
                    return [data in container]
            return [False]
        if name == "map":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot map over {_jq_type(data)}")
            if not args:
                return [data]
            result_list: list[Any] = []
            for item in data:
                result_list.extend(self.run(args[0], item))
            return [result_list]
        if name == "map_values":
            if not args:
                return [data]
            if isinstance(data, dict):
                result_mv: dict[str, Any] = {}
                for k, v in data.items():
                    vals = self.run(args[0], v)
                    if vals:
                        result_mv[k] = vals[0]
                return [result_mv]
            if isinstance(data, list):
                result_list = []
                for v in data:
                    vals = self.run(args[0], v)
                    if vals:
                        result_list.append(vals[0])
                return [result_list]
            raise _JqRuntimeError(f"Cannot map_values over {_jq_type(data)}")
        if name == "select":
            if not args:
                return [data]
            vals = self.run(args[0], data)
            for v in vals:
                if _is_truthy(v):
                    return [data]
            return []
        if name == "empty":
            return []
        if name == "error":
            msg = "error"
            if args:
                vs = self.run(args[0], data)
                if vs:
                    msg = str(vs[0])
            raise _JqRuntimeError(msg)
        if name == "not":
            return [not _is_truthy(data)]
        if name == "add":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot add {_jq_type(data)}")
            if not data:
                return [None]
            result_add: Any = data[0]
            for item in data[1:]:
                if result_add is None:
                    result_add = item
                elif (isinstance(result_add, str) and isinstance(item, str)) or (
                    isinstance(result_add, list) and isinstance(item, list)
                ):
                    result_add = result_add + item  # type: ignore[operator]
                elif isinstance(result_add, dict) and isinstance(item, dict):
                    result_add = {**result_add, **item}
                elif isinstance(result_add, (int, float)) and isinstance(
                    item, (int, float)
                ):
                    result_add = result_add + item
                elif item is None:
                    pass
                else:
                    result_add = result_add + item
            return [result_add]
        if name == "any":
            if args:
                if isinstance(data, list):
                    for item in data:
                        vals = self.run(args[0], item)
                        for v in vals:
                            if _is_truthy(v):
                                return [True]
                    return [False]
                return [False]
            if isinstance(data, list):
                return [any(_is_truthy(x) for x in data)]
            return [_is_truthy(data)]
        if name == "all":
            if args:
                if isinstance(data, list):
                    for item in data:
                        vals = self.run(args[0], item)
                        for v in vals:
                            if not _is_truthy(v):
                                return [False]
                    return [True]
                return [True]
            if isinstance(data, list):
                return [all(_is_truthy(x) for x in data)]
            return [_is_truthy(data)]
        if name == "sort":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot sort {_jq_type(data)}")
            return [sorted(data, key=_jq_sort_key)]
        if name == "sort_by":
            if not isinstance(data, list) or not args:
                raise _JqRuntimeError("sort_by requires array and argument")

            def _sort_by_key(item: Any) -> Any:
                vals = self.run(args[0], item)
                v = vals[0] if vals else None
                return _jq_sort_key(v)

            return [sorted(data, key=_sort_by_key)]
        if name == "group_by":
            if not isinstance(data, list) or not args:
                raise _JqRuntimeError("group_by requires array and argument")
            groups: dict[str, list[Any]] = {}
            order: list[str] = []
            for item in data:
                vals = self.run(args[0], item)
                key = json.dumps(vals[0] if vals else None, sort_keys=True)
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(item)
            return [[groups[k] for k in order]]
        if name == "unique":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot unique {_jq_type(data)}")
            seen: list[str] = []
            result_uniq: list[Any] = []
            for item in sorted(data, key=_jq_sort_key):
                key = json.dumps(item, sort_keys=True)
                if key not in seen:
                    seen.append(key)
                    result_uniq.append(item)
            return [result_uniq]
        if name == "unique_by":
            if not isinstance(data, list) or not args:
                raise _JqRuntimeError("unique_by requires array and argument")
            seen_ub: list[str] = []
            result_ub: list[Any] = []
            for item in data:
                vals = self.run(args[0], item)
                key = json.dumps(vals[0] if vals else None, sort_keys=True)
                if key not in seen_ub:
                    seen_ub.append(key)
                    result_ub.append(item)
            return [result_ub]
        if name == "flatten":
            if not isinstance(data, list):
                raise _JqRuntimeError(f"Cannot flatten {_jq_type(data)}")
            depth = 999999  # Default: fully recursive
            if args:
                dv = self.run(args[0], data)
                if dv and isinstance(dv[0], (int, float)):
                    depth = int(dv[0])
            return [_flatten(data, depth)]
        if name == "min":
            if not isinstance(data, list) or not data:
                return [None]
            return [min(data, key=_jq_sort_key)]
        if name == "min_by":
            if not isinstance(data, list) or not data or not args:
                return [None]

            def _min_key(item: Any) -> Any:
                vals = self.run(args[0], item)
                return _jq_sort_key(vals[0] if vals else None)

            return [min(data, key=_min_key)]
        if name == "max":
            if not isinstance(data, list) or not data:
                return [None]
            return [max(data, key=_jq_sort_key)]
        if name == "max_by":
            if not isinstance(data, list) or not data or not args:
                return [None]

            def _max_key(item: Any) -> Any:
                vals = self.run(args[0], item)
                return _jq_sort_key(vals[0] if vals else None)

            return [max(data, key=_max_key)]
        if name == "reverse":
            if isinstance(data, list):
                return [list(reversed(data))]
            if isinstance(data, str):
                return [data[::-1]]
            raise _JqRuntimeError(f"Cannot reverse {_jq_type(data)}")
        if name == "contains":
            if not args:
                raise _JqRuntimeError("contains requires 1 argument")
            vals = self.run(args[0], data)
            if vals:
                return [_jq_contains(data, vals[0])]
            return [False]
        if name == "inside":
            if not args:
                raise _JqRuntimeError("inside requires 1 argument")
            vals = self.run(args[0], data)
            if vals:
                return [_jq_contains(vals[0], data)]
            return [False]
        if name == "split":
            if not isinstance(data, str) or not args:
                raise _JqRuntimeError("split requires string input")
            delim_vals = self.run(args[0], data)
            delim = str(delim_vals[0]) if delim_vals else ""
            return [data.split(delim)]
        if name == "join":
            if not isinstance(data, list) or not args:
                raise _JqRuntimeError("join requires array input")
            delim_vals = self.run(args[0], data)
            delim = str(delim_vals[0]) if delim_vals else ""
            return [delim.join(str(x) if x is not None else "" for x in data)]
        if name == "test":
            if not isinstance(data, str) or not args:
                return [False]
            pat_vals = self.run(args[0], data)
            pat = str(pat_vals[0]) if pat_vals else ""
            flags_str = ""
            if len(args) > 1:
                fv = self.run(args[1], data)
                if fv:
                    flags_str = str(fv[0])
            re_flags = _jq_re_flags(flags_str)
            try:
                return [bool(re.search(pat, data, re_flags))]
            except re.error:
                return [False]
        if name == "match":
            if not isinstance(data, str) or not args:
                return [None]
            pat_vals = self.run(args[0], data)
            pat = str(pat_vals[0]) if pat_vals else ""
            flags_str = ""
            if len(args) > 1:
                fv = self.run(args[1], data)
                if fv:
                    flags_str = str(fv[0])
            re_flags = _jq_re_flags(flags_str)
            try:
                m = re.search(pat, data, re_flags)
            except re.error:
                return [None]
            if m is None:
                return [None]
            captures = [
                {
                    "offset": g_start,
                    "length": g_end - g_start,
                    "string": data[g_start:g_end],
                    "name": None,
                }
                for g_start, g_end in m.regs[1:]
            ]
            return [
                {
                    "offset": m.start(),
                    "length": m.end() - m.start(),
                    "string": m.group(),
                    "captures": captures,
                }
            ]
        if name == "capture":
            if not isinstance(data, str) or not args:
                return [{}]
            pat_vals = self.run(args[0], data)
            pat = str(pat_vals[0]) if pat_vals else ""
            try:
                m = re.search(pat, data)
            except re.error:
                return [{}]
            if m is None:
                return [{}]
            return [m.groupdict()]
        if name == "scan":
            if not isinstance(data, str) or not args:
                return [[]]
            pat_vals = self.run(args[0], data)
            pat = str(pat_vals[0]) if pat_vals else ""
            try:
                matches = re.findall(pat, data)
            except re.error:
                return [[]]
            return [matches]
        if name == "gsub":
            return self._eval_regex_replace(data, args, global_replace=True)
        if name == "sub":
            return self._eval_regex_replace(data, args, global_replace=False)
        if name == "ascii_downcase":
            if isinstance(data, str):
                return [data.lower()]
            raise _JqRuntimeError(f"Cannot downcase {_jq_type(data)}")
        if name == "ascii_upcase":
            if isinstance(data, str):
                return [data.upper()]
            raise _JqRuntimeError(f"Cannot upcase {_jq_type(data)}")
        if name == "ltrimstr":
            if not isinstance(data, str) or not args:
                return [data]
            pv = self.run(args[0], data)
            prefix = str(pv[0]) if pv else ""
            if data.startswith(prefix):
                return [data[len(prefix) :]]
            return [data]
        if name == "rtrimstr":
            if not isinstance(data, str) or not args:
                return [data]
            sv = self.run(args[0], data)
            suffix = str(sv[0]) if sv else ""
            if suffix and data.endswith(suffix):
                return [data[: -len(suffix)]]
            return [data]
        if name == "startswith":
            if not isinstance(data, str) or not args:
                return [False]
            pv = self.run(args[0], data)
            prefix = str(pv[0]) if pv else ""
            return [data.startswith(prefix)]
        if name == "endswith":
            if not isinstance(data, str) or not args:
                return [False]
            sv = self.run(args[0], data)
            suffix = str(sv[0]) if sv else ""
            return [data.endswith(suffix)]
        if name == "tonumber":
            if isinstance(data, (int, float)):
                return [data]
            if isinstance(data, str):
                try:
                    if "." in data or "e" in data.lower():
                        return [float(data)]
                    return [int(data)]
                except ValueError as exc:
                    raise _JqRuntimeError(f"Cannot convert {data!r} to number") from exc
            raise _JqRuntimeError(f"Cannot convert {_jq_type(data)} to number")
        if name == "tostring":
            if isinstance(data, str):
                return [data]
            return [json.dumps(data, separators=(",", ":"))]
        if name == "limit":
            if len(args) < 2:
                raise _JqRuntimeError("limit requires 2 arguments")
            nv = self.run(args[0], data)
            count = int(nv[0]) if nv else 0
            vals = self.run(args[1], data)
            return vals[:count]
        if name == "first":
            if args:
                vals = self.run(args[0], data)
                return vals[:1]
            return [data]
        if name == "last":
            if args:
                vals = self.run(args[0], data)
                return vals[-1:] if vals else []
            return [data]
        if name == "range":
            if not args:
                raise _JqRuntimeError("range requires arguments")
            nv = self.run(args[0], data)
            n_val = int(nv[0]) if nv else 0
            if len(args) == 1:
                return list(range(n_val))
            end_v = self.run(args[1], data)
            end_val = int(end_v[0]) if end_v else 0
            if len(args) >= 3:
                step_v = self.run(args[2], data)
                step_val = int(step_v[0]) if step_v else 1
                return list(range(n_val, end_val, step_val))
            return list(range(n_val, end_val))
        if name == "walk":
            if not args:
                return [data]
            return [self._eval_walk(data, args[0])]
        if name == "getpath":
            if not args:
                raise _JqRuntimeError("getpath requires 1 argument")
            pv = self.run(args[0], data)
            path = pv[0] if pv else []
            return [_getpath(data, path)]
        if name == "setpath":
            if len(args) < 2:
                raise _JqRuntimeError("setpath requires 2 arguments")
            pv = self.run(args[0], data)
            path = pv[0] if pv else []
            vv = self.run(args[1], data)
            val = vv[0] if vv else None
            return [_setpath(data, path, val)]
        if name == "delpaths":
            if not args:
                raise _JqRuntimeError("delpaths requires 1 argument")
            pv = self.run(args[0], data)
            paths = pv[0] if pv else []
            result_dp = data
            for p in sorted(paths, reverse=True):
                result_dp = _delpath(result_dp, p)
            return [result_dp]
        if name == "leaf_paths":
            return [_leaf_paths(data)]
        if name in ("indices", "index"):
            if not args:
                return [None]
            sv = self.run(args[0], data)
            target = sv[0] if sv else None
            if isinstance(data, str) and isinstance(target, str):
                if name == "index":
                    idx = data.find(target)
                    return [idx if idx >= 0 else None]
                idxs: list[int] = []
                start = 0
                while True:
                    idx = data.find(target, start)
                    if idx < 0:
                        break
                    idxs.append(idx)
                    start = idx + 1
                return [idxs]
            if isinstance(data, list):
                if name == "index":
                    for i_val, item in enumerate(data):
                        if item == target:
                            return [i_val]
                    return [None]
                return [[i_val for i_val, item in enumerate(data) if item == target]]
            return [None]
        if name == "rindex":
            if not args:
                return [None]
            sv = self.run(args[0], data)
            target = sv[0] if sv else None
            if isinstance(data, str) and isinstance(target, str):
                idx = data.rfind(target)
                return [idx if idx >= 0 else None]
            if isinstance(data, list):
                for i_val in range(len(data) - 1, -1, -1):
                    if data[i_val] == target:
                        return [i_val]
                return [None]
            return [None]
        if name == "ascii":
            if isinstance(data, str) and len(data) == 1:
                return [ord(data)]
            return [data]
        if name == "implode":
            if isinstance(data, list):
                return ["".join(chr(c) for c in data if isinstance(c, int))]
            return [data]
        if name == "explode":
            if isinstance(data, str):
                return [[ord(c) for c in data]]
            return [data]
        if name == "tojson":
            return [json.dumps(data, separators=(",", ":"))]
        if name == "fromjson":
            if isinstance(data, str):
                return [json.loads(data)]
            return [data]
        if name == "env":
            return [self.env_vars]
        if name == "builtins":
            return [_BUILTIN_NAMES]
        if name == "nan":
            return [float("nan")]
        if name == "infinite":
            return [float("inf")]
        if name == "isinfinite":
            if isinstance(data, float):
                return [math.isinf(data)]
            return [False]
        if name == "isnan":
            if isinstance(data, float):
                return [math.isnan(data)]
            return [False]
        if name == "isnormal":
            if isinstance(data, (int, float)):
                return [
                    not (
                        math.isnan(float(data)) or math.isinf(float(data)) or data == 0
                    )
                ]
            return [False]
        if name == "abs":
            if isinstance(data, (int, float)):
                return [abs(data)]
            return [data]
        if name == "floor":
            if isinstance(data, (int, float)):
                return [math.floor(data)]
            return [data]
        if name == "ceil":
            if isinstance(data, (int, float)):
                return [math.ceil(data)]
            return [data]
        if name == "round":
            if isinstance(data, (int, float)):
                return [round(data)]
            return [data]
        if name == "sqrt":
            if isinstance(data, (int, float)):
                return [math.sqrt(float(data))]
            return [data]
        if name == "fabs":
            if isinstance(data, (int, float)):
                return [math.fabs(float(data))]
            return [data]
        if name == "pow":
            if len(args) >= 2:
                bv = self.run(args[0], data)
                ev = self.run(args[1], data)
                b = float(bv[0]) if bv else 0
                e = float(ev[0]) if ev else 0
                return [math.pow(b, e)]
            return [data]
        if name in ("log", "log2", "log10"):
            if isinstance(data, (int, float)):
                fn = {"log": math.log, "log2": math.log2, "log10": math.log10}[name]
                return [fn(float(data))]
            return [data]
        if name in ("exp", "exp2", "exp10"):
            if isinstance(data, (int, float)):
                if name == "exp":
                    return [math.exp(float(data))]
                if name == "exp2":
                    return [2.0 ** float(data)]
                return [10.0 ** float(data)]
            return [data]
        if name in ("objects", "iterables"):
            if isinstance(data, dict):
                return [data]
            return []
        if name == "arrays":
            if isinstance(data, list):
                return [data]
            return []
        if name == "strings":
            if isinstance(data, str):
                return [data]
            return []
        if name == "numbers":
            if isinstance(data, (int, float)) and not isinstance(data, bool):
                return [data]
            return []
        if name == "booleans":
            if isinstance(data, bool):
                return [data]
            return []
        if name == "nulls":
            if data is None:
                return [data]
            return []
        if name == "scalars":
            if not isinstance(data, (dict, list)):
                return [data]
            return []
        if name == "recurse_down":
            return self._eval_recurse(data)
        if name == "repeat":
            if not args:
                return [data]
            val = data
            results_rep: list[Any] = []
            for _ in range(1000):
                try:
                    vals = self.run(args[0], val)
                except _JqRuntimeError:
                    break
                if not vals:
                    break
                val = vals[0]
                results_rep.append(val)
            return results_rep
        if name == "while":
            if len(args) < 2:
                return [data]
            val = data
            results_wh: list[Any] = []
            for _ in range(10000):
                cond_vals = self.run(args[0], val)
                if not cond_vals or not _is_truthy(cond_vals[0]):
                    break
                results_wh.append(val)
                upd_vals = self.run(args[1], val)
                if not upd_vals:
                    break
                val = upd_vals[0]
            return results_wh
        if name == "until":
            if len(args) < 2:
                return [data]
            val = data
            for _ in range(10000):
                cond_vals = self.run(args[0], val)
                if cond_vals and _is_truthy(cond_vals[0]):
                    break
                upd_vals = self.run(args[1], val)
                if not upd_vals:
                    break
                val = upd_vals[0]
            return [val]
        if name == "debug":
            if self.stderr is not None:
                self.stderr.write(f'["DEBUG:",{json.dumps(data)}]\n')
            return [data]
        if name == "break":
            if args:
                vr = args[0]
                label = vr.name if isinstance(vr, _VarRef) else "$out"
                raise _JqBreak(label)
            raise _JqBreak("$out")
        if name == "nth":
            if not args:
                raise _JqRuntimeError("nth requires arguments")
            nv = self.run(args[0], data)
            n_val = int(nv[0]) if nv else 0
            if len(args) >= 2:
                vals = self.run(args[1], data)
                if 0 <= n_val < len(vals):
                    return [vals[n_val]]
                return [None]
            return [n_val]
        if name == "splits":
            if not isinstance(data, str) or not args:
                return [[]]
            pv = self.run(args[0], data)
            pat = str(pv[0]) if pv else ""
            try:
                return re.split(pat, data)
            except re.error:
                return [[]]
        if name == "transpose":
            if not isinstance(data, list):
                return [data]
            if not data:
                return [[]]
            max_len = max((len(row) if isinstance(row, list) else 1) for row in data)
            result_t: list[list[Any]] = []
            for i_val in range(max_len):
                row: list[Any] = []
                for arr in data:
                    if isinstance(arr, list):
                        row.append(arr[i_val] if i_val < len(arr) else None)
                    else:
                        row.append(arr if i_val == 0 else None)
                result_t.append(row)
            return [result_t]
        if name == "trim":
            if isinstance(data, str):
                return [data.strip()]
            return [data]
        if name == "ltrim":
            if isinstance(data, str):
                return [data.lstrip()]
            return [data]
        if name == "rtrim":
            if isinstance(data, str):
                return [data.rstrip()]
            return [data]
        if name == "object":
            return [{}]

        raise _JqRuntimeError(f"Unknown function: {name}")

    def _eval_regex_replace(
        self, data: Any, args: list[_JqNode], *, global_replace: bool
    ) -> list[Any]:
        if not isinstance(data, str) or len(args) < 2:
            raise _JqRuntimeError("gsub/sub requires string and 2 args")
        pv = self.run(args[0], data)
        rv = self.run(args[1], data)
        pat = str(pv[0]) if pv else ""
        repl = str(rv[0]) if rv else ""
        flags_str = ""
        if len(args) > 2:
            fv = self.run(args[2], data)
            if fv:
                flags_str = str(fv[0])
        re_flags = _jq_re_flags(flags_str)
        try:
            count = 0 if global_replace else 1
            return [re.sub(pat, repl, data, count=count, flags=re_flags)]
        except re.error:
            return [data]

    def _eval_binop(self, node: _BinOp, data: Any) -> list[Any]:
        op = node.op

        if op == "//":
            left = self.run(node.left, data)
            for v in left:
                if v is not None and v is not False:
                    return [v]
            return self.run(node.right, data)

        if op in ("and", "or"):
            left = self.run(node.left, data)
            if op == "and":
                for lv in left:
                    if not _is_truthy(lv):
                        return [False]
                right = self.run(node.right, data)
                for rv in right:
                    return [_is_truthy(rv)]
                return [False]
            # or
            for lv in left:
                if _is_truthy(lv):
                    return [True]
            right = self.run(node.right, data)
            for rv in right:
                return [_is_truthy(rv)]
            return [False]

        left_vals = self.run(node.left, data)
        right_vals = self.run(node.right, data)

        results: list[Any] = []
        for lv in left_vals:
            for rv in right_vals:
                results.append(_apply_binop(op, lv, rv))
        return results

    def _eval_if(self, node: _IfThenElse, data: Any) -> list[Any]:
        cond_vals = self.run(node.cond, data)
        for cv in cond_vals:
            if _is_truthy(cv):
                return self.run(node.then_, data)
        if node.else_ is not None:
            return self.run(node.else_, data)
        return [data]

    def _eval_try(self, node: _TryCatch, data: Any) -> list[Any]:
        try:
            return self.run(node.try_, data)
        except (
            _JqRuntimeError,
            TypeError,
            KeyError,
            IndexError,
            ValueError,
        ):
            if node.catch is not None:
                return self.run(node.catch, data)
            return []

    def _eval_interpolation(self, node: _StringInterpolation, data: Any) -> list[Any]:
        parts: list[str] = []
        for part in node.parts:
            if isinstance(part, str):
                parts.append(part)
            else:
                vals = self.run(part, data)
                for v in vals:
                    if isinstance(v, str):
                        parts.append(v)
                    else:
                        parts.append(json.dumps(v, separators=(",", ":")))
        return ["".join(parts)]

    def _eval_format(self, node: _Format, data: Any) -> list[Any]:  # noqa: C901
        name = node.name
        if name == "@base64":
            if isinstance(data, str):
                return [base64.b64encode(data.encode()).decode()]
            return [base64.b64encode(json.dumps(data).encode()).decode()]
        if name == "@base64d":
            if isinstance(data, str):
                try:
                    return [base64.b64decode(data).decode()]
                except Exception as exc:
                    raise _JqRuntimeError("Invalid base64") from exc
            raise _JqRuntimeError("@base64d requires string")
        if name == "@uri":
            if isinstance(data, str):
                return [urllib.parse.quote(data, safe="")]
            return [urllib.parse.quote(json.dumps(data), safe="")]
        if name == "@csv":
            if isinstance(data, list):
                csv_parts: list[str] = []
                for item in data:
                    if isinstance(item, str):
                        csv_parts.append('"' + item.replace('"', '""') + '"')
                    elif item is None:
                        csv_parts.append("")
                    else:
                        csv_parts.append(json.dumps(item))
                return [",".join(csv_parts)]
            raise _JqRuntimeError("@csv requires array")
        if name == "@tsv":
            if isinstance(data, list):
                tsv_parts: list[str] = []
                for item in data:
                    if item is None:
                        tsv_parts.append("")
                    elif isinstance(item, str):
                        tsv_parts.append(
                            item.replace("\\", "\\\\")
                            .replace("\t", "\\t")
                            .replace("\n", "\\n")
                            .replace("\r", "\\r")
                        )
                    else:
                        tsv_parts.append(json.dumps(item))
                return ["\t".join(tsv_parts)]
            raise _JqRuntimeError("@tsv requires array")
        if name == "@json":
            return [json.dumps(data, separators=(",", ":"))]
        if name in ("@text", "@html"):
            if name == "@html" and isinstance(data, str):
                return [
                    data.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("'", "&#39;")
                    .replace('"', "&quot;")
                ]
            if isinstance(data, str):
                return [data]
            return [json.dumps(data)]

        raise _JqRuntimeError(f"Unknown format: {name}")

    def _eval_keys(self, data: Any, sort: bool) -> list[Any]:
        if isinstance(data, dict):
            k = list(data.keys())
            if sort:
                k = sorted(k)
            return [k]
        if isinstance(data, list):
            return [list(range(len(data)))]
        raise _JqRuntimeError(f"Cannot get keys of {_jq_type(data)}")

    def _eval_object(self, node: _ObjectConstruct, data: Any) -> list[Any]:
        result_obj: dict[str, Any] = {}
        for key_spec, val_node in node.pairs:
            if isinstance(key_spec, str):
                key_str = key_spec
            elif not isinstance(key_spec, str):
                kv = self.run(key_spec, data)
                key_str = str(kv[0]) if kv else ""
            else:
                key_str = str(key_spec)

            if val_node is None:
                result_obj[key_str] = (
                    data.get(key_str) if isinstance(data, dict) else None
                )
            else:
                vv = self.run(val_node, data)
                result_obj[key_str] = vv[0] if vv else None
        return [result_obj]

    def _eval_recurse(self, data: Any) -> list[Any]:
        results: list[Any] = [data]
        queue = [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, dict):
                for v in item.values():
                    results.append(v)
                    queue.append(v)
            elif isinstance(item, list):
                for v in item:
                    results.append(v)
                    queue.append(v)
        return results

    def _eval_walk(self, data: Any, func: _JqNode) -> Any:
        if isinstance(data, dict):
            new_obj = {k: self._eval_walk(v, func) for k, v in data.items()}
            vals = self.run(func, new_obj)
            return vals[0] if vals else new_obj
        if isinstance(data, list):
            new_list = [self._eval_walk(item, func) for item in data]
            vals = self.run(func, new_list)
            return vals[0] if vals else new_list
        vals = self.run(func, data)
        return vals[0] if vals else data

    def _eval_path(self, expr: _JqNode, data: Any) -> list[list[Any]]:
        """Get paths to values that match the expression."""
        return _collect_paths(expr, data, self)

    def _eval_reduce(self, node: _ReduceExpr, data: Any) -> list[Any]:
        items = self.run(node.expr, data)
        acc_vals = self.run(node.init, data)
        acc = acc_vals[0] if acc_vals else None
        saved = dict(self.variables)
        for item in items:
            self.variables[node.var] = item
            upd = self.run(node.update, acc)
            if upd:
                acc = upd[0]
        self.variables = saved
        return [acc]

    def _eval_as(self, node: _AsPattern, data: Any) -> list[Any]:
        vals = self.run(node.expr, data)
        results: list[Any] = []
        saved = dict(self.variables)
        for v in vals:
            self.variables[node.var] = v
            results.extend(self.run(node.body, data))
        self.variables = saved
        return results


# -- helper functions --------------------------------------------------


def _jq_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "number"
    if isinstance(v, float):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    if isinstance(v, dict):
        return "object"
    return "unknown"


def _jq_length(v: Any) -> int | float:
    if v is None:
        return 0
    if isinstance(v, (str, list, dict)):
        return len(v)
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return abs(v)
    return 0


def _is_truthy(v: Any) -> bool:
    return v is not None and v is not False


def _jq_sort_key(v: Any) -> tuple[int, Any]:
    """Return a sort key for jq ordering.

    Order: null < false < true < numbers < strings < arrays < objects.
    """
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1 if not v else 2, 0)
    if isinstance(v, (int, float)):
        return (3, v)
    if isinstance(v, str):
        return (4, v)
    if isinstance(v, list):
        return (5, str(v))
    if isinstance(v, dict):
        return (6, str(v))
    return (7, str(v))


def _apply_binop(op: str, left: Any, right: Any) -> Any:  # noqa: C901
    if op == "+":
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        if isinstance(left, dict) and isinstance(right, dict):
            return {**left, **right}
        if left is None:
            return right
        if right is None:
            return left
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            result = left + right
            return result
        return left
    if op == "-":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left - right
        return left
    if op == "*":
        if isinstance(left, dict) and isinstance(right, dict):
            return {**left, **right}
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left * right
        return left
    if op == "/":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if right == 0:
                raise _JqRuntimeError("Division by zero")
            result = left / right
            if isinstance(left, int) and isinstance(right, int) and left % right == 0:
                return left // right
            return result
        if isinstance(left, str) and isinstance(right, str):
            return left.split(right)
        return left
    if op == "%":
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            if right == 0:
                raise _JqRuntimeError("Modulo by zero")
            return left % right
        return left
    if op == "==":
        return _jq_equal(left, right)
    if op == "!=":
        return not _jq_equal(left, right)
    if op == "<":
        return _jq_sort_key(left) < _jq_sort_key(right)
    if op == ">":
        return _jq_sort_key(left) > _jq_sort_key(right)
    if op == "<=":
        return _jq_sort_key(left) <= _jq_sort_key(right)
    if op == ">=":
        return _jq_sort_key(left) >= _jq_sort_key(right)
    raise _JqRuntimeError(f"Unknown operator: {op}")


def _jq_equal(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


def _flatten(data: list[Any], depth: int) -> list[Any]:
    result: list[Any] = []
    for item in data:
        if isinstance(item, list) and depth > 0:
            result.extend(_flatten(item, depth - 1))
        else:
            result.append(item)
    return result


def _getpath(data: Any, path: Any) -> Any:
    if not isinstance(path, list):
        return None
    current = data
    for seg in path:
        if isinstance(current, dict) and isinstance(seg, str):
            current = current.get(seg)
        elif isinstance(current, list) and isinstance(seg, (int, float)):
            idx = int(seg)
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return None
        else:
            return None
    return current


def _setpath(data: Any, path: Any, value: Any) -> Any:
    import copy as _copy

    if not isinstance(path, list) or not path:
        return value
    data = _copy.deepcopy(data) if data is not None else {}
    current = data
    for i, seg in enumerate(path[:-1]):
        next_seg = path[i + 1]
        if isinstance(current, dict):
            if seg not in current:
                current[seg] = {} if isinstance(next_seg, str) else []
            current = current[seg]
        elif isinstance(current, list) and isinstance(seg, (int, float)):
            idx = int(seg)
            while len(current) <= idx:
                current.append(None)
            if current[idx] is None:
                current[idx] = {} if isinstance(next_seg, str) else []
            current = current[idx]
    last = path[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, list) and isinstance(last, (int, float)):
        idx = int(last)
        while len(current) <= idx:
            current.append(None)
        current[idx] = value
    return data


def _delpath(data: Any, path: Any) -> Any:
    import copy as _copy

    if not isinstance(path, list) or not path:
        return data
    data = _copy.deepcopy(data)
    current = data
    for seg in path[:-1]:
        if isinstance(current, dict):
            current = current.get(seg, {})
        elif isinstance(current, list) and isinstance(seg, (int, float)):
            idx = int(seg)
            if 0 <= idx < len(current):
                current = current[idx]
            else:
                return data
        else:
            return data
    last = path[-1]
    if isinstance(current, dict) and last in current:
        del current[last]
    elif isinstance(current, list) and isinstance(last, (int, float)):
        idx = int(last)
        if 0 <= idx < len(current):
            current.pop(idx)
    return data


def _leaf_paths(data: Any, prefix: list[Any] | None = None) -> list[list[Any]]:
    if prefix is None:
        prefix = []
    if isinstance(data, dict):
        result: list[list[Any]] = []
        for k, v in data.items():
            result.extend(_leaf_paths(v, [*prefix, k]))
        return result
    if isinstance(data, list):
        result = []
        for i, v in enumerate(data):
            result.extend(_leaf_paths(v, [*prefix, i]))
        return result
    return [prefix]


def _collect_paths(
    expr: _JqNode, data: Any, evaluator: _JqEvaluator
) -> list[list[Any]]:
    """Collect paths to values matching expr."""
    if isinstance(expr, _Identity):
        return [[]]
    if isinstance(expr, _Field):
        if isinstance(data, dict) and expr.name in data:
            return [[expr.name]]
        return []
    if isinstance(expr, _Pipe):
        left_paths = _collect_paths(expr.left, data, evaluator)
        result: list[list[Any]] = []
        for lp in left_paths:
            inner = _getpath(data, lp)
            right_paths = _collect_paths(expr.right, inner, evaluator)
            for rp in right_paths:
                result.append(lp + rp)
        return result
    if isinstance(expr, _Iterate):
        if isinstance(data, list):
            return [[i] for i in range(len(data))]
        if isinstance(data, dict):
            return [[k] for k in data]
        return []
    if isinstance(expr, _Index):
        idx_vals = evaluator.run(expr.index, data)
        result = []
        for idx in idx_vals:
            if isinstance(data, list) and isinstance(idx, (int, float)):
                result.append([int(idx)])
            elif isinstance(data, dict) and isinstance(idx, str):
                result.append([idx])
        return result
    # Fallback
    return []


def _jq_re_flags(flags_str: str) -> int:
    flags = 0
    if "x" in flags_str:
        flags |= re.VERBOSE
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "m" in flags_str:
        flags |= re.MULTILINE
    if "s" in flags_str:
        flags |= re.DOTALL
    return flags


def _jq_contains(a: Any, b: Any) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return b in a
    if isinstance(a, list) and isinstance(b, list):
        return all(any(_jq_contains(ai, bi) for ai in a) for bi in b)
    if isinstance(a, dict) and isinstance(b, dict):
        return all(k in a and _jq_contains(a[k], b[k]) for k in b)
    return _jq_equal(a, b)


_BUILTIN_NAMES: list[str] = [
    "length",
    "keys",
    "values",
    "type",
    "empty",
    "error",
    "map",
    "select",
    "sort",
    "sort_by",
    "group_by",
    "unique",
    "unique_by",
    "flatten",
    "add",
    "any",
    "all",
    "min",
    "max",
    "to_entries",
    "from_entries",
    "with_entries",
    "has",
    "in",
    "contains",
    "inside",
    "split",
    "join",
    "test",
    "match",
    "gsub",
    "sub",
    "ascii_downcase",
    "ascii_upcase",
    "ltrimstr",
    "rtrimstr",
    "startswith",
    "endswith",
    "tonumber",
    "tostring",
    "not",
    "recurse",
    "env",
    "range",
    "limit",
    "first",
    "last",
    "keys_unsorted",
    "reverse",
    "walk",
    "getpath",
    "setpath",
    "delpaths",
    "path",
    "leaf_paths",
    "debug",
    "input",
    "inputs",
    "builtins",
]


# -- jq command entry point -------------------------------------------


@command("jq")
def cmd_jq(  # noqa: C901
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    raw_output = False
    compact = False
    exit_status = False
    slurp = False
    null_input = False
    jq_vars: dict[str, Any] = {}
    filter_expr: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-r", "--raw-output"):
            raw_output = True
        elif a in ("-c", "--compact-output"):
            compact = True
        elif a in ("-e", "--exit-status"):
            exit_status = True
        elif a in ("-s", "--slurp"):
            slurp = True
        elif a in ("-n", "--null-input"):
            null_input = True
        elif a == "--arg" and i + 2 < len(args):
            jq_vars["$" + args[i + 1]] = args[i + 2]
            i += 2
        elif a == "--argjson" and i + 2 < len(args):
            try:
                jq_vars["$" + args[i + 1]] = json.loads(args[i + 2])
            except json.JSONDecodeError:
                io.stderr.write(f"jq: invalid JSON for --argjson: {args[i + 2]}\n")
                return CommandResult(exit_code=2)
            i += 2
        elif a == "--":
            files.extend(args[i + 1 :])
            break
        elif filter_expr is None and not a.startswith("-"):
            filter_expr = a
        elif filter_expr is not None:
            files.append(a)
        else:
            io.stderr.write(f"jq: unknown option: {a}\n")
            return CommandResult(exit_code=2)
        i += 1

    if filter_expr is None:
        filter_expr = "."

    # Parse the filter
    try:
        tokens = _jq_tokenize(filter_expr)
        parser = _JqParser(tokens)
        ast = parser.parse()
    except (_JqLexError, _JqParseError) as exc:
        io.stderr.write(f"jq: parse error: {exc}\n")
        return CommandResult(exit_code=3)

    # Read input
    if null_input:
        inputs: list[Any] = [None]
    else:
        text, read_exit = read_text_inputs(files, state, vfs, io, "jq")
        if read_exit != 0:
            return CommandResult(exit_code=read_exit)
        # Parse JSON inputs (handle multiple JSON values in one stream)
        inputs_or_none = _parse_json_inputs(text)
        if inputs_or_none is None:
            io.stderr.write("jq: invalid JSON input\n")
            return CommandResult(exit_code=2)
        inputs = inputs_or_none

    if slurp:
        inputs = [inputs]

    # Build env vars from shell state
    env_vars: dict[str, str] = {}
    for k, v in state.variables.items():
        env_vars[k] = v

    # Evaluate
    evaluator = _JqEvaluator(
        variables=jq_vars,
        env_vars=env_vars,
        all_inputs=inputs[1:] if len(inputs) > 1 else [],
        stderr=io.stderr,
    )

    all_outputs: list[Any] = []
    for inp in inputs:
        try:
            results = evaluator.run(ast, inp)
            all_outputs.extend(results)
        except _JqRuntimeError as exc:
            io.stderr.write(f"jq: error: {exc}\n")
            return CommandResult(exit_code=5)
        except _JqBreak:
            pass

    # Output
    has_null_or_false = False
    for val in all_outputs:
        if val is None or val is False:
            has_null_or_false = True
        output_str = _jq_format_output(val, raw_output=raw_output, compact=compact)
        io.stdout.write(output_str + "\n")

    if exit_status and has_null_or_false:
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


def _parse_json_inputs(text: str) -> list[Any] | None:
    """Parse one or more JSON values from a text stream."""
    text = text.strip()
    if not text:
        return [None]

    results: list[Any] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        # Skip whitespace
        while idx < len(text) and text[idx] in " \t\n\r":
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
            results.append(obj)
            idx = end
        except json.JSONDecodeError:
            return None
    return results if results else [None]


def _jq_format_output(val: Any, *, raw_output: bool, compact: bool) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, str):
        if raw_output:
            return val
        return json.dumps(val)
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val.is_integer() and abs(val) < 1e18:
            return str(int(val))
        return json.dumps(val)
    if compact:
        return json.dumps(val, separators=(",", ":"), ensure_ascii=False)
    return json.dumps(val, indent=2, ensure_ascii=False)


# =====================================================================
# patch -- Apply unified diffs to VFS files
# =====================================================================


@command("patch")
def cmd_patch(  # noqa: C901
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    strip = 0
    input_file: str | None = None
    reverse = False
    forward = False
    dry_run = False
    silent = False
    positional: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("-p") and len(a) > 2:
            try:
                strip = int(a[2:])
            except ValueError:
                io.stderr.write(f"patch: invalid strip count: {a[2:]}\n")
                return CommandResult(exit_code=2)
        elif a == "-p" and i + 1 < len(args):
            i += 1
            try:
                strip = int(args[i])
            except ValueError:
                io.stderr.write(f"patch: invalid strip count: {args[i]}\n")
                return CommandResult(exit_code=2)
        elif a.startswith("--strip="):
            try:
                strip = int(a.split("=", 1)[1])
            except ValueError:
                io.stderr.write("patch: invalid strip count\n")
                return CommandResult(exit_code=2)
        elif a in ("-i", "--input") and i + 1 < len(args):
            i += 1
            input_file = args[i]
        elif a.startswith("--input="):
            input_file = a.split("=", 1)[1]
        elif a in ("-R", "--reverse"):
            reverse = True
        elif a in ("-N", "--forward"):
            forward = True
        elif a == "--dry-run":
            dry_run = True
        elif a in ("-s", "--silent", "--quiet"):
            silent = True
        elif not a.startswith("-"):
            positional.append(a)
        else:
            io.stderr.write(f"patch: unknown option: {a}\n")
            return CommandResult(exit_code=2)
        i += 1

    # Read patch content
    if input_file is not None:
        patch_text = read_text(input_file, state, vfs, io, "patch")
        if patch_text is None:
            return CommandResult(exit_code=2)
    elif len(positional) >= 2:
        patch_text = read_text(positional[1], state, vfs, io, "patch")
        if patch_text is None:
            return CommandResult(exit_code=2)
    else:
        patch_text = io.stdin.read()

    if not patch_text:
        io.stderr.write("patch: no patch input\n")
        return CommandResult(exit_code=1)

    # Parse the unified diff
    hunks_by_file = _parse_unified_diff(patch_text, strip)

    if not hunks_by_file:
        io.stderr.write("patch: no valid patches found\n")
        return CommandResult(exit_code=1)

    exit_code = 0

    for filename, hunks in hunks_by_file.items():
        # Determine the actual file to patch
        target_file = positional[0] if positional else filename

        abs_path = vfs.resolve(target_file, state.cwd)

        # Read existing file content
        try:
            content = vfs.read(abs_path).decode("utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
        except FileNotFoundError:
            # File doesn't exist yet -- start empty
            lines = []

        # Apply hunks
        success = True
        for hunk in hunks:
            result = _apply_hunk(lines, hunk, reverse=reverse, forward=forward)
            if result is None:
                io.stderr.write(f"patch: FAILED to apply hunk for {target_file}\n")
                success = False
                exit_code = 1
            else:
                lines = result

        if success:
            if not silent:
                io.stdout.write(f"patching file {target_file}\n")
            if not dry_run:
                vfs.write(abs_path, "".join(lines).encode("utf-8"))
        else:
            exit_code = 1

    return CommandResult(exit_code=exit_code)


class _PatchHunk:
    def __init__(
        self,
        old_start: int,
        old_count: int,
        new_start: int,
        new_count: int,
        lines: list[tuple[str, str]],
    ) -> None:
        self.old_start = old_start
        self.old_count = old_count
        self.new_start = new_start
        self.new_count = new_count
        # lines is list of (type, text) where type is ' ', '+', '-'
        self.lines = lines


def _parse_unified_diff(  # noqa: C901
    text: str, strip: int
) -> dict[str, list[_PatchHunk]]:
    """Parse a unified diff into hunks grouped by filename."""
    result: dict[str, list[_PatchHunk]] = {}
    lines = text.splitlines(keepends=True)
    i = 0
    current_file: str | None = None

    while i < len(lines):
        line = lines[i]

        # Detect file header: --- a/path followed by +++ b/path
        if (
            line.startswith("--- ")
            and i + 1 < len(lines)
            and lines[i + 1].startswith("+++ ")
        ):
            minus_path = line[4:].strip()
            plus_path = lines[i + 1][4:].strip()

            # Remove timestamp if present
            for sep in ("\t", "  "):
                if sep in minus_path:
                    minus_path = minus_path.split(sep)[0]
                if sep in plus_path:
                    plus_path = plus_path.split(sep)[0]

            # Use the +++ path (new file) for patching
            target = plus_path
            if target == "/dev/null":
                target = minus_path

            # Apply strip
            target = _strip_path(target, strip)

            current_file = target
            if current_file not in result:
                result[current_file] = []
            i += 2
            continue

        # Detect hunk header: @@ -start,count +start,count @@
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m and current_file is not None:
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) is not None else 1

            hunk_lines: list[tuple[str, str]] = []
            i += 1

            while i < len(lines):
                hline = lines[i]
                if hline.startswith("--- ") or hline.startswith("+++ "):
                    break
                if hline.startswith("@@ "):
                    break
                if hline.startswith("diff "):
                    break
                if hline.startswith("\\"):
                    # "\ No newline at end of file"
                    i += 1
                    continue
                if hline.startswith("+"):
                    hunk_lines.append(("+", hline[1:]))
                elif hline.startswith("-"):
                    hunk_lines.append(("-", hline[1:]))
                elif hline.startswith(" "):
                    hunk_lines.append((" ", hline[1:]))
                else:
                    # Context line without leading space (some diffs)
                    hunk_lines.append((" ", hline))
                i += 1

            result[current_file].append(
                _PatchHunk(old_start, old_count, new_start, new_count, hunk_lines)
            )
            continue

        i += 1

    return result


def _strip_path(path: str, strip: int) -> str:
    """Strip leading path components."""
    if strip <= 0:
        return path
    parts = path.split("/")
    if len(parts) > strip:
        return "/".join(parts[strip:])
    return parts[-1] if parts else path


def _apply_hunk(
    lines: list[str],
    hunk: _PatchHunk,
    *,
    reverse: bool = False,
    forward: bool = False,
    fuzz: int = 3,
) -> list[str] | None:
    """Apply a single hunk to the file lines.

    Returns the modified lines, or None if the hunk fails to apply.
    """
    hunk_lines = hunk.lines
    if reverse:
        # Swap + and -
        new_hunk_lines: list[tuple[str, str]] = []
        for ltype, ltext in hunk_lines:
            if ltype == "+":
                new_hunk_lines.append(("-", ltext))
            elif ltype == "-":
                new_hunk_lines.append(("+", ltext))
            else:
                new_hunk_lines.append((ltype, ltext))
        hunk_lines = new_hunk_lines

    # Build the expected old lines (context + removed) for matching
    old_lines: list[str] = []
    for ltype, ltext in hunk_lines:
        if ltype in (" ", "-"):
            old_lines.append(ltext)

    # Try to find the location in the file
    # 1-based line number from hunk header
    target_line = hunk.old_start - 1 if not reverse else hunk.new_start - 1
    target_line = max(target_line, 0)

    # Try exact match first, then with fuzz
    match_offset = _find_hunk_match(lines, old_lines, target_line, fuzz)
    if match_offset is None:
        return None

    # Check if already applied (forward mode)
    if forward:
        new_lines: list[str] = []
        for ltype, ltext in hunk_lines:
            if ltype in (" ", "+"):
                new_lines.append(ltext)
        if _find_hunk_match(lines, new_lines, target_line, fuzz) is not None:
            return lines  # Already applied

    # Apply the hunk
    result = list(lines[:match_offset])
    for ltype, ltext in hunk_lines:
        if ltype in (" ", "+"):
            result.append(ltext)
    result.extend(lines[match_offset + len(old_lines) :])
    return result


def _find_hunk_match(
    file_lines: list[str],
    expected_lines: list[str],
    target: int,
    fuzz: int,
) -> int | None:
    """Find where expected_lines match in file_lines, starting near target."""
    if not expected_lines:
        # Empty hunk -- insert at target position
        return min(target, len(file_lines))

    # Try exact position first
    if _lines_match(file_lines, expected_lines, target):
        return target

    # Try with fuzz
    for offset in range(1, fuzz + 1):
        for delta in (offset, -offset):
            pos = target + delta
            if 0 <= pos <= len(file_lines) - len(expected_lines) and _lines_match(
                file_lines, expected_lines, pos
            ):
                return pos

    # Try wider search
    for pos in range(max(0, target - 20), min(len(file_lines), target + 20)):
        if _lines_match(file_lines, expected_lines, pos):
            return pos

    return None


def _lines_match(file_lines: list[str], expected: list[str], start: int) -> bool:
    """Check if expected lines match file_lines starting at start."""
    if start < 0 or start + len(expected) > len(file_lines):
        return False
    for i, exp in enumerate(expected):
        actual = file_lines[start + i]
        # Compare stripped of trailing newline for flexibility
        if actual.rstrip("\n\r") != exp.rstrip("\n\r"):
            return False
    return True


# ── yq ────────────────────────────────────────────────────────────────────


@command("yq")
def cmd_yq(  # noqa: C901
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    """YAML/TOML/JSON processor using jq filter syntax."""
    raw_output = False
    compact = False
    exit_status = False
    slurp = False
    null_input = False
    output_format = "yaml"  # yaml, json, toml, props
    input_format = "auto"  # auto, yaml, json, toml
    in_place = False
    jq_vars: dict[str, Any] = {}
    filter_expr: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-r", "--raw-output"):
            raw_output = True
        elif a in ("-c", "--compact-output"):
            compact = True
        elif a in ("-e", "--exit-status"):
            exit_status = True
        elif a in ("-s", "--slurp"):
            slurp = True
        elif a in ("-n", "--null-input"):
            null_input = True
        elif a in ("-i", "--in-place"):
            in_place = True
        elif a in ("-o", "--output-format") and i + 1 < len(args):
            i += 1
            output_format = args[i]
        elif a in ("-p", "--input-format") and i + 1 < len(args):
            i += 1
            input_format = args[i]
        elif a in ("-oj", "--tojson"):
            output_format = "json"
        elif a in ("-oy", "--toyaml"):
            output_format = "yaml"
        elif a == "--arg" and i + 2 < len(args):
            jq_vars["$" + args[i + 1]] = args[i + 2]
            i += 2
        elif a == "--argjson" and i + 2 < len(args):
            try:
                jq_vars["$" + args[i + 1]] = json.loads(args[i + 2])
            except json.JSONDecodeError:
                io.stderr.write(f"yq: invalid JSON for --argjson: {args[i + 2]}\n")
                return CommandResult(exit_code=2)
            i += 2
        elif a == "--":
            files.extend(args[i + 1 :])
            break
        elif filter_expr is None and not a.startswith("-"):
            filter_expr = a
        elif filter_expr is not None:
            files.append(a)
        else:
            io.stderr.write(f"yq: unknown option: {a}\n")
            return CommandResult(exit_code=2)
        i += 1

    if filter_expr is None:
        filter_expr = "."

    # Parse the jq filter
    try:
        tokens = _jq_tokenize(filter_expr)
        parser = _JqParser(tokens)
        ast = parser.parse()
    except (_JqLexError, _JqParseError) as exc:
        io.stderr.write(f"yq: parse error: {exc}\n")
        return CommandResult(exit_code=3)

    # Read input
    if null_input:
        inputs: list[Any] = [None]
    else:
        text, read_exit = read_text_inputs(files, state, vfs, io, "yq")
        if read_exit != 0:
            return CommandResult(exit_code=read_exit)
        fmt = _yq_detect_format(text, input_format, files)
        inputs_or_none = _yq_parse_inputs(text, fmt, io)
        if inputs_or_none is None:
            return CommandResult(exit_code=2)
        inputs = inputs_or_none

    if slurp:
        inputs = [inputs]

    # Build env vars
    env_vars: dict[str, str] = {}
    for k, v in state.variables.items():
        env_vars[k] = v

    # Evaluate
    evaluator = _JqEvaluator(
        variables=jq_vars,
        env_vars=env_vars,
        all_inputs=inputs[1:] if len(inputs) > 1 else [],
        stderr=io.stderr,
    )

    all_outputs: list[Any] = []
    for inp in inputs:
        try:
            results = evaluator.run(ast, inp)
            all_outputs.extend(results)
        except _JqRuntimeError as exc:
            io.stderr.write(f"yq: error: {exc}\n")
            return CommandResult(exit_code=5)
        except _JqBreak:
            pass

    # Output
    has_null_or_false = False
    output_text = ""
    for val in all_outputs:
        if val is None or val is False:
            has_null_or_false = True
        output_text += _yq_format_output(
            val, output_format, raw_output=raw_output, compact=compact
        )

    if in_place and files:
        for f in files:
            abs_path = vfs.resolve(f, state.cwd)
            vfs.write(abs_path, output_text.encode("utf-8"), append=False)
    else:
        io.stdout.write(output_text)

    if exit_status and has_null_or_false:
        return CommandResult(exit_code=1)
    return CommandResult(exit_code=0)


def _yq_detect_format(text: str, explicit: str, files: list[str]) -> str:
    """Detect the input format from explicit flag, file extension, or content."""
    if explicit != "auto":
        return explicit
    # Check file extension
    for f in files:
        lower = f.lower()
        if lower.endswith((".yaml", ".yml")):
            return "yaml"
        if lower.endswith(".json"):
            return "json"
        if lower.endswith(".toml"):
            return "toml"
    # Sniff content
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return "json"
    if stripped.startswith("---") or ": " in stripped.split("\n", 1)[0]:
        return "yaml"
    if "=" in stripped.split("\n", 1)[0] and not stripped.startswith("#!"):
        return "toml"
    return "yaml"


def _yq_parse_inputs(text: str, fmt: str, io: IOContext) -> list[Any] | None:
    """Parse input text as YAML, JSON, or TOML."""
    text = text.strip()
    if not text:
        return [None]

    if fmt == "json":
        return _parse_json_inputs(text)

    if fmt == "toml":
        try:
            return [tomllib.loads(text)]
        except Exception as exc:
            io.stderr.write(f"yq: TOML parse error: {exc}\n")
            return None

    # YAML — may contain multiple documents separated by ---
    try:
        docs = list(yaml.safe_load_all(text))
        return docs if docs else [None]
    except yaml.YAMLError as exc:
        io.stderr.write(f"yq: YAML parse error: {exc}\n")
        return None


def _yq_format_output(
    val: Any,
    fmt: str,
    *,
    raw_output: bool = False,
    compact: bool = False,
) -> str:
    """Format a value for output in the requested format."""
    if fmt == "json":
        return _jq_format_output(val, raw_output=raw_output, compact=compact) + "\n"

    if fmt in ("props", "properties"):
        # Java-style key=value for flat objects
        if isinstance(val, dict):
            lines = [f"{k} = {v}" for k, v in val.items()]
            return "\n".join(lines) + "\n"
        return str(val) + "\n"

    # YAML output (default)
    if raw_output and isinstance(val, str):
        return val + "\n"
    if val is None:
        return "null\n"
    try:
        result = yaml.dump(
            val,
            default_flow_style=compact,
            allow_unicode=True,
            sort_keys=False,
        )
        # Strip YAML document end marker for simple scalars
        if result.endswith("\n...\n"):
            result = result[: -len("...\n")]
        return result
    except yaml.YAMLError:
        return str(val) + "\n"
