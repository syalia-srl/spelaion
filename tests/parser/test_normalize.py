"""Tests for CST → AST normalization."""

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
from agentsh.ast.words import (
    CommandSubstitutionSegment,
    DoubleQuotedSegment,
    LiteralSegment,
    ParameterExpansionSegment,
    SingleQuotedSegment,
)
from agentsh.parser.frontend import parse_script
from agentsh.parser.normalize import normalize


def _parse_and_normalize(script: str) -> Program:
    result = parse_script(script)
    program, _diags = normalize(result.root_node, script)
    return program


class TestNormalizeSimpleCommand:
    def test_simple_echo(self) -> None:
        prog = _parse_and_normalize("echo hello")
        assert len(prog.body) == 1
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        assert len(cmd.words) == 2

    def test_simple_command_words(self) -> None:
        prog = _parse_and_normalize("echo hello world")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        assert len(cmd.words) == 3

    def test_assignment(self) -> None:
        prog = _parse_and_normalize("FOO=bar")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        assert len(cmd.assignments) >= 1

    def test_assignment_with_command(self) -> None:
        prog = _parse_and_normalize("FOO=bar echo hello")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        assert len(cmd.assignments) == 1
        assert cmd.assignments[0].name == "FOO"
        assert len(cmd.words) == 2


class TestNormalizePipeline:
    def test_simple_pipeline(self) -> None:
        prog = _parse_and_normalize("echo hello | cat")
        assert len(prog.body) == 1
        pipe = prog.body[0]
        assert isinstance(pipe, Pipeline)
        assert len(pipe.commands) == 2

    def test_three_stage_pipeline(self) -> None:
        prog = _parse_and_normalize("echo hello | grep h | cat")
        pipe = prog.body[0]
        assert isinstance(pipe, Pipeline)
        assert len(pipe.commands) == 3


class TestNormalizeAndOr:
    def test_and_list(self) -> None:
        prog = _parse_and_normalize("true && echo ok")
        node = prog.body[0]
        assert isinstance(node, AndOrList)
        assert node.operators == ("&&",)
        assert len(node.commands) == 2

    def test_or_list(self) -> None:
        prog = _parse_and_normalize("false || echo fallback")
        node = prog.body[0]
        assert isinstance(node, AndOrList)
        assert node.operators == ("||",)


class TestNormalizeCompound:
    def test_subshell(self) -> None:
        prog = _parse_and_normalize("(echo hello)")
        node = prog.body[0]
        assert isinstance(node, Subshell)

    def test_group(self) -> None:
        prog = _parse_and_normalize("{ echo hello; }")
        node = prog.body[0]
        assert isinstance(node, Group)

    def test_function_def(self) -> None:
        prog = _parse_and_normalize("greet() { echo hello; }")
        node = prog.body[0]
        assert isinstance(node, FunctionDef)
        assert node.name == "greet"


class TestNormalizeSequence:
    def test_semicolons(self) -> None:
        prog = _parse_and_normalize("echo a; echo b")
        # Should have 2 commands in body or be a Sequence
        assert len(prog.body) >= 2 or isinstance(prog.body[0], Sequence)


class TestNormalizeWords:
    def test_literal_word(self) -> None:
        prog = _parse_and_normalize("echo hello")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        word = cmd.words[1]
        assert len(word.segments) == 1
        assert isinstance(word.segments[0], LiteralSegment)
        assert word.segments[0].value == "hello"

    def test_single_quoted(self) -> None:
        prog = _parse_and_normalize("echo 'hello world'")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        word = cmd.words[1]
        assert any(isinstance(s, SingleQuotedSegment) for s in word.segments)

    def test_double_quoted_with_var(self) -> None:
        prog = _parse_and_normalize('echo "hello $NAME"')
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        word = cmd.words[1]
        # Should contain a DoubleQuotedSegment with inner segments
        dq = word.segments[0]
        assert isinstance(dq, DoubleQuotedSegment)
        # Inner segments should include a parameter expansion
        has_param = any(isinstance(s, ParameterExpansionSegment) for s in dq.segments)
        assert has_param

    def test_command_substitution(self) -> None:
        prog = _parse_and_normalize("echo $(pwd)")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        word = cmd.words[1]
        assert any(isinstance(s, CommandSubstitutionSegment) for s in word.segments)

    def test_parameter_expansion(self) -> None:
        prog = _parse_and_normalize("echo $HOME")
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        word = cmd.words[1]
        assert any(isinstance(s, ParameterExpansionSegment) for s in word.segments)


class TestNormalizeRedirection:
    def test_output_redirect(self) -> None:
        prog = _parse_and_normalize("echo hello > out.txt")
        # The command should have redirections
        cmd = prog.body[0]
        assert isinstance(cmd, SimpleCommand)
        assert len(cmd.redirections) >= 1

    def test_spans_preserved(self) -> None:
        prog = _parse_and_normalize("echo hello")
        assert prog.span.start_byte == 0
        assert prog.span.end_byte == 10
