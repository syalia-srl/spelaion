"""Tests for agentsh.ast — node construction, span preservation, and composition."""

from __future__ import annotations

import pytest

from agentsh.ast import (
    AndOrList,
    ArithmeticExpansionSegment,
    AssignmentWord,
    CaseClause,
    CaseItem,
    CommandSubstitutionSegment,
    DoubleQuotedSegment,
    ForLoop,
    FunctionDef,
    GlobSegment,
    Group,
    IfClause,
    LiteralSegment,
    ParameterExpansionSegment,
    Pipeline,
    Point,
    Program,
    Redirection,
    Sequence,
    SimpleCommand,
    SingleQuotedSegment,
    Span,
    Subshell,
    UntilLoop,
    WhileLoop,
    Word,
)
from agentsh.ast.nodes import ASTNode

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _span(start_byte: int = 0, end_byte: int = 10) -> Span:
    """Create a simple span for testing."""
    return Span(
        start_byte=start_byte,
        end_byte=end_byte,
        start_point=Point(0, start_byte),
        end_point=Point(0, end_byte),
    )


def _word(text: str, span: Span | None = None) -> Word:
    """Shorthand: create a Word with a single LiteralSegment."""
    return Word(
        segments=(LiteralSegment(text),),
        span=span or _span(),
    )


# ===================================================================
# Span / Point
# ===================================================================


class TestSpan:
    def test_point_fields(self) -> None:
        p = Point(3, 7)
        assert p.row == 3
        assert p.column == 7

    def test_point_str(self) -> None:
        assert str(Point(1, 4)) == "1:4"

    def test_span_fields(self) -> None:
        s = _span(5, 15)
        assert s.start_byte == 5
        assert s.end_byte == 15
        assert s.start_point == Point(0, 5)
        assert s.end_point == Point(0, 15)

    def test_span_length(self) -> None:
        assert _span(5, 15).length == 10

    def test_span_unknown(self) -> None:
        s = Span.unknown()
        assert s.start_byte == 0
        assert s.end_byte == 0
        assert s.start_point == Point(0, 0)
        assert s.end_point == Point(0, 0)

    def test_span_str(self) -> None:
        s = _span(0, 5)
        assert str(s) == "[0:0..0:5]"

    def test_span_is_frozen(self) -> None:
        s = _span()
        with pytest.raises(AttributeError):
            s.start_byte = 99  # type: ignore[misc]

    def test_point_is_frozen(self) -> None:
        p = Point(0, 0)
        with pytest.raises(AttributeError):
            p.row = 5  # type: ignore[misc]


# ===================================================================
# Word segments
# ===================================================================


class TestWordSegments:
    def test_literal_segment(self) -> None:
        seg = LiteralSegment("hello")
        assert seg.value == "hello"

    def test_single_quoted_segment(self) -> None:
        seg = SingleQuotedSegment("don't expand $this")
        assert seg.value == "don't expand $this"

    def test_double_quoted_segment_with_nested_expansion(self) -> None:
        inner = ParameterExpansionSegment(name="USER")
        seg = DoubleQuotedSegment(
            segments=(LiteralSegment("hello "), inner, LiteralSegment("!"))
        )
        assert len(seg.segments) == 3
        assert isinstance(seg.segments[1], ParameterExpansionSegment)

    def test_parameter_expansion_simple(self) -> None:
        seg = ParameterExpansionSegment(name="HOME")
        assert seg.name == "HOME"
        assert seg.operator is None
        assert seg.argument is None

    def test_parameter_expansion_with_default(self) -> None:
        seg = ParameterExpansionSegment(name="X", operator=":-", argument="fallback")
        assert seg.operator == ":-"
        assert seg.argument == "fallback"

    def test_parameter_expansion_hash(self) -> None:
        seg = ParameterExpansionSegment(name="PATH", operator="#", argument="*/")
        assert seg.operator == "#"
        assert seg.argument == "*/"

    def test_command_substitution(self) -> None:
        seg = CommandSubstitutionSegment(command="date +%Y")
        assert seg.command == "date +%Y"

    def test_arithmetic_expansion(self) -> None:
        seg = ArithmeticExpansionSegment(expression="x + 1")
        assert seg.expression == "x + 1"

    def test_glob_segment(self) -> None:
        seg = GlobSegment(pattern="*.py")
        assert seg.pattern == "*.py"

    def test_segments_are_frozen(self) -> None:
        seg = LiteralSegment("x")
        with pytest.raises(AttributeError):
            seg.value = "y"  # type: ignore[misc]


