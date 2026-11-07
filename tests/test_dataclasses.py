"""Comprehensive tests for all small dataclass/enum modules.

Covers:
- runtime.result: CommandResult, ShellError
- runtime.options: ShellOptions
- runtime.events: ExecutionEvent, EventKind
- parser.diagnostics: Diagnostic, DiagnosticSeverity, UnsupportedSyntaxError
- ast.spans: Point, Span
- ast.words: all WordSegment types
"""

from __future__ import annotations

import dataclasses

import pytest

from agentsh.ast.spans import Point, Span
from agentsh.ast.words import (
    ArithmeticExpansionSegment,
    CommandSubstitutionSegment,
    DoubleQuotedSegment,
    GlobSegment,
    LiteralSegment,
    ParameterExpansionSegment,
    SingleQuotedSegment,
)
from agentsh.parser.diagnostics import (
    Diagnostic,
    DiagnosticSeverity,
    UnsupportedSyntaxError,
)
from agentsh.runtime.events import EventKind, ExecutionEvent
from agentsh.runtime.options import ShellOptions
from agentsh.runtime.result import CommandResult, ShellError

# ── Point ────────────────────────────────────────────────────────────────


class TestPoint:
    def test_construction(self) -> None:
        p = Point(row=3, column=7)
        assert p.row == 3
        assert p.column == 7

    def test_str_format(self) -> None:
        assert str(Point(0, 0)) == "0:0"
        assert str(Point(10, 42)) == "10:42"

    def test_frozen(self) -> None:
        p = Point(1, 2)
        with pytest.raises(dataclasses.FrozenInstanceError):
            p.row = 5  # type: ignore[misc]

    def test_equality(self) -> None:
        assert Point(1, 2) == Point(1, 2)
        assert Point(1, 2) != Point(1, 3)


# ── Span ─────────────────────────────────────────────────────────────────


class TestSpan:
    def test_construction(self) -> None:
        s = Span(
            start_byte=0,
            end_byte=10,
            start_point=Point(0, 0),
            end_point=Point(0, 10),
        )
        assert s.start_byte == 0
        assert s.end_byte == 10
        assert s.start_point == Point(0, 0)
        assert s.end_point == Point(0, 10)

    def test_length_property(self) -> None:
        s = Span(5, 15, Point(0, 5), Point(0, 15))
        assert s.length == 10

    def test_length_zero(self) -> None:
        s = Span(5, 5, Point(0, 5), Point(0, 5))
        assert s.length == 0

    def test_unknown_sentinel(self) -> None:
        s = Span.unknown()
        assert s.start_byte == 0
        assert s.end_byte == 0
        assert s.start_point == Point(0, 0)
        assert s.end_point == Point(0, 0)
        assert s.length == 0

    def test_str_format(self) -> None:
        s = Span(0, 10, Point(1, 2), Point(1, 12))
        assert str(s) == "[1:2..1:12]"

    def test_frozen(self) -> None:
        s = Span.unknown()
        with pytest.raises(dataclasses.FrozenInstanceError):
            s.start_byte = 99  # type: ignore[misc]

    def test_equality(self) -> None:
        a = Span(0, 5, Point(0, 0), Point(0, 5))
        b = Span(0, 5, Point(0, 0), Point(0, 5))
        c = Span(0, 6, Point(0, 0), Point(0, 6))
        assert a == b
        assert a != c


# ── CommandResult ────────────────────────────────────────────────────────


class TestCommandResult:
    def test_default_construction(self) -> None:
        r = CommandResult()
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.error is None

    def test_success_factory(self) -> None:
        r = CommandResult.success()
        assert r.exit_code == 0
        assert r.stdout == ""
        assert r.stderr == ""

    def test_success_with_stdout(self) -> None:
        r = CommandResult.success(stdout="hello")
        assert r.exit_code == 0
        assert r.stdout == "hello"

    def test_fail_factory_defaults(self) -> None:
        r = CommandResult.fail()
        assert r.exit_code == 1
        assert r.stderr == ""
        assert r.error is None

    def test_fail_with_values(self) -> None:
        err = ShellError(message="oops")
        r = CommandResult.fail(exit_code=2, stderr="msg", error=err)
        assert r.exit_code == 2
        assert r.stderr == "msg"
        assert r.error is err
        assert r.error.message == "oops"

    def test_mutable(self) -> None:
        r = CommandResult()
        r.exit_code = 42
        assert r.exit_code == 42


# ── ShellError ───────────────────────────────────────────────────────────


class TestShellError:
    def test_construction_with_message(self) -> None:
        e = ShellError(message="file not found")
        assert e.message == "file not found"
        assert e.span is None
        assert e.command == ""
        assert e.exit_code == 1

    def test_construction_with_span_and_command(self) -> None:
        span = Span(0, 5, Point(0, 0), Point(0, 5))
        e = ShellError(message="bad", span=span, command="rm")
        assert e.span == span
        assert e.command == "rm"

    def test_custom_exit_code(self) -> None:
        e = ShellError(message="not found", exit_code=127)
        assert e.exit_code == 127

    def test_frozen(self) -> None:
        e = ShellError(message="error")
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.message = "changed"  # type: ignore[misc]


