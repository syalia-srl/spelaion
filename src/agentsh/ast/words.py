"""Word segment model for representing the internal structure of Bash words.

A Bash "word" is composed of segments that may be literal text, quoted
strings, variable expansions, command substitutions, arithmetic expansions,
or glob patterns.  After parsing, each word is a tuple of these segments;
the evaluator walks the segments to perform expansion, quoting, and
glob matching.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Segment types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LiteralSegment:
    """An unquoted literal string fragment.

    Example source: ``hello``
    """

    value: str


@dataclass(frozen=True, slots=True)
class SingleQuotedSegment:
    """A single-quoted string — no expansions are performed.

    Example source: ``'hello world'``
    """

    value: str


@dataclass(frozen=True, slots=True)
class ParameterExpansionSegment:
    """A parameter/variable expansion.

    Covers the following forms:
    - ``$name``           — name="name", operator=None, argument=None
    - ``${name}``         — name="name", operator=None, argument=None
    - ``${name:-default}``— name="name", operator=":-", argument="default"
    - ``${name:=value}``  — name="name", operator=":=", argument="value"
    - ``${name:+alt}``    — name="name", operator=":+", argument="alt"
    - ``${name:?err}``    — name="name", operator=":?", argument="err"
    - ``${#name}``        — name="name", operator="#", argument=None
    - ``${name%pat}``     — name="name", operator="%", argument="pat"
    - ``${name%%pat}``    — name="name", operator="%%", argument="pat"
    - ``${name#pat}``     — name="name", operator="#", argument="pat"
    - ``${name##pat}``    — name="name", operator="##", argument="pat"
    """

    name: str
    operator: str | None = None
    argument: str | None = None


@dataclass(frozen=True, slots=True)
class CommandSubstitutionSegment:
    """A command substitution — the raw source inside ``$(...)``.

    The *command* field contains the unparsed source text of the
    substituted command.  The evaluator will parse and execute it in a
    subshell context.

    Example source: ``$(ls -la)`` => command="ls -la"
    """

    command: str


@dataclass(frozen=True, slots=True)
class ArithmeticExpansionSegment:
    """An arithmetic expansion — ``$(( expression ))``.

    Example source: ``$(( x + 1 ))`` => expression="x + 1"
    """

    expression: str


@dataclass(frozen=True, slots=True)
class GlobSegment:
    """A glob/pathname-expansion pattern.

    Represents unquoted ``*``, ``?``, or ``[...]`` sequences that
    should be expanded against the virtual filesystem at evaluation time.

    Example source: ``*.py`` => pattern="*.py"
    """

    pattern: str


@dataclass(frozen=True, slots=True)
class ProcessSubstitutionSegment:
    """A process substitution — ``<(command)`` or ``>(command)``."""

    command: str
    direction: str  # "<" or ">"


@dataclass(frozen=True, slots=True)
class DoubleQuotedSegment:
    """A double-quoted string — may contain nested expansions.

    The *segments* tuple can include ``LiteralSegment``,
    ``ParameterExpansionSegment``, ``CommandSubstitutionSegment``, and
    ``ArithmeticExpansionSegment`` (but not ``GlobSegment`` or
    ``SingleQuotedSegment``, as those are not recognised inside double
    quotes).

    Example source: ``"hello ${name}"``
    """

    segments: tuple[WordSegment, ...]


# ---------------------------------------------------------------------------
# Union type
# ---------------------------------------------------------------------------

#: The discriminated union of all word segment types.
WordSegment = (
    LiteralSegment
    | SingleQuotedSegment
    | DoubleQuotedSegment
    | ParameterExpansionSegment
    | CommandSubstitutionSegment
    | ArithmeticExpansionSegment
    | GlobSegment
    | ProcessSubstitutionSegment
)

# Update the forward reference now that WordSegment is defined.
# With ``from __future__ import annotations`` all annotations are strings,
# so the tuple[WordSegment, ...] inside DoubleQuotedSegment resolves
# correctly at type-checking time.  No runtime patching is needed.
