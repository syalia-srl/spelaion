"""Parser frontend using tree-sitter and tree-sitter-bash."""

from __future__ import annotations

from dataclasses import dataclass, field

import tree_sitter_bash as tsbash
from tree_sitter import Language, Node, Parser

from agentsh.ast.spans import Point, Span
from agentsh.parser.diagnostics import Diagnostic, DiagnosticSeverity

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
        text = source[span.start_byte : span.end_byte]
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
    source_bytes = text.encode("utf-8")
    tree = _PARSER.parse(source_bytes)
    root = tree.root_node
    diagnostics = _collect_errors(root, text)
    has_errors = len(diagnostics) > 0 or root.has_error

    return ParseResult(
        tree=tree,
        source=text,
        diagnostics=diagnostics,
        has_errors=has_errors,
    )


def span_from_node(node: Node) -> Span:
    """Public helper to create a Span from a tree-sitter node."""
    return _span_from_node(node)
