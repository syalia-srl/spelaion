"""AST node definitions for the virtual Bash parser.

Every node is a frozen dataclass with ``__slots__`` and carries a ``span``
attribute that records the exact source location from which the node was
parsed.  Nodes form an immutable tree; transformations produce new trees
rather than mutating in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agentsh.ast.spans import Span
from agentsh.ast.words import WordSegment

# ---------------------------------------------------------------------------
# Base protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ASTNode(Protocol):
    """Structural protocol satisfied by every AST node.

    Using a ``Protocol`` instead of a base class keeps the dataclass
    hierarchy flat and avoids MRO complications with frozen/slotted
    dataclasses.
    """

    @property
    def span(self) -> Span: ...


# ---------------------------------------------------------------------------
# Leaf / helper nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Word:
    """A parsed Bash word, broken into its constituent segments.

    After expansion each segment is evaluated left-to-right and the
    results are concatenated to form the final string value.
    """

    segments: tuple[WordSegment, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class AssignmentWord:
    """A variable assignment in command prefix position.

    ``name=value`` where *value* may be ``None`` for bare assignments
    like ``x=`` (which assigns the empty string).
    """

    name: str
    value: Word | None
    span: Span


@dataclass(frozen=True, slots=True)
class ArrayAssignmentWord:
    """An array assignment: ``name=(value1 value2 ...)``."""

    name: str
    values: tuple[Word, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Redirection:
    """An I/O redirection attached to a command.

    *op* is the redirection operator (``>``, ``>>``, ``<``, ``<<``,
    ``<<<``, ``>&``, ``<&``, ``<>``).  *fd* is the optional explicit
    file-descriptor number (``None`` means the default for the operator,
    i.e. 1 for output and 0 for input).  *target* is the filename or
    here-document word.
    """

    op: str
    fd: int | None
    target: Word
    span: Span


# ---------------------------------------------------------------------------
# Command nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SimpleCommand:
    """A simple (non-compound) command.

    Consists of optional variable assignments, the command word followed
    by argument words, and optional I/O redirections.
    """

    words: tuple[Word, ...]
    assignments: tuple[AssignmentWord | ArrayAssignmentWord, ...]
    redirections: tuple[Redirection, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Pipeline:
    """A pipeline of one or more commands connected by ``|``.

    When *negated* is ``True`` the pipeline was prefixed with ``!``
    and its exit status is logically inverted.
    """

    commands: tuple[ASTNode, ...]
    negated: bool
    span: Span


@dataclass(frozen=True, slots=True)
class AndOrList:
    """A chain of commands joined by ``&&`` and/or ``||`` operators.

    *operators* has length ``len(commands) - 1``; ``operators[i]``
    sits between ``commands[i]`` and ``commands[i+1]``.
    """

    operators: tuple[str, ...]
    commands: tuple[ASTNode, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Sequence:
    """A sequence of commands separated by ``;`` or newlines."""

    commands: tuple[ASTNode, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class Program:
    """The top-level node representing a complete parsed script or input line."""

    body: tuple[ASTNode, ...]
    span: Span


# ---------------------------------------------------------------------------
# Compound commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Group:
    """A brace group: ``{ list; }``.

    Executes *body* in the current shell environment.
    """

    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class Subshell:
    """A subshell group: ``( list )``.

    Executes *body* in a child copy of the current environment.
    """

    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class FunctionDef:
    """A function definition: ``name() { body; }`` or ``name() ( body )``.

    *body* is typically a ``Group`` or ``Subshell`` node.
    """

    name: str
    body: ASTNode
    span: Span


# ---------------------------------------------------------------------------
# Control-flow nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IfClause:
    """An ``if``/``elif``/``else`` construct.

    *conditions* and *bodies* are parallel tuples for the ``if`` and each
    ``elif`` branch.  *else_body* is ``None`` when there is no ``else``
    part.
    """

    conditions: tuple[ASTNode, ...]
    bodies: tuple[ASTNode, ...]
    else_body: ASTNode | None
    span: Span


@dataclass(frozen=True, slots=True)
class WhileLoop:
    """A ``while`` loop: ``while condition; do body; done``."""

    condition: ASTNode
    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class UntilLoop:
    """An ``until`` loop: ``until condition; do body; done``."""

    condition: ASTNode
    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class ForLoop:
    """A ``for`` loop: ``for name in words; do body; done``.

    When *words* is ``None`` the loop iterates over the positional
    parameters (``"$@"``).
    """

    variable: str
    words: tuple[Word, ...] | None
    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class ExtendedTest:
    """An extended test command: ``[[ expression ]]``."""

    words: tuple[Word, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class CStyleForLoop:
    """A C-style for loop: ``for (( init; condition; update )); do body; done``."""

    init: str
    condition: str
    update: str
    body: ASTNode
    span: Span


@dataclass(frozen=True, slots=True)
class CaseClause:
    """A ``case`` construct: ``case word in pattern) body ;; esac``.

    Each item in *items* is a ``CaseItem``.
    """

    word: Word
    items: tuple[CaseItem, ...]
    span: Span


@dataclass(frozen=True, slots=True)
class CaseItem:
    """A single arm of a ``case`` construct.

    *patterns* are the pipe-separated patterns and *body* is the
    command list to execute when a pattern matches.  *body* may be
    ``None`` for empty arms.
    """

    patterns: tuple[Word, ...]
    body: ASTNode | None
    span: Span


@dataclass(frozen=True, slots=True)
class RedirectedCommand:
    """A compound command wrapped with I/O redirections.

    Produced by ``redirected_statement`` when the inner command is
    *not* a :class:`SimpleCommand` (e.g. ``while``, ``for``, ``if``).
    ``SimpleCommand`` already carries its own ``redirections`` field,
    so it does not need this wrapper.
    """

    body: ASTNode
    redirections: tuple[Redirection, ...]
    span: Span