# ── ShellOptions ─────────────────────────────────────────────────────────


class TestShellOptions:
    def test_default_values(self) -> None:
        opts = ShellOptions()
        assert opts.errexit is False
        assert opts.nounset is False
        assert opts.pipefail is False
        assert opts.xtrace is False
        assert opts.noglob is False

    def test_setting_individual_options(self) -> None:
        opts = ShellOptions()
        opts.errexit = True
        assert opts.errexit is True
        # others remain unchanged
        assert opts.nounset is False

    def test_construction_with_values(self) -> None:
        opts = ShellOptions(errexit=True, pipefail=True)
        assert opts.errexit is True
        assert opts.pipefail is True
        assert opts.nounset is False

    def test_mutable(self) -> None:
        opts = ShellOptions()
        opts.noglob = True
        opts.xtrace = True
        assert opts.noglob is True
        assert opts.xtrace is True


# ── EventKind ────────────────────────────────────────────────────────────


class TestEventKind:
    @pytest.mark.parametrize(
        "member,value",
        [
            ("PARSE", "parse"),
            ("NORMALIZE", "normalize"),
            ("EXPAND", "expand"),
            ("RESOLVE", "resolve"),
            ("PLAN", "plan"),
            ("EXECUTE", "execute"),
            ("BUILTIN", "builtin"),
            ("TOOL_DISPATCH", "tool_dispatch"),
            ("REDIRECT", "redirect"),
            ("POLICY", "policy"),
        ],
    )
    def test_members_exist(self, member: str, value: str) -> None:
        kind = EventKind[member]
        assert kind.value == value

    def test_total_member_count(self) -> None:
        assert len(EventKind) == 10


# ── ExecutionEvent ───────────────────────────────────────────────────────


class TestExecutionEvent:
    def test_construction_with_kind_and_message(self) -> None:
        ev = ExecutionEvent(kind=EventKind.PARSE, message="parsed ok")
        assert ev.kind is EventKind.PARSE
        assert ev.message == "parsed ok"
        assert ev.data is None

    def test_construction_with_data(self) -> None:
        ev = ExecutionEvent(
            kind=EventKind.EXECUTE,
            message="ran command",
            data={"cmd": "echo", "args": ["hello"]},
        )
        assert ev.data is not None
        assert ev.data["cmd"] == "echo"
        assert ev.data["args"] == ["hello"]

    def test_mutable(self) -> None:
        ev = ExecutionEvent(kind=EventKind.PLAN, message="initial")
        ev.message = "updated"
        assert ev.message == "updated"


# ── DiagnosticSeverity ───────────────────────────────────────────────────


class TestDiagnosticSeverity:
    @pytest.mark.parametrize(
        "member,value",
        [
            ("ERROR", "error"),
            ("WARNING", "warning"),
            ("INFO", "info"),
        ],
    )
    def test_members(self, member: str, value: str) -> None:
        assert DiagnosticSeverity[member].value == value

    def test_total_member_count(self) -> None:
        assert len(DiagnosticSeverity) == 3


# ── Diagnostic ───────────────────────────────────────────────────────────


class TestDiagnostic:
    def test_construction(self) -> None:
        span = Span(0, 5, Point(0, 0), Point(0, 5))
        d = Diagnostic(
            severity=DiagnosticSeverity.ERROR,
            message="unexpected token",
            span=span,
        )
        assert d.severity is DiagnosticSeverity.ERROR
        assert d.message == "unexpected token"
        assert d.span is span

    def test_str_format(self) -> None:
        span = Span(0, 5, Point(2, 4), Point(2, 9))
        d = Diagnostic(DiagnosticSeverity.WARNING, "unused var", span)
        # row is 0-indexed, __str__ adds 1
        assert str(d) == "warning: unused var at 3:4"

    def test_str_format_first_line(self) -> None:
        span = Span(0, 3, Point(0, 0), Point(0, 3))
        d = Diagnostic(DiagnosticSeverity.ERROR, "syntax error", span)
        assert str(d) == "error: syntax error at 1:0"

    def test_frozen(self) -> None:
        span = Span.unknown()
        d = Diagnostic(DiagnosticSeverity.INFO, "note", span)
        with pytest.raises(dataclasses.FrozenInstanceError):
            d.message = "other"  # type: ignore[misc]


# ── UnsupportedSyntaxError ───────────────────────────────────────────────


class TestUnsupportedSyntaxError:
    def test_is_exception(self) -> None:
        err = UnsupportedSyntaxError("coproc not supported", node_type="coproc")
        assert isinstance(err, Exception)

    def test_message(self) -> None:
        err = UnsupportedSyntaxError("bad syntax")
        assert str(err) == "bad syntax"

    def test_node_type_attribute(self) -> None:
        err = UnsupportedSyntaxError("nope", node_type="process_substitution")
        assert err.node_type == "process_substitution"

    def test_default_node_type(self) -> None:
        err = UnsupportedSyntaxError("unknown")
        assert err.node_type == ""

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(UnsupportedSyntaxError, match="heredoc"):
            raise UnsupportedSyntaxError("heredoc not supported", node_type="heredoc")


