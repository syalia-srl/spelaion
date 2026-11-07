"""CST to AST normalization pass.

Converts tree-sitter CST nodes into project-owned AST nodes.
Unsupported syntax raises explicit diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tree_sitter import Node

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
    RedirectedCommand,
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
from agentsh.parser.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    UnsupportedSyntaxError,
)

_REDIRECT_TYPES: frozenset[str] = frozenset(
    {"file_redirect", "heredoc_redirect", "herestring_redirect"}
)


def _span(node: Node) -> Span:
    return Span(
        start_byte=node.start_byte,
        end_byte=node.end_byte,
        start_point=Point(row=node.start_point[0], column=node.start_point[1]),
        end_point=Point(row=node.end_point[0], column=node.end_point[1]),
    )


def _node_text(node: Node, source: str) -> str:
    return source[node.start_byte : node.end_byte]


def _named_children(node: Node) -> list[Node]:
    return [c for c in node.children if c.is_named]


def _try_normalize_node(
    child: Node,
    source: str,
    diagnostics: list[Diagnostic],
    target: list[ASTNode],
) -> None:
    """Normalize *child* and append the result to *target*.

    If normalization raises :class:`UnsupportedSyntaxError`, a warning
    diagnostic is emitted instead.
    """
    try:
        ast_node = _normalize_node(child, source, diagnostics)
        if ast_node is not None:
            target.append(ast_node)
    except UnsupportedSyntaxError as e:
        diagnostics.append(
            Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                message=f"Unsupported syntax: {e}",
                span=_span(child),
            )
        )


def _as_body(parts: list[ASTNode], span: Span) -> ASTNode:
    """Collapse a list of nodes into a single body node."""
    if len(parts) == 1:
        return parts[0]
    return Sequence(commands=tuple(parts), span=span)


def normalize(root: Node, source: str) -> tuple[Program, list[Diagnostic]]:
    """Normalize a tree-sitter CST root into a project-owned AST Program."""
    diagnostics: list[Diagnostic] = []
    body = _normalize_children(root, source, diagnostics)
    return Program(body=tuple(body), span=_span(root)), diagnostics


def _normalize_children(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> list[ASTNode]:
    results: list[ASTNode] = []
    for child in node.children:
        if not child.is_named:
            continue
        if child.type == "ERROR":
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    message=f"Syntax error: {_node_text(child, source)!r}",
                    span=_span(child),
                )
            )
            continue
        try:
            ast_node = _normalize_node(child, source, diagnostics)
            if ast_node is not None:
                results.append(ast_node)
        except UnsupportedSyntaxError as e:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported syntax: {e}",
                    span=_span(child),
                )
            )
    return results


def _normalize_node(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> ASTNode | None:
    handler = _NODE_HANDLERS.get(node.type)
    if handler is not None:
        return handler(node, source, diagnostics)

    # Treat unknown named nodes as unsupported
    if node.type in _IGNORED_TYPES:
        return None

    raise UnsupportedSyntaxError(
        f"Node type '{node.type}' is not supported", node_type=node.type
    )


def _normalize_program(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Program:
    body = _normalize_children(node, source, diagnostics)
    return Program(body=tuple(body), span=_span(node))


def _normalize_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> ASTNode | None:
    """Normalize a 'command' node.

    In tree-sitter-bash, a 'command' node with a 'command_name' child
    is a simple command. Otherwise, dispatch to contained nodes.
    """
    # Check if this is a simple command (has command_name child)
    has_command_name = any(
        c.type == "command_name" for c in node.children if c.is_named
    )
    if has_command_name:
        return _normalize_simple_command(node, source, diagnostics)

    named = _named_children(node)
    if not named:
        return None
    if len(named) == 1:
        return _normalize_node(named[0], source, diagnostics)
    # Multiple named children — treat as sequence
    children: list[ASTNode] = []
    for child in named:
        try:
            ast_node = _normalize_node(child, source, diagnostics)
            if ast_node is not None:
                children.append(ast_node)
        except UnsupportedSyntaxError as e:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported: {e}",
                    span=_span(child),
                )
            )
    return _as_body(children, _span(node))


def _normalize_simple_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand:
    words: list[Word] = []
    assignments: list[AssignmentWord | ArrayAssignmentWord] = []
    redirections: list[Redirection] = []

    for child in node.children:
        if not child.is_named:
            continue
        if child.type == "variable_assignment":
            assignments.append(_normalize_assignment(child, source, diagnostics))
        elif child.type in _REDIRECT_TYPES:
            redirections.append(_normalize_redirection(child, source, diagnostics))
        else:
            # command_name, word, string, concatenation, expansion, etc.
            words.append(_normalize_word_node(child, source))

    return SimpleCommand(
        words=tuple(words),
        assignments=tuple(assignments),
        redirections=tuple(redirections),
        span=_span(node),
    )


def _normalize_assignment(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> AssignmentWord | ArrayAssignmentWord:
    name_node = node.child_by_field_name("name")
    value_node = node.child_by_field_name("value")

    name = _node_text(name_node, source) if name_node else ""

    # Check for array assignment: name=(val1 val2 ...)
    for child in node.children:
        if child.type == "array":
            values: list[Word] = []
            for elem in child.children:
                if elem.is_named:
                    values.append(_normalize_word_node(elem, source))
            return ArrayAssignmentWord(
                name=name, values=tuple(values), span=_span(node)
            )

    # Handle subscript assignment: name[idx]=value
    if name_node and "[" in _node_text(name_node, source):
        raw_name = _node_text(name_node, source)
        # Keep full name[idx] as the name for the executor to parse
        name = raw_name

    value = _normalize_word_node(value_node, source) if value_node else None

    return AssignmentWord(name=name, value=value, span=_span(node))


def _parse_heredoc_body(text: str) -> list[WordSegment]:
    """Parse heredoc body text to extract expansion segments.

    Scans character-by-character to find:
    - ``$((expr))`` -> ArithmeticExpansionSegment
    - ``$(cmd)``    -> CommandSubstitutionSegment
    - ``${var}``    -> ParameterExpansionSegment
    - ``$name``     -> ParameterExpansionSegment
    - Everything else -> LiteralSegment
    """
    segments: list[WordSegment] = []
    i = 0
    n = len(text)
    literal_start = 0

    while i < n:
        if text[i] == "$" and i + 1 < n:
            if i > literal_start:
                segments.append(LiteralSegment(value=text[literal_start:i]))
            seg, new_i = _scan_dollar(text, i, n)
            segments.append(seg)
            i = new_i
            literal_start = i
        else:
            i += 1

    if literal_start < n:
        segments.append(LiteralSegment(value=text[literal_start:]))

    return segments


def _scan_dollar(text: str, i: int, n: int) -> tuple[WordSegment, int]:
    """Parse a single ``$``-initiated expansion starting at index *i*.

    Returns ``(segment, new_index)`` where *new_index* is the position
    immediately after the consumed expansion.
    """
    next_ch = text[i + 1]

    # $((...)) — arithmetic expansion
    if next_ch == "(" and i + 2 < n and text[i + 2] == "(":
        seg, end = _scan_arith_expansion(text, i, n)
        if seg is not None:
            return seg, end

    # $(...) — command substitution
    if next_ch == "(":
        seg, end = _scan_command_sub(text, i, n)
        if seg is not None:
            return seg, end

    # ${...} — braced parameter expansion
    if next_ch == "{":
        j = text.find("}", i + 2)
        if j >= 0:
            inner = text[i + 2 : j]
            return _parse_braced_param(inner), j + 1

    # $name — simple variable
    if next_ch == "_" or next_ch.isalpha():
        j = i + 2
        while j < n and (text[j].isalnum() or text[j] == "_"):
            j += 1
        return ParameterExpansionSegment(name=text[i + 1 : j]), j

    # $digit — positional parameter
    if next_ch.isdigit():
        return ParameterExpansionSegment(name=next_ch), i + 2

    # $? $# $@ $* $! $$ $- — special parameters
    if next_ch in "?#@*!$-":
        return ParameterExpansionSegment(name=next_ch), i + 2

    # Lone $ — literal
    return LiteralSegment(value="$"), i + 1


def _scan_arith_expansion(
    text: str, i: int, n: int
) -> tuple[ArithmeticExpansionSegment | None, int]:
    """Try to scan ``$((...))`` at *i*.

    Returns ``(seg, end)`` or ``(None, 0)``.
    """
    depth = 1
    j = i + 3
    while j < n - 1 and depth > 0:
        if text[j] == "(" and text[j + 1] == "(":
            depth += 1
            j += 2
        elif text[j] == ")" and text[j + 1] == ")":
            depth -= 1
            if depth == 0:
                break
            j += 2
        else:
            j += 1
    if depth == 0:
        return ArithmeticExpansionSegment(expression=text[i + 3 : j]), j + 2
    return None, 0


def _scan_command_sub(
    text: str, i: int, n: int
) -> tuple[CommandSubstitutionSegment | None, int]:
    """Try to scan ``$(...)`` at *i*.

    Returns ``(seg, end)`` or ``(None, 0)``.
    """
    depth = 1
    j = i + 2
    while j < n and depth > 0:
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
        j += 1
    if depth == 0:
        return CommandSubstitutionSegment(command=text[i + 2 : j - 1]), j
    return None, 0


#: Operator strings checked in priority order for parameter expansions.
_PARAM_OPERATORS: tuple[str, ...] = (
    ":-",
    ":+",
    ":=",
    ":?",
    "-",
    "+",
    "=",
    "?",
    "//",
    "/",
    "##",
    "#",
    "%%",
    "%",
    "^^",
    "^",
    ",,",
    ",",
)


def _parse_braced_param(inner: str) -> ParameterExpansionSegment:
    """Parse the content inside ``${...}`` into a ParameterExpansionSegment.

    Delegates to the same helpers used by :func:`_parse_expansion`:
    :func:`_parse_length_expansion` and :func:`_find_operator`.

    Note: unlike :func:`_parse_expansion`, which uses the full tree-sitter
    CST, this function operates on raw text extracted from heredoc bodies.
    For subscript expressions with a trailing operator (e.g. ``arr[0]:-val``),
    it falls through to :func:`_find_operator` so that the operator is
    matched against the full inner string rather than the post-bracket suffix.
    """
    # ${#var} — string length
    if inner.startswith("#") and not inner.startswith("##"):
        return _parse_length_expansion(inner[1:])

    # ${arr[idx]} — simple subscript only (no trailing operator)
    if "[" in inner:
        bracket_start = inner.index("[")
        rest = inner[bracket_start:]
        bracket_end = rest.find("]")
        if bracket_end >= 0:
            after = rest[bracket_end + 1 :]
            if not after:
                name = inner[:bracket_start]
                subscript = rest[1:bracket_end]
                return ParameterExpansionSegment(
                    name=name, operator="[", argument=subscript
                )

    # Check for operators (:-  :+  //  ##  %% etc.)
    return _find_operator(inner)


def _normalize_herestring_redirect(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Redirection:
    """Normalize a here-string redirection (<<<)."""
    fd: int | None = None
    target_word: Word | None = None

    for child in node.children:
        if child.type == "file_descriptor":
            fd = int(_node_text(child, source))
        elif child.is_named and child.type != "file_descriptor":
            target_word = _normalize_word_node(child, source)
    if target_word is None:
        full = _node_text(node, source)
        idx = full.find("<<<")
        body = full[idx + 3 :].strip() if idx >= 0 else ""
        target_word = Word(segments=(LiteralSegment(value=body),), span=_span(node))
    return Redirection(op="<<<", fd=fd, target=target_word, span=_span(node))


def _normalize_heredoc_redirect(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Redirection:
    """Normalize a here-doc redirection (<<, <<-)."""
    fd: int | None = None

    # Detect <<- (tab-stripping variant)
    strip_tabs = False
    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text == "<<-":
                strip_tabs = True

    # Find the heredoc body node and delimiter
    body_node = None
    delimiter_node = None
    for child in node.children:
        if child.type == "heredoc_body":
            body_node = child
        elif child.type == "heredoc_start" or (
            delimiter_node is None
            and child.is_named
            and child.type
            not in (
                "heredoc_body",
                "heredoc_end",
                "file_descriptor",
            )
        ):
            delimiter_node = child

    # Determine if delimiter was quoted (suppresses expansion)
    quoted_delimiter = False
    if delimiter_node:
        dtxt = _node_text(delimiter_node, source)
        if dtxt.startswith("'") or dtxt.startswith('"') or "\\" in dtxt:
            quoted_delimiter = True

    if body_node:
        body_text = _node_text(body_node, source)
        # Remove the trailing delimiter line
        lines = body_text.split("\n")
        if lines and lines[-1].strip() == "":
            lines = lines[:-1]
        # Strip tabs for <<-
        if strip_tabs:
            lines = [line.lstrip("\t") for line in lines]
        body_text = "\n".join(lines)
        if body_text and not body_text.endswith("\n"):
            body_text += "\n"
    else:
        body_text = ""

    if quoted_delimiter:
        target_word = Word(
            segments=(SingleQuotedSegment(value=body_text),), span=_span(node)
        )
    else:
        # Unquoted delimiter: expand variables in the body
        parsed_segments = _parse_heredoc_body(body_text)
        target_word = Word(
            segments=(DoubleQuotedSegment(segments=tuple(parsed_segments)),),
            span=_span(node),
        )
    return Redirection(op="<<", fd=fd, target=target_word, span=_span(node))


def _normalize_redirection(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Redirection:
    """Normalize a redirection node into a Redirection AST node."""
    if node.type == "herestring_redirect":
        return _normalize_herestring_redirect(node, source, diagnostics)
    if node.type == "heredoc_redirect":
        return _normalize_heredoc_redirect(node, source, diagnostics)

    # --- normal file redirections ---
    fd: int | None = None
    op = ""
    target_word: Word | None = None

    for child in node.children:
        if child.type == "file_descriptor":
            fd = int(_node_text(child, source))
        elif not child.is_named:
            text = _node_text(child, source)
            if text in (">", ">>", "<", "<<", "<<<", ">&", "<&", "2>", "2>>"):
                op = text
        else:
            target_word = _normalize_word_node(child, source)

    if not op:
        # Infer from the full text
        full = _node_text(node, source)
        for candidate in (">>>", ">>", ">", "<<<", "<<", "<", ">&", "<&"):
            if candidate in full:
                op = candidate
                break

    if target_word is None:
        target_word = Word(segments=(LiteralSegment(value=""),), span=_span(node))

    return Redirection(op=op, fd=fd, target=target_word, span=_span(node))


def _normalize_pipeline(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Pipeline | ASTNode:
    negated = False
    commands: list[ASTNode] = []

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text == "!":
                negated = True
            continue
        try:
            ast_node = _normalize_node(child, source, diagnostics)
            if ast_node is not None:
                commands.append(ast_node)
        except UnsupportedSyntaxError as e:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported in pipeline: {e}",
                    span=_span(child),
                )
            )

    if len(commands) == 1 and not negated:
        return commands[0]

    return Pipeline(commands=tuple(commands), negated=negated, span=_span(node))


def _normalize_list(node: Node, source: str, diagnostics: list[Diagnostic]) -> ASTNode:
    """Normalize a 'list' node.

    In tree-sitter-bash, 'list' is used for both:
    - Semicolon/newline separated commands
    - And/or lists (&&, ||)
    We detect which case based on operators between children.
    """
    # Check for && or || operators
    operators: list[str] = []
    commands: list[ASTNode] = []

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text in ("&&", "||"):
                operators.append(text)
            continue
        try:
            ast_node = _normalize_node(child, source, diagnostics)
            if ast_node is not None:
                commands.append(ast_node)
        except UnsupportedSyntaxError as e:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported in list: {e}",
                    span=_span(child),
                )
            )

    if len(commands) == 1:
        return commands[0]

    # If we found && or || operators, this is an AndOrList
    if operators:
        return AndOrList(
            operators=tuple(operators),
            commands=tuple(commands),
            span=_span(node),
        )

    return Sequence(commands=tuple(commands), span=_span(node))


def _normalize_and_or(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> AndOrList:
    operators: list[str] = []
    commands: list[ASTNode] = []

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text in ("&&", "||"):
                operators.append(text)
            continue
        try:
            ast_node = _normalize_node(child, source, diagnostics)
            if ast_node is not None:
                commands.append(ast_node)
        except UnsupportedSyntaxError as e:
            diagnostics.append(
                Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    message=f"Unsupported in and/or: {e}",
                    span=_span(child),
                )
            )

    return AndOrList(
        operators=tuple(operators),
        commands=tuple(commands),
        span=_span(node),
    )


def _normalize_subshell(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Subshell:
    children = _normalize_children(node, source, diagnostics)
    return Subshell(body=_as_body(children, _span(node)), span=_span(node))


def _normalize_group(node: Node, source: str, diagnostics: list[Diagnostic]) -> Group:
    children = _normalize_children(node, source, diagnostics)
    return Group(body=_as_body(children, _span(node)), span=_span(node))


def _normalize_function_def(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> FunctionDef:
    name = ""
    body: ASTNode | None = None

    name_node = node.child_by_field_name("name")
    body_node = node.child_by_field_name("body")

    if name_node:
        name = _node_text(name_node, source)
    if body_node:
        try:
            body = _normalize_node(body_node, source, diagnostics)
        except UnsupportedSyntaxError:
            body = None

    if body is None:
        # Fallback: try to find body in children
        for child in _named_children(node):
            if child.type in ("compound_statement", "subshell", "list"):
                body = _normalize_node(child, source, diagnostics)
                break

    if body is None:
        body = Sequence(commands=(), span=_span(node))

    return FunctionDef(name=name, body=body, span=_span(node))


def _normalize_negated_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> Pipeline:
    children = _normalize_children(node, source, diagnostics)
    if len(children) == 1:
        return Pipeline(commands=(children[0],), negated=True, span=_span(node))
    return Pipeline(commands=tuple(children), negated=True, span=_span(node))


def _normalize_variable_assignments(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand:
    """Normalize multiple variable assignments (FOO=bar BAR=baz)."""
    assignments: list[AssignmentWord | ArrayAssignmentWord] = []
    for child in node.children:
        if child.is_named and child.type == "variable_assignment":
            assignments.append(_normalize_assignment(child, source, diagnostics))
    return SimpleCommand(
        words=(),
        assignments=tuple(assignments),
        redirections=(),
        span=_span(node),
    )


def _normalize_unset_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand:
    """Normalize an unset_command into a SimpleCommand."""
    words: list[Word] = [
        Word(segments=(LiteralSegment(value="unset"),), span=_span(node))
    ]
    for child in node.children:
        if child.is_named and child.type in ("variable_name", "word"):
            words.append(
                Word(
                    segments=(LiteralSegment(value=_node_text(child, source)),),
                    span=_span(child),
                )
            )
    return SimpleCommand(
        words=tuple(words),
        assignments=(),
        redirections=(),
        span=_span(node),
    )


def _normalize_declaration_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand:
    """Normalize a declaration_command (export, declare, local, etc.).

    Tree-sitter: declaration_command has the keyword (export/declare/local)
    as an unnamed child and variable_assignment(s) as named children.
    """
    cmd_word: Word | None = None
    words: list[Word] = []

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text in ("export", "declare", "local", "readonly", "typeset"):
                cmd_word = Word(
                    segments=(LiteralSegment(value=text),),
                    span=_span(child),
                )
            continue
        if child.type == "variable_assignment":
            # Convert to a word arg like "FOO=bar" for the builtin.
            # Array initializers (name=(...)) use SingleQuotedSegment to
            # prevent word splitting on spaces inside the parentheses.
            name_node = child.child_by_field_name("name")
            name = _node_text(name_node, source) if name_node else ""
            has_array = any(c.type == "array" for c in child.children)
            value_node = child.child_by_field_name("value")
            if has_array or value_node:
                value_text = _node_text(child, source)
                # Remove leading "name=" prefix — we already have it
                eq_idx = value_text.find("=")
                val_part = value_text[eq_idx + 1 :] if eq_idx >= 0 else ""
                if has_array:
                    # Prevent word splitting on array init values
                    words.append(
                        Word(
                            segments=(SingleQuotedSegment(value=f"{name}={val_part}"),),
                            span=_span(child),
                        )
                    )
                elif value_node is not None:
                    # Normalize the value node to preserve expansions
                    # (e.g. local x="$1" must expand $1).
                    value_segments = _extract_segments(value_node, source)
                    all_segs: list[WordSegment] = [LiteralSegment(value=f"{name}=")]
                    all_segs.extend(value_segments)
                    words.append(
                        Word(
                            segments=tuple(all_segs),
                            span=_span(child),
                        )
                    )
            else:
                words.append(
                    Word(
                        segments=(LiteralSegment(value=name),),
                        span=_span(child),
                    )
                )
        elif child.type == "variable_name":
            # Bare variable name (e.g. ``declare -A name``)
            words.append(
                Word(
                    segments=(LiteralSegment(value=_node_text(child, source)),),
                    span=_span(child),
                )
            )
        elif child.type in ("word", "string", "raw_string", "simple_expansion"):
            words.append(_normalize_word_node(child, source))

    all_words: list[Word] = []
    if cmd_word:
        all_words.append(cmd_word)
    all_words.extend(words)

    return SimpleCommand(
        words=tuple(all_words),
        assignments=(),
        redirections=(),
        span=_span(node),
    )


def _normalize_standalone_assignment(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand:
    """Normalize a top-level variable_assignment into a SimpleCommand with no words."""
    assignment = _normalize_assignment(node, source, diagnostics)
    return SimpleCommand(
        words=(),
        assignments=(assignment,),
        redirections=(),
        span=_span(node),
    )


def _normalize_redirected_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> ASTNode:
    """A redirected_statement wraps a command with redirections."""
    body_node = node.child_by_field_name("body")
    redirect_nodes = [
        c for c in node.children if c.is_named and c.type in _REDIRECT_TYPES
    ]

    if body_node is not None:
        inner = _normalize_node(body_node, source, diagnostics)
        if isinstance(inner, SimpleCommand) and redirect_nodes:
            extra_redirs = [
                _normalize_redirection(r, source, diagnostics) for r in redirect_nodes
            ]
            return SimpleCommand(
                words=inner.words,
                assignments=inner.assignments,
                redirections=inner.redirections + tuple(extra_redirs),
                span=_span(node),
            )
        if redirect_nodes and inner is not None:
            extra_redirs = [
                _normalize_redirection(r, source, diagnostics) for r in redirect_nodes
            ]
            return RedirectedCommand(
                body=inner,
                redirections=tuple(extra_redirs),
                span=_span(node),
            )
        return inner  # type: ignore[return-value]

    # Fallback
    children = _normalize_children(node, source, diagnostics)
    return _as_body(children, _span(node))


# --- Word normalization ---


def _normalize_word_node(node: Node, source: str) -> Word:
    """Convert a CST word-like node into a Word with segments."""
    segments = _extract_segments(node, source)
    if not segments:
        segments = [LiteralSegment(value=_node_text(node, source))]
    return Word(segments=tuple(segments), span=_span(node))


def _extract_segments(node: Node, source: str) -> list[WordSegment]:  # noqa: C901
    """Recursively extract word segments from a CST node."""
    ntype = node.type

    if ntype == "word":
        text = _node_text(node, source)
        # Check for glob characters in unquoted words
        if any(c in text for c in ("*", "?", "[")):
            return [GlobSegment(pattern=text)]
        return [LiteralSegment(value=text)]

    if ntype == "number":
        return [LiteralSegment(value=_node_text(node, source))]

    if ntype == "raw_string":
        # Single-quoted string: 'content'
        text = _node_text(node, source)
        # Strip surrounding quotes
        if text.startswith("'") and text.endswith("'"):
            text = text[1:-1]
        return [SingleQuotedSegment(value=text)]

    if ntype == "string":
        # Double-quoted string: "content"
        return _extract_double_quoted(node, source)

    if ntype == "simple_expansion":
        # $VAR — use helper to properly extract variable name
        prefix, var_name = _extract_simple_expansion(node, source)
        result: list[WordSegment] = []
        if prefix:
            result.append(LiteralSegment(value=prefix))
        result.append(ParameterExpansionSegment(name=var_name))
        return result

    if ntype == "expansion":
        # ${VAR}, ${VAR:-default}, etc.
        return [_parse_expansion(node, source)]

    if ntype == "command_substitution":
        # $(command)
        text = _node_text(node, source)
        if text.startswith("$(") and text.endswith(")"):
            cmd = text[2:-1]
        elif text.startswith("`") and text.endswith("`"):
            cmd = text[1:-1]
        else:
            cmd = text
        return [CommandSubstitutionSegment(command=cmd)]

    if ntype == "arithmetic_expansion":
        text = _node_text(node, source)
        expr = text[3:-2] if text.startswith("$((") and text.endswith("))") else text
        return [ArithmeticExpansionSegment(expression=expr)]

    if ntype == "process_substitution":
        text = _node_text(node, source)
        if text.startswith("<(") and text.endswith(")"):
            return [ProcessSubstitutionSegment(command=text[2:-1], direction="<")]
        if text.startswith(">(") and text.endswith(")"):
            return [ProcessSubstitutionSegment(command=text[2:-1], direction=">")]
        return [LiteralSegment(value=text)]

    if ntype == "concatenation":
        segments: list[WordSegment] = []
        for child in node.children:
            if child.is_named:
                segments.extend(_extract_segments(child, source))
            else:
                text = _node_text(child, source)
                if text:
                    segments.append(LiteralSegment(value=text))
        return segments

    if ntype == "string_content":
        return [LiteralSegment(value=_node_text(node, source))]

    # Fallback: treat as literal
    return [LiteralSegment(value=_node_text(node, source))]


def _extract_simple_expansion(node: Node, source: str) -> tuple[str, str]:
    """Extract the variable name from a simple_expansion node.

    Returns (prefix_text, var_name). The prefix is any text before the $
    that tree-sitter includes in the span (e.g. spaces).
    """
    # Look for variable_name or special_variable_name child
    for child in node.children:
        if child.type in ("variable_name", "special_variable_name"):
            var_name = _node_text(child, source)
            # Calculate prefix: text between node start and $
            full_text = _node_text(node, source)
            dollar_idx = full_text.find("$")
            prefix = full_text[:dollar_idx] if dollar_idx > 0 else ""
            return prefix, var_name

    # Fallback: strip $ from text
    full_text = _node_text(node, source)
    dollar_idx = full_text.find("$")
    if dollar_idx >= 0:
        prefix = full_text[:dollar_idx]
        var_name = full_text[dollar_idx + 1 :]
        return prefix, var_name

    return "", full_text.lstrip("$")


def _extract_dq_child(child: Node, source: str, out: list[WordSegment]) -> None:
    """Dispatch a single child node inside a double-quoted string."""
    if not child.is_named:
        text = _node_text(child, source)
        if text not in ('"',):
            out.append(LiteralSegment(value=text))
    elif child.type == "string_content":
        out.append(LiteralSegment(value=_node_text(child, source)))
    elif child.type == "simple_expansion":
        prefix, var_name = _extract_simple_expansion(child, source)
        if prefix:
            out.append(LiteralSegment(value=prefix))
        out.append(ParameterExpansionSegment(name=var_name))
    elif child.type == "expansion":
        full_text = _node_text(child, source)
        brace_idx = full_text.find("${")
        if brace_idx > 0:
            out.append(LiteralSegment(value=full_text[:brace_idx]))
        out.append(_parse_expansion(child, source))
    elif child.type == "command_substitution":
        text = _node_text(child, source)
        if text.startswith("$(") and text.endswith(")"):
            cmd = text[2:-1]
        elif text.startswith("`") and text.endswith("`"):
            cmd = text[1:-1]
        else:
            cmd = text
        out.append(CommandSubstitutionSegment(command=cmd))
    elif child.type == "arithmetic_expansion":
        text = _node_text(child, source)
        expr = text[3:-2] if text.startswith("$((") and text.endswith("))") else text
        out.append(ArithmeticExpansionSegment(expression=expr))
    else:
        out.extend(_extract_segments(child, source))


def _extract_double_quoted(node: Node, source: str) -> list[WordSegment]:
    """Extract segments from a double-quoted string node.

    Tracks byte positions to capture any source text that falls between
    tree-sitter children (e.g. newlines between ``string_content`` nodes
    in a multiline double-quoted string).
    """
    segments: list[WordSegment] = []
    inner_segments: list[WordSegment] = []

    # Byte cursor: starts right after the opening quote.
    cursor = node.start_byte

    for child in node.children:
        # Capture any gap text between the previous child and this one.
        if child.start_byte > cursor:
            gap = source[cursor : child.start_byte]
            # Skip the opening/closing quote characters themselves.
            if gap and gap != '"':
                inner_segments.append(LiteralSegment(value=gap))

        _extract_dq_child(child, source, inner_segments)
        cursor = child.end_byte

    # Always create a DoubleQuotedSegment, even for empty strings like ""
    segments.append(DoubleQuotedSegment(segments=tuple(inner_segments)))

    return segments


def _parse_expansion(node: Node, source: str) -> ParameterExpansionSegment:
    """Parse a ${...} expansion node.

    Use child nodes when available for accuracy, falling back to text parsing.
    """
    text = _node_text(node, source)
    # Find the actual ${...} content
    brace_start = text.find("${")
    if brace_start >= 0 and text.endswith("}"):
        inner = text[brace_start + 2 : -1]
    elif text.startswith("${") and text.endswith("}"):
        inner = text[2:-1]
    else:
        inner = text.lstrip(" $")

    # ${#var} — string length operator
    if inner.startswith("#") and not inner.startswith("##"):
        return _parse_length_expansion(inner[1:])

    # ${!name[@]} / ${!name[*]} — array keys expansion
    if inner.startswith("!") and "[" in inner:
        result = _parse_indirect_expansion(inner)
        if result is not None:
            return result

    # ${arr[idx]} — array subscript (possibly with further operator)
    if "[" in inner:
        return _parse_subscript_expansion(inner)

    # ${var:offset:length} — substring extraction
    result = _parse_substring_expansion(inner)
    if result is not None:
        return result

    # Check for operators
    return _find_operator(inner)


def _parse_length_expansion(rest: str) -> ParameterExpansionSegment:
    """Parse ``${#var}`` or ``${#arr[@]}``."""
    if "[" in rest:
        arr_name = rest[: rest.index("[")]
        return ParameterExpansionSegment(name=arr_name, operator="#[", argument=None)
    return ParameterExpansionSegment(name=rest, operator="#len", argument=None)


def _parse_indirect_expansion(inner: str) -> ParameterExpansionSegment | None:
    """Parse ``${!name[@]}`` / ``${!name[*]}``."""
    bracket_start = inner.index("[")
    arr_name = inner[1:bracket_start]
    bracket_rest = inner[bracket_start:]
    bracket_end = bracket_rest.find("]")
    if bracket_end >= 0:
        subscript = bracket_rest[1:bracket_end]
        if subscript in ("@", "*"):
            return ParameterExpansionSegment(
                name=arr_name, operator="![@]", argument=None
            )
    return None


def _parse_subscript_expansion(inner: str) -> ParameterExpansionSegment:
    """Parse ``${arr[idx]}`` and ``${arr[idx]op...}``."""
    bracket_start = inner.index("[")
    name = inner[:bracket_start]
    rest = inner[bracket_start:]
    bracket_end = rest.find("]")
    if bracket_end >= 0:
        subscript = rest[1:bracket_end]
        after = rest[bracket_end + 1 :]
        if not after:
            return ParameterExpansionSegment(
                name=name, operator="[", argument=subscript
            )
        # ${arr[idx]op...} e.g. ${arr[0]:-default}
        for op in (*_PARAM_OPERATORS, ":"):
            if after.startswith(op):
                arg = after[len(op) :]
                return ParameterExpansionSegment(
                    name=name,
                    operator=f"[{subscript}]{op}",
                    argument=arg,
                )
        return ParameterExpansionSegment(name=name, operator="[", argument=subscript)
    return ParameterExpansionSegment(name=inner)


def _parse_substring_expansion(
    inner: str,
) -> ParameterExpansionSegment | None:
    """Parse ``${var:offset:length}``."""
    colon_idx = inner.find(":")
    if colon_idx > 0:
        after_colon = inner[colon_idx + 1 :]
        if (
            after_colon
            and after_colon[0] in "0123456789- "
            and not after_colon.startswith(("-", "+", "=", "?"))
        ):
            name = inner[:colon_idx]
            return ParameterExpansionSegment(
                name=name, operator=":", argument=after_colon
            )
    return None


def _find_operator(inner: str) -> ParameterExpansionSegment:
    """Scan *inner* for a known parameter expansion operator."""
    for op in _PARAM_OPERATORS:
        idx = inner.find(op)
        if idx > 0:
            name = inner[:idx]
            argument = inner[idx + len(op) :]
            return ParameterExpansionSegment(name=name, operator=op, argument=argument)
    return ParameterExpansionSegment(name=inner)


def _normalize_if_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> IfClause:
    """Normalize an if/elif/else statement into an IfClause AST node.

    tree-sitter-bash CST structure:
      if_statement -> if, condition_cmd, ;, then, body_cmd, ;,
                      [elif_clause -> elif, cond, ;, then, body, ;]*,
                      [else_clause -> else, body, ;],
                      fi
    The condition and body are direct named children between keywords.
    elif_clause and else_clause are named nodes wrapping their content.
    """
    conditions: list[ASTNode] = []
    bodies: list[ASTNode] = []
    else_body: ASTNode | None = None

    # Phase 1: collect condition and body from if-branch
    phase = "seek_cond"
    cond_parts: list[ASTNode] = []
    body_parts: list[ASTNode] = []

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text == "if":
                phase = "cond"
            elif text == "then":
                if cond_parts:
                    conditions.append(_as_body(cond_parts, _span(node)))
                    cond_parts = []
                phase = "body"
            elif text == "fi":
                pass
            continue

        # Named children
        if child.type == "elif_clause":
            # Finalize current body
            if body_parts:
                bodies.append(_as_body(body_parts, _span(node)))
                body_parts = []
            # Parse elif recursively
            elif_cond, elif_body = _parse_elif_clause(child, source, diagnostics)
            conditions.append(elif_cond)
            bodies.append(elif_body)

        elif child.type == "else_clause":
            # Finalize current body
            if body_parts:
                bodies.append(_as_body(body_parts, _span(node)))
                body_parts = []
            # Parse else body
            else_parts = _normalize_children(child, source, diagnostics)
            if else_parts:
                else_body = _as_body(else_parts, _span(child))

        elif phase == "cond":
            _try_normalize_node(child, source, diagnostics, cond_parts)

        elif phase == "body":
            _try_normalize_node(child, source, diagnostics, body_parts)

    # Finalize last body
    if body_parts:
        bodies.append(_as_body(body_parts, _span(node)))

    return IfClause(
        conditions=tuple(conditions),
        bodies=tuple(bodies),
        else_body=else_body,
        span=_span(node),
    )


def _parse_elif_clause(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> tuple[ASTNode, ASTNode]:
    """Parse an elif_clause into (condition, body)."""
    cond_parts: list[ASTNode] = []
    body_parts: list[ASTNode] = []
    phase = "cond"

    for child in node.children:
        if not child.is_named:
            text = _node_text(child, source)
            if text == "then":
                phase = "body"
            continue

        target = cond_parts if phase == "cond" else body_parts
        _try_normalize_node(child, source, diagnostics, target)

    condition = _as_body(cond_parts, _span(node))
    body = _as_body(body_parts, _span(node))
    return condition, body


def _normalize_for_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> ForLoop:
    """Normalize a for loop into a ForLoop AST node."""
    variable = ""
    words: list[Word] | None = None
    body: ASTNode = Sequence(commands=(), span=_span(node))

    var_node = node.child_by_field_name("variable")
    if var_node:
        variable = _node_text(var_node, source)

    # Find 'in' words
    in_found = False
    for child in node.children:
        if child.type == "in":
            in_found = True
            continue
        if in_found and child.type in ("do", ";", "\n"):
            break
        if in_found and child.is_named:
            words = words or []
            words.append(_normalize_word_node(child, source))

    # Find body (do_group)
    body_node = node.child_by_field_name("body")
    if body_node:
        body_children = _normalize_children(body_node, source, diagnostics)
        if body_children:
            body = _as_body(body_children, _span(body_node))

    return ForLoop(
        variable=variable,
        words=tuple(words) if words else None,
        body=body,
        span=_span(node),
    )


def _normalize_while_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> WhileLoop | UntilLoop:
    """Normalize a while/until loop.

    tree-sitter reports both ``while`` and ``until`` as
    ``while_statement``; the keyword child distinguishes them.
    """
    condition, body = _extract_loop_condition_body(node, source, diagnostics)
    # Check first child text for "until" keyword
    first = node.children[0] if node.children else None
    if first is not None and first.type == "until":
        return UntilLoop(condition=condition, body=body, span=_span(node))
    return WhileLoop(condition=condition, body=body, span=_span(node))


def _normalize_until_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> UntilLoop:
    """Normalize an until loop into an UntilLoop AST node."""
    condition, body = _extract_loop_condition_body(node, source, diagnostics)
    return UntilLoop(condition=condition, body=body, span=_span(node))


def _extract_loop_condition_body(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> tuple[ASTNode, ASTNode]:
    """Extract condition and body from while/until via field names."""
    empty_cmd: ASTNode = SimpleCommand(
        words=(), assignments=(), redirections=(), span=_span(node)
    )
    condition: ASTNode = empty_cmd
    body: ASTNode = Sequence(commands=(), span=_span(node))

    cond_node = node.child_by_field_name("condition")
    body_node = node.child_by_field_name("body")

    if cond_node:
        # Try to normalize the condition node directly first
        try:
            result = _normalize_node(cond_node, source, diagnostics)
            condition = result if result is not None else empty_cmd
        except UnsupportedSyntaxError:
            # Fall back to normalizing its children
            cond_children = _normalize_children(cond_node, source, diagnostics)
            if cond_children:
                condition = _as_body(cond_children, _span(cond_node))

    if body_node:
        body_children = _normalize_children(body_node, source, diagnostics)
        if body_children:
            body = _as_body(body_children, _span(body_node))

    return condition, body


def _normalize_c_style_for(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> CStyleForLoop:
    """Normalize a C-style for loop: for (( init; cond; update )); do body; done."""
    text = _node_text(node, source)
    # Extract the (( ... )) part
    paren_start = text.find("((")
    paren_end = text.find("))")
    if paren_start >= 0 and paren_end > paren_start:
        inner = text[paren_start + 2 : paren_end].strip()
        parts = inner.split(";")
        init = parts[0].strip() if len(parts) > 0 else ""
        condition = parts[1].strip() if len(parts) > 1 else ""
        update = parts[2].strip() if len(parts) > 2 else ""
    else:
        init, condition, update = "", "", ""

    body: ASTNode = Sequence(commands=(), span=_span(node))
    body_node = node.child_by_field_name("body")
    if body_node:
        body_children = _normalize_children(body_node, source, diagnostics)
        if body_children:
            body = _as_body(body_children, _span(body_node))

    return CStyleForLoop(
        init=init, condition=condition, update=update, body=body, span=_span(node)
    )


def _normalize_case_statement(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> CaseClause:
    """Normalize a case statement into a CaseClause AST node."""
    word_node = node.child_by_field_name("value")
    word = (
        _normalize_word_node(word_node, source)
        if word_node
        else Word(
            segments=(LiteralSegment(value=""),),
            span=_span(node),
        )
    )

    items: list[CaseItem] = []
    for child in node.children:
        if child.type == "case_item":
            patterns: list[Word] = []
            body_parts: list[ASTNode] = []
            in_body = False
            for item_child in child.children:
                if not item_child.is_named:
                    text = _node_text(item_child, source)
                    if text == ")":
                        in_body = True
                    continue
                if not in_body:
                    # Pattern: word, extglob_pattern, string, etc.
                    patterns.append(_normalize_word_node(item_child, source))
                else:
                    _try_normalize_node(item_child, source, diagnostics, body_parts)
            item_body: ASTNode | None = (
                _as_body(body_parts, _span(child)) if body_parts else None
            )
            items.append(
                CaseItem(
                    patterns=tuple(patterns),
                    body=item_body,
                    span=_span(child),
                )
            )

    return CaseClause(word=word, items=tuple(items), span=_span(node))


# Node type -> handler mapping
def _normalize_test_command(
    node: Node, source: str, diagnostics: list[Diagnostic]
) -> SimpleCommand | ExtendedTest:
    """Normalize a test_command ([ ... ], test ..., or [[ ... ]]) into AST."""
    # Detect [[ ... ]] extended test
    text = _node_text(node, source)
    if text.startswith("[["):
        words: list[Word] = []
        _flatten_test_children(node, source, words, extended=True)
        return ExtendedTest(words=tuple(words), span=_span(node))

    words = []
    _flatten_test_children(node, source, words)
    return SimpleCommand(
        words=tuple(words),
        assignments=(),
        redirections=(),
        span=_span(node),
    )


def _flatten_test_children(
    node: Node, source: str, words: list[Word], *, extended: bool = False
) -> None:
    """Recursively flatten test_command children into a word list.

    When *extended* is ``True`` (``[[ ... ]]``):
    - Only ``[[`` / ``]]`` are treated as bracket tokens.
    - ``parenthesized_expression`` children are recursed into.
    - ``(`` and ``)`` are preserved in unnamed children.

    When *extended* is ``False`` (``[ ... ]``):
    - ``[``, ``]``, ``[[``, and ``]]`` are all treated as bracket tokens.
    - ``parenthesized_expression`` is not recursed.
    - ``(`` and ``)`` are filtered out from unnamed children.
    """
    bracket_types = ("[[", "]]") if extended else ("[", "]", "[[", "]]")
    recurse_types: tuple[str, ...] = (
        ("unary_expression", "binary_expression", "parenthesized_expression")
        if extended
        else ("unary_expression", "binary_expression")
    )
    unnamed_exclude = ("", " ") if extended else ("", " ", "(", ")")

    for child in node.children:
        ctype = child.type
        text = _node_text(child, source)

        if ctype in bracket_types or ctype == "test_operator":
            words.append(
                Word(
                    segments=(LiteralSegment(value=text),),
                    span=_span(child),
                )
            )
        elif ctype in recurse_types:
            _flatten_test_children(child, source, words, extended=extended)
        elif ctype in ("number", "regex"):
            words.append(
                Word(
                    segments=(LiteralSegment(value=text),),
                    span=_span(child),
                )
            )
        elif child.is_named:
            words.append(_normalize_word_node(child, source))
        elif text not in unnamed_exclude:
            words.append(
                Word(
                    segments=(LiteralSegment(value=text),),
                    span=_span(child),
                )
            )


_NODE_HANDLERS: dict[str, Callable[..., Any]] = {
    "program": _normalize_program,
    "command": _normalize_command,
    "simple_command": _normalize_simple_command,
    "pipeline": _normalize_pipeline,
    "list": _normalize_list,
    "subshell": _normalize_subshell,
    "compound_statement": _normalize_group,
    "function_definition": _normalize_function_def,
    "negated_command": _normalize_negated_command,
    "redirected_statement": _normalize_redirected_statement,
    "variable_assignment": _normalize_standalone_assignment,
    "declaration_command": _normalize_declaration_command,
    "unset_command": _normalize_unset_command,
    "variable_assignments": _normalize_variable_assignments,
    "if_statement": _normalize_if_statement,
    "for_statement": _normalize_for_statement,
    "while_statement": _normalize_while_statement,
    "until_statement": _normalize_until_statement,
    "c_style_for_statement": _normalize_c_style_for,
    "case_statement": _normalize_case_statement,
    "test_command": _normalize_test_command,
    "do_group": _normalize_list,
}

# Types we silently skip
_IGNORED_TYPES: set[str] = {
    "comment",
    "\n",
}