# ===================================================================
# Word
# ===================================================================


class TestWord:
    def test_word_with_single_literal(self) -> None:
        w = _word("echo")
        assert len(w.segments) == 1
        assert isinstance(w.segments[0], LiteralSegment)
        assert w.segments[0].value == "echo"

    def test_word_with_mixed_segments(self) -> None:
        span = _span()
        w = Word(
            segments=(
                LiteralSegment("file_"),
                ParameterExpansionSegment(name="N"),
                LiteralSegment(".txt"),
            ),
            span=span,
        )
        assert len(w.segments) == 3
        assert w.span is span

    def test_word_span_preserved(self) -> None:
        span = _span(10, 20)
        w = _word("abc", span=span)
        assert w.span.start_byte == 10
        assert w.span.end_byte == 20


# ===================================================================
# Redirection and AssignmentWord
# ===================================================================


class TestRedirection:
    def test_output_redirect(self) -> None:
        r = Redirection(op=">", fd=None, target=_word("/tmp/out"), span=_span())
        assert r.op == ">"
        assert r.fd is None

    def test_redirect_with_explicit_fd(self) -> None:
        r = Redirection(op=">&", fd=2, target=_word("1"), span=_span())
        assert r.fd == 2

    def test_append_redirect(self) -> None:
        r = Redirection(op=">>", fd=1, target=_word("log.txt"), span=_span())
        assert r.op == ">>"
        assert r.fd == 1


class TestAssignmentWord:
    def test_simple_assignment(self) -> None:
        a = AssignmentWord(name="X", value=_word("42"), span=_span())
        assert a.name == "X"
        assert a.value is not None
        assert a.value.segments[0].value == "42"  # type: ignore[union-attr]

    def test_empty_assignment(self) -> None:
        a = AssignmentWord(name="EMPTY", value=None, span=_span())
        assert a.value is None


# ===================================================================
# SimpleCommand
# ===================================================================


