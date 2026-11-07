"""LangChain tool: parse a shell script and return AST as JSON."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    pass


class AgentShParseTool(BaseTool):
    """Parse a shell script and return the AST structure."""

    name: str = "agentsh_parse"
    description: str = (
        "Parse a shell script and return its abstract syntax tree (AST). "
        "Useful for understanding what a shell script does before running it."
    )
    engine: Any = None  # ShellEngine

    def _run(self, script: str) -> str:
        """Parse the script and return AST as JSON."""
        result = self.engine.parse(script)

        output: dict[str, Any] = {
            "has_errors": result.has_errors,
            "diagnostics": [str(d) for d in result.diagnostics],
        }

        if result.ast is not None:
            output["ast"] = ast_to_dict(result.ast)

        return json.dumps(output, indent=2)


def _assignment_to_dict(a: Any) -> dict[str, Any]:
    """Convert an assignment node to a dict."""
    from agentsh.ast.nodes import ArrayAssignmentWord

    if isinstance(a, ArrayAssignmentWord):
        return {
            "type": "array_assignment",
            "name": a.name,
            "values": [_word_to_dict(v) for v in a.values],
        }
    return {"name": a.name, "value": _word_to_dict(a.value) if a.value else None}


def ast_to_dict(node: Any) -> dict[str, Any]:
    """Convert an AST node to a JSON-serializable dict."""
    from agentsh.ast.nodes import (
        AndOrList,
        FunctionDef,
        Group,
        Pipeline,
        Program,
        Sequence,
        SimpleCommand,
        Subshell,
    )

    if isinstance(node, Program):
        return {
            "type": "Program",
            "body": [ast_to_dict(n) for n in node.body],
        }
    if isinstance(node, Sequence):
        return {
            "type": "Sequence",
            "commands": [ast_to_dict(n) for n in node.commands],
        }
    if isinstance(node, AndOrList):
        return {
            "type": "AndOrList",
            "operators": list(node.operators),
            "commands": [ast_to_dict(n) for n in node.commands],
        }
    if isinstance(node, Pipeline):
        return {
            "type": "Pipeline",
            "negated": node.negated,
            "commands": [ast_to_dict(n) for n in node.commands],
        }
    if isinstance(node, SimpleCommand):
        return {
            "type": "SimpleCommand",
            "words": [_word_to_dict(w) for w in node.words],
            "assignments": [_assignment_to_dict(a) for a in node.assignments],
        }
    if isinstance(node, Group):
        return {"type": "Group", "body": ast_to_dict(node.body)}
    if isinstance(node, Subshell):
        return {"type": "Subshell", "body": ast_to_dict(node.body)}
    if isinstance(node, FunctionDef):
        return {
            "type": "FunctionDef",
            "name": node.name,
            "body": ast_to_dict(node.body),
        }

    return {"type": type(node).__name__}


def _word_to_dict(word: Any) -> dict[str, Any]:
    """Convert a Word to a dict."""
    from agentsh.ast.words import (
        CommandSubstitutionSegment,
        DoubleQuotedSegment,
        GlobSegment,
        LiteralSegment,
        ParameterExpansionSegment,
        SingleQuotedSegment,
    )

    segments: list[dict[str, Any]] = []
    for seg in word.segments:
        if isinstance(seg, LiteralSegment):
            segments.append({"type": "literal", "value": seg.value})
        elif isinstance(seg, SingleQuotedSegment):
            segments.append({"type": "single_quoted", "value": seg.value})
        elif isinstance(seg, ParameterExpansionSegment):
            segments.append({"type": "param_expansion", "name": seg.name})
        elif isinstance(seg, CommandSubstitutionSegment):
            segments.append({"type": "command_sub", "command": seg.command})
        elif isinstance(seg, GlobSegment):
            segments.append({"type": "glob", "pattern": seg.pattern})
        elif isinstance(seg, DoubleQuotedSegment):
            inner: list[dict[str, str]] = [
                {
                    "type": type(s).__name__,
                    "value": str(getattr(s, "value", getattr(s, "name", ""))),
                }
                for s in seg.segments
            ]
            segments.append(
                {"type": "double_quoted", "segments": inner}  # type: ignore[dict-item]
            )
        else:
            segments.append({"type": type(seg).__name__})

    return {"segments": segments}
