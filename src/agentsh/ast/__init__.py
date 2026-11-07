"""agentsh.ast — Abstract-syntax-tree definitions for the virtual Bash parser.

Public API re-exports:
    Span model:   Point, Span
    Word model:   WordSegment union and its members
    AST nodes:    All concrete node types plus the ASTNode protocol
"""

from agentsh.ast.nodes import (
    AndOrList,
    ArrayAssignmentWord,
    AssignmentWord,
    ASTNode,
    CaseClause,
    CaseItem,
    CStyleForLoop,
    ExtendedTest,
    ForLoop,
    FunctionDef,
    Group,
    IfClause,
    Pipeline,
    Program,
    Redirection,
    Sequence,
    SimpleCommand,
    Subshell,
    UntilLoop,
    WhileLoop,
    Word,
)
from agentsh.ast.spans import Point, Span
from agentsh.ast.words import (
    ArithmeticExpansionSegment,
    CommandSubstitutionSegment,
    DoubleQuotedSegment,
    GlobSegment,
    LiteralSegment,
    ParameterExpansionSegment,
    ProcessSubstitutionSegment,
    SingleQuotedSegment,
    WordSegment,
)

__all__ = [
    "ASTNode",
    "AndOrList",
    "ArithmeticExpansionSegment",
    "ArrayAssignmentWord",
    "AssignmentWord",
    "CStyleForLoop",
    "CaseClause",
    "CaseItem",
    "CommandSubstitutionSegment",
    "DoubleQuotedSegment",
    "ExtendedTest",
    "ForLoop",
    "FunctionDef",
    "GlobSegment",
    "Group",
    "IfClause",
    "LiteralSegment",
    "ParameterExpansionSegment",
    "Pipeline",
    "Point",
    "ProcessSubstitutionSegment",
    "Program",
    "Redirection",
    "Sequence",
    "SimpleCommand",
    "SingleQuotedSegment",
    "Span",
    "Subshell",
    "UntilLoop",
    "WhileLoop",
    "Word",
    "WordSegment",
]