class TestSimpleCommand:
    def test_basic_command(self) -> None:
        cmd = SimpleCommand(
            words=(_word("echo"), _word("hello")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        assert len(cmd.words) == 2
        assert len(cmd.assignments) == 0
        assert len(cmd.redirections) == 0

    def test_command_with_assignment_and_redirect(self) -> None:
        assign = AssignmentWord(name="LC", value=_word("C"), span=_span())
        redir = Redirection(op=">", fd=None, target=_word("/dev/null"), span=_span())
        cmd = SimpleCommand(
            words=(_word("sort"),),
            assignments=(assign,),
            redirections=(redir,),
            span=_span(),
        )
        assert len(cmd.assignments) == 1
        assert len(cmd.redirections) == 1
        assert cmd.assignments[0].name == "LC"

    def test_satisfies_ast_node_protocol(self) -> None:
        cmd = SimpleCommand(words=(), assignments=(), redirections=(), span=_span())
        assert isinstance(cmd, ASTNode)


# ===================================================================
# Pipeline
# ===================================================================


class TestPipeline:
    def test_simple_pipeline(self) -> None:
        cmd1 = SimpleCommand(
            words=(_word("ls"),), assignments=(), redirections=(), span=_span()
        )
        cmd2 = SimpleCommand(
            words=(_word("grep"), _word("foo")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        pipe = Pipeline(commands=(cmd1, cmd2), negated=False, span=_span())
        assert len(pipe.commands) == 2
        assert pipe.negated is False

    def test_negated_pipeline(self) -> None:
        cmd = SimpleCommand(
            words=(_word("false"),), assignments=(), redirections=(), span=_span()
        )
        pipe = Pipeline(commands=(cmd,), negated=True, span=_span())
        assert pipe.negated is True

    def test_satisfies_ast_node_protocol(self) -> None:
        pipe = Pipeline(commands=(), negated=False, span=_span())
        assert isinstance(pipe, ASTNode)


# ===================================================================
# AndOrList
# ===================================================================


class TestAndOrList:
    def test_and_then_or(self) -> None:
        cmds = tuple(
            SimpleCommand(
                words=(_word(name),), assignments=(), redirections=(), span=_span()
            )
            for name in ("a", "b", "c")
        )
        aol = AndOrList(operators=("&&", "||"), commands=cmds, span=_span())
        assert len(aol.operators) == 2
        assert len(aol.commands) == 3
        assert aol.operators[0] == "&&"
        assert aol.operators[1] == "||"


# ===================================================================
# Sequence
# ===================================================================


class TestSequence:
    def test_sequence_of_commands(self) -> None:
        cmds = tuple(
            SimpleCommand(
                words=(_word(n),), assignments=(), redirections=(), span=_span()
            )
            for n in ("a", "b")
        )
        seq = Sequence(commands=cmds, span=_span())
        assert len(seq.commands) == 2


# ===================================================================
# Program
# ===================================================================


class TestProgram:
    def test_empty_program(self) -> None:
        prog = Program(body=(), span=_span())
        assert len(prog.body) == 0

    def test_program_with_pipeline(self) -> None:
        cmd = SimpleCommand(
            words=(_word("ls"),), assignments=(), redirections=(), span=_span()
        )
        pipe = Pipeline(commands=(cmd,), negated=False, span=_span())
        prog = Program(body=(pipe,), span=_span(0, 2))
        assert len(prog.body) == 1
        assert isinstance(prog.body[0], Pipeline)

    def test_program_span_preserved(self) -> None:
        span = Span(0, 100, Point(0, 0), Point(5, 0))
        prog = Program(body=(), span=span)
        assert prog.span.end_byte == 100
        assert prog.span.end_point.row == 5

    def test_program_with_sequence_and_pipelines(self) -> None:
        """Integration: Program -> Sequence -> Pipeline -> SimpleCommand."""
        echo = SimpleCommand(
            words=(_word("echo"), _word("hi")),
            assignments=(),
            redirections=(),
            span=_span(0, 7),
        )
        grep = SimpleCommand(
            words=(_word("grep"), _word("h")),
            assignments=(),
            redirections=(),
            span=_span(10, 16),
        )
        pipe = Pipeline(commands=(echo, grep), negated=False, span=_span(0, 16))
        ls = SimpleCommand(
            words=(_word("ls"),),
            assignments=(),
            redirections=(),
            span=_span(18, 20),
        )
        seq = Sequence(commands=(pipe, ls), span=_span(0, 20))
        prog = Program(body=(seq,), span=_span(0, 20))

        assert len(prog.body) == 1
        assert isinstance(prog.body[0], Sequence)
        seq_node = prog.body[0]
        assert isinstance(seq_node, Sequence)
        assert isinstance(seq_node.commands[0], Pipeline)
        pipeline_node = seq_node.commands[0]
        assert isinstance(pipeline_node, Pipeline)
        assert len(pipeline_node.commands) == 2

    def test_satisfies_ast_node_protocol(self) -> None:
        prog = Program(body=(), span=_span())
        assert isinstance(prog, ASTNode)


# ===================================================================
# Group / Subshell
# ===================================================================


class TestGroup:
    def test_group_wraps_body(self) -> None:
        inner = SimpleCommand(
            words=(_word("true"),), assignments=(), redirections=(), span=_span()
        )
        g = Group(body=inner, span=_span())
        assert isinstance(g.body, SimpleCommand)

    def test_satisfies_ast_node_protocol(self) -> None:
        inner = SimpleCommand(words=(), assignments=(), redirections=(), span=_span())
        assert isinstance(Group(body=inner, span=_span()), ASTNode)


class TestSubshell:
    def test_subshell_wraps_body(self) -> None:
        inner = SimpleCommand(
            words=(_word("pwd"),), assignments=(), redirections=(), span=_span()
        )
        s = Subshell(body=inner, span=_span())
        assert isinstance(s.body, SimpleCommand)


# ===================================================================
# FunctionDef
# ===================================================================


class TestFunctionDef:
    def test_function_definition(self) -> None:
        body = Group(
            body=SimpleCommand(
                words=(_word("echo"), _word("hi")),
                assignments=(),
                redirections=(),
                span=_span(),
            ),
            span=_span(),
        )
        fn = FunctionDef(name="greet", body=body, span=_span())
        assert fn.name == "greet"
        assert isinstance(fn.body, Group)


# ===================================================================
# Control-flow nodes
# ===================================================================


class TestIfClause:
    def test_simple_if(self) -> None:
        cond = SimpleCommand(
            words=(_word("true"),), assignments=(), redirections=(), span=_span()
        )
        body = SimpleCommand(
            words=(_word("echo"), _word("yes")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = IfClause(
            conditions=(cond,), bodies=(body,), else_body=None, span=_span()
        )
        assert len(node.conditions) == 1
        assert node.else_body is None

    def test_if_else(self) -> None:
        cond = SimpleCommand(
            words=(_word("false"),), assignments=(), redirections=(), span=_span()
        )
        body = SimpleCommand(
            words=(_word("echo"), _word("no")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        else_body = SimpleCommand(
            words=(_word("echo"), _word("yes")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = IfClause(
            conditions=(cond,), bodies=(body,), else_body=else_body, span=_span()
        )
        assert node.else_body is not None


class TestWhileLoop:
    def test_while_loop(self) -> None:
        cond = SimpleCommand(
            words=(_word("true"),), assignments=(), redirections=(), span=_span()
        )
        body = SimpleCommand(
            words=(_word("sleep"), _word("1")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = WhileLoop(condition=cond, body=body, span=_span())
        assert isinstance(node.condition, SimpleCommand)
        assert isinstance(node.body, SimpleCommand)


class TestUntilLoop:
    def test_until_loop(self) -> None:
        cond = SimpleCommand(
            words=(_word("false"),), assignments=(), redirections=(), span=_span()
        )
        body = SimpleCommand(
            words=(_word("echo"), _word("waiting")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = UntilLoop(condition=cond, body=body, span=_span())
        assert isinstance(node.condition, SimpleCommand)


class TestForLoop:
    def test_for_loop_with_words(self) -> None:
        words = (_word("a"), _word("b"), _word("c"))
        body = SimpleCommand(
            words=(_word("echo"), _word("$i")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = ForLoop(variable="i", words=words, body=body, span=_span())
        assert node.variable == "i"
        assert node.words is not None
        assert len(node.words) == 3

    def test_for_loop_without_words(self) -> None:
        body = SimpleCommand(
            words=(_word("echo"), _word("$1")),
            assignments=(),
            redirections=(),
            span=_span(),
        )
        node = ForLoop(variable="arg", words=None, body=body, span=_span())
        assert node.words is None


class TestCaseClause:
    def test_case_clause(self) -> None:
        item1 = CaseItem(
            patterns=(_word("*.py"),),
            body=SimpleCommand(
                words=(_word("echo"), _word("python")),
                assignments=(),
                redirections=(),
                span=_span(),
            ),
            span=_span(),
        )
        item2 = CaseItem(
            patterns=(_word("*.sh"), _word("*.bash")),
            body=SimpleCommand(
                words=(_word("echo"), _word("shell")),
                assignments=(),
                redirections=(),
                span=_span(),
            ),
            span=_span(),
        )
        item_default = CaseItem(
            patterns=(_word("*"),),
            body=None,
            span=_span(),
        )
        node = CaseClause(
            word=_word("$file"), items=(item1, item2, item_default), span=_span()
        )
        assert len(node.items) == 3
        assert node.items[2].body is None

    def test_case_item_with_multiple_patterns(self) -> None:
        item = CaseItem(
            patterns=(_word("yes"), _word("y"), _word("Y")),
            body=SimpleCommand(
                words=(_word("echo"), _word("ok")),
                assignments=(),
                redirections=(),
                span=_span(),
            ),
            span=_span(),
        )
        assert len(item.patterns) == 3


# ===================================================================
# Immutability
# ===================================================================


class TestImmutability:
    """Verify that all node types are truly frozen."""

    def test_word_is_frozen(self) -> None:
        w = _word("x")
        with pytest.raises(AttributeError):
            w.span = _span()  # type: ignore[misc]

    def test_simple_command_is_frozen(self) -> None:
        cmd = SimpleCommand(words=(), assignments=(), redirections=(), span=_span())
        with pytest.raises(AttributeError):
            cmd.words = ()  # type: ignore[misc]

    def test_pipeline_is_frozen(self) -> None:
        pipe = Pipeline(commands=(), negated=False, span=_span())
        with pytest.raises(AttributeError):
            pipe.negated = True  # type: ignore[misc]

    def test_program_is_frozen(self) -> None:
        prog = Program(body=(), span=_span())
        with pytest.raises(AttributeError):
            prog.body = ()  # type: ignore[misc]

    def test_function_def_is_frozen(self) -> None:
        body = Group(
            body=SimpleCommand(words=(), assignments=(), redirections=(), span=_span()),
            span=_span(),
        )
        fn = FunctionDef(name="f", body=body, span=_span())
        with pytest.raises(AttributeError):
            fn.name = "g"  # type: ignore[misc]

    def test_if_clause_is_frozen(self) -> None:
        cond = SimpleCommand(words=(), assignments=(), redirections=(), span=_span())
        node = IfClause(
            conditions=(cond,), bodies=(cond,), else_body=None, span=_span()
        )
        with pytest.raises(AttributeError):
            node.else_body = cond  # type: ignore[misc]
