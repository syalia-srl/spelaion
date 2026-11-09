"""Parser frontend using tree-sitter and tree-sitter-bash."""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_bash as tsbash
from tree_sitter import Language, Node, Parser

from spelaion.ast.spans import Point, Span
from spelaion.parser.diagnostics import Diagnostic, DiagnosticSeverity

_LANGUAGE = Language(tsbash.language())
_PARSER = Parser(_LANGUAGE)


@dataclass
class ParseResult:
    """Result of parsing a shell script."""

    tree: object  # tree_sitter.Tree
    source: str
    diagnostics: list[Diagnostic] = field(default_factory=lambda: [])
    has_errors: bool = False

    @property
    def root_node(self) -> Node:
        """Access the root CST node."""
        return self.tree.root_node  # type: ignore[attr-defined]


def _span_from_node(node: Node) -> Span:
    """Extract a Span from a tree-sitter Node."""
    return Span(
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_point=Point(row=node.start_point[0], column=node.start_point[1]),
        end_point=Point(row=node.end_point[0], column=node.end_point[1]),
    )


def _collect_errors(node: Node, source: str) -> list[Diagnostic]:
    """Walk the CST and collect ERROR and MISSING nodes as diagnostics."""
    diagnostics: list[Diagnostic] = []
    _walk_errors(node, source, diagnostics)
    return diagnostics


def _walk_errors(node: Node, source: str, diagnostics: list[Diagnostic]) -> None:
    if node.type == "ERROR":
        span = _span_from_node(node)
        text = source.encode("utf-8")[span.start_byte : span.end_byte].decode(
            "utf-8", errors="replace"
        )
        msg = f"Syntax error near: {text!r}" if text else "Syntax error"
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                message=msg,
                span=span,
            )
        )
    elif node.is_missing:
        span = _span_from_node(node)
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                message=f"Missing expected: {node.type}",
                span=span,
            )
        )
    for child in node.children:
        _walk_errors(child, source, diagnostics)


def parse_script(text: str) -> ParseResult:
    """Parse a shell script string and return a ParseResult.

    The result contains the tree-sitter CST, the source text,
    and any diagnostics (syntax errors).
    """
    tree = _PARSER.parse(_mask_heredoc_bodies(text.encode("utf-8")))
    root = tree.root_node
    diagnostics = _collect_errors(root, text)
    has_errors = len(diagnostics) > 0 or root.has_error

    return ParseResult(
        tree=tree,
        source=text,
        diagnostics=diagnostics,
        has_errors=has_errors,
    )


def _heredocs(node: Node) -> list[Node]:
    """Every ``heredoc_redirect`` under *node*, in source order."""
    found: list[Node] = []
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "heredoc_redirect":
            found.append(n)
        stack.extend(reversed(n.children))
    return sorted(found, key=lambda n: n.start_byte)


def _mask_heredoc_bodies(source: bytes) -> bytes:
    """*source* with each here-document body overwritten, byte for byte.

    tree-sitter-bash ends a body at a line that only starts with the
    delimiter, or has blanks before it (`` EOF``, ``EOFX``), and parses the
    rest as commands. Here a body ends, as in bash, at the first line that
    is exactly the delimiter, or tabs and the delimiter for ``<<-``; its
    bytes become a filler that cannot end it. Offsets do not move, so the
    normaliser reads the real body from the original text.
    """
    done = -1
    # Where the next body on a line starts, when that line has several.
    after: dict[int, int] = {}
    while True:
        tree = _PARSER.parse(source)
        pending = [h for h in _heredocs(tree.root_node) if h.start_byte > done]
        start = (
            next((c for c in pending[0].children if c.type == "heredoc_start"), None)
            if pending
            else None
        )
        if start is None:
            return source
        h = pending[0]
        done = h.start_byte
        dash = any(source[c.start_byte : c.end_byte] == b"<<-" for c in h.children)
        delimiter = source[start.start_byte : start.end_byte]
        for q in (b"'", b'"', b"\\"):
            delimiter = delimiter.replace(q, b"")
        line_end = source.find(b"\n", start.end_byte)
        if line_end < 0:
            return source
        begin = after.get(line_end, line_end + 1)
        pos = begin
        while pos < len(source):
            nl = source.find(b"\n", pos)
            end = len(source) if nl < 0 else nl
            line = source[pos:end]
            if line == delimiter or (dash and line.lstrip(b"\t") == delimiter):
                break
            pos = end + 1
        body_end = min(pos, len(source))
        after[line_end] = min(
            source.find(b"\n", body_end) + 1 or len(source), len(source)
        )
        fill = next(b for b in b"xyz" if b not in delimiter)
        body = bytes(b if b == 10 else fill for b in source[begin:body_end])
        source = source[:begin] + body + source[body_end:]


def span_from_node(node: Node) -> Span:
    """Public helper to create a Span from a tree-sitter node."""
    return _span_from_node(node)