# ── Word segments ────────────────────────────────────────────────────────


class TestLiteralSegment:
    def test_construction(self) -> None:
        seg = LiteralSegment(value="hello")
        assert seg.value == "hello"

    def test_empty_value(self) -> None:
        seg = LiteralSegment(value="")
        assert seg.value == ""

    def test_frozen(self) -> None:
        seg = LiteralSegment(value="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.value = "y"  # type: ignore[misc]

    def test_equality(self) -> None:
        assert LiteralSegment("a") == LiteralSegment("a")
        assert LiteralSegment("a") != LiteralSegment("b")


class TestSingleQuotedSegment:
    def test_construction(self) -> None:
        seg = SingleQuotedSegment(value="hello world")
        assert seg.value == "hello world"

    def test_preserves_special_chars(self) -> None:
        seg = SingleQuotedSegment(value="$HOME *.py")
        assert seg.value == "$HOME *.py"

    def test_frozen(self) -> None:
        seg = SingleQuotedSegment(value="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.value = "y"  # type: ignore[misc]


class TestParameterExpansionSegment:
    def test_simple_variable(self) -> None:
        seg = ParameterExpansionSegment(name="HOME")
        assert seg.name == "HOME"
        assert seg.operator is None
        assert seg.argument is None

    def test_with_operator_and_argument(self) -> None:
        seg = ParameterExpansionSegment(name="var", operator=":-", argument="default")
        assert seg.name == "var"
        assert seg.operator == ":-"
        assert seg.argument == "default"

    def test_length_operator(self) -> None:
        seg = ParameterExpansionSegment(name="name", operator="#")
        assert seg.operator == "#"
        assert seg.argument is None

    def test_suffix_removal(self) -> None:
        seg = ParameterExpansionSegment(name="file", operator="%%", argument=".tar.gz")
        assert seg.operator == "%%"
        assert seg.argument == ".tar.gz"

    def test_frozen(self) -> None:
        seg = ParameterExpansionSegment(name="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.name = "y"  # type: ignore[misc]


class TestCommandSubstitutionSegment:
    def test_construction(self) -> None:
        seg = CommandSubstitutionSegment(command="ls -la")
        assert seg.command == "ls -la"

    def test_frozen(self) -> None:
        seg = CommandSubstitutionSegment(command="echo hi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.command = "other"  # type: ignore[misc]

    def test_equality(self) -> None:
        assert CommandSubstitutionSegment("pwd") == CommandSubstitutionSegment("pwd")


class TestArithmeticExpansionSegment:
    def test_construction(self) -> None:
        seg = ArithmeticExpansionSegment(expression="x + 1")
        assert seg.expression == "x + 1"

    def test_frozen(self) -> None:
        seg = ArithmeticExpansionSegment(expression="1")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.expression = "2"  # type: ignore[misc]


class TestGlobSegment:
    def test_construction(self) -> None:
        seg = GlobSegment(pattern="*.py")
        assert seg.pattern == "*.py"

    def test_question_mark_glob(self) -> None:
        seg = GlobSegment(pattern="file?.txt")
        assert seg.pattern == "file?.txt"

    def test_bracket_glob(self) -> None:
        seg = GlobSegment(pattern="[abc]*.log")
        assert seg.pattern == "[abc]*.log"

    def test_frozen(self) -> None:
        seg = GlobSegment(pattern="*")
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.pattern = "?"  # type: ignore[misc]


class TestDoubleQuotedSegment:
    def test_construction_with_literal(self) -> None:
        inner = (LiteralSegment("hello"),)
        seg = DoubleQuotedSegment(segments=inner)
        assert len(seg.segments) == 1
        assert seg.segments[0] == LiteralSegment("hello")

    def test_nested_expansion(self) -> None:
        inner = (
            LiteralSegment("home is "),
            ParameterExpansionSegment(name="HOME"),
        )
        seg = DoubleQuotedSegment(segments=inner)
        assert len(seg.segments) == 2
        assert isinstance(seg.segments[0], LiteralSegment)
        assert isinstance(seg.segments[1], ParameterExpansionSegment)

    def test_nested_command_substitution(self) -> None:
        inner = (
            LiteralSegment("today is "),
            CommandSubstitutionSegment(command="date"),
        )
        seg = DoubleQuotedSegment(segments=inner)
        assert isinstance(seg.segments[1], CommandSubstitutionSegment)

    def test_nested_arithmetic(self) -> None:
        inner = (ArithmeticExpansionSegment(expression="2+2"),)
        seg = DoubleQuotedSegment(segments=inner)
        assert isinstance(seg.segments[0], ArithmeticExpansionSegment)

    def test_empty_segments(self) -> None:
        seg = DoubleQuotedSegment(segments=())
        assert seg.segments == ()

    def test_frozen(self) -> None:
        seg = DoubleQuotedSegment(segments=())
        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.segments = (LiteralSegment("x"),)  # type: ignore[misc]

    def test_equality(self) -> None:
        inner = (LiteralSegment("a"),)
        assert DoubleQuotedSegment(inner) == DoubleQuotedSegment(inner)
