"""Tests for the expansion engine."""

from agentsh.ast.nodes import Word
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
from agentsh.runtime.state import ShellState
from agentsh.semantics.expand import expand_word, expand_word_single
from agentsh.vfs.filesystem import VirtualFilesystem

_SPAN = Span(0, 0, Point(0, 0), Point(0, 0))


def _word(*segments: object) -> Word:
    return Word(segments=tuple(segments), span=_SPAN)  # type: ignore[arg-type]


def _state(**kwargs: str) -> ShellState:
    s = ShellState()
    for k, v in kwargs.items():
        s.set_var(k, v)
    return s


class TestLiteralExpansion:
    def test_simple_literal(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(LiteralSegment(value="hello"))
        result = expand_word(word, state, vfs)
        assert result == ["hello"]

    def test_empty_literal(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(LiteralSegment(value=""))
        result = expand_word(word, state, vfs)
        assert result == [""]


class TestTildeExpansion:
    def test_tilde_alone(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(HOME="/home/user")
        word = _word(LiteralSegment(value="~"))
        result = expand_word(word, state, vfs)
        assert result == ["/home/user"]

    def test_tilde_slash(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(HOME="/home/user")
        word = _word(LiteralSegment(value="~/docs"))
        result = expand_word(word, state, vfs)
        assert result == ["/home/user/docs"]


class TestParameterExpansion:
    def test_simple_var(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(NAME="world")
        word = _word(ParameterExpansionSegment(name="NAME"))
        result = expand_word(word, state, vfs)
        assert result == ["world"]

    def test_unset_var(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(ParameterExpansionSegment(name="MISSING"))
        result = expand_word(word, state, vfs)
        assert result == [""]

    def test_default_value(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(
            ParameterExpansionSegment(name="MISSING", operator=":-", argument="default")
        )
        result = expand_word(word, state, vfs)
        assert result == ["default"]

    def test_default_value_set(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(VAR="exists")
        word = _word(
            ParameterExpansionSegment(name="VAR", operator=":-", argument="default")
        )
        result = expand_word(word, state, vfs)
        assert result == ["exists"]

    def test_alternative_value(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(VAR="exists")
        word = _word(
            ParameterExpansionSegment(name="VAR", operator=":+", argument="alt")
        )
        result = expand_word(word, state, vfs)
        assert result == ["alt"]

    def test_special_param_question_mark(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        state.last_status = 42
        word = _word(ParameterExpansionSegment(name="?"))
        result = expand_word(word, state, vfs)
        assert result == ["42"]

    def test_special_param_hash(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        state.positional_params = ["a", "b", "c"]
        word = _word(ParameterExpansionSegment(name="#"))
        result = expand_word(word, state, vfs)
        assert result == ["3"]

    def test_positional_param(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        state.positional_params = ["first", "second"]
        word = _word(ParameterExpansionSegment(name="1"))
        result = expand_word(word, state, vfs)
        assert result == ["first"]


class TestSingleQuoted:
    def test_single_quoted_no_expansion(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(HOME="/home/user")
        word = _word(SingleQuotedSegment(value="$HOME"))
        result = expand_word(word, state, vfs)
        assert result == ["$HOME"]


class TestDoubleQuoted:
    def test_double_quoted_with_var(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(NAME="world")
        word = _word(
            DoubleQuotedSegment(
                segments=(
                    LiteralSegment(value="hello "),
                    ParameterExpansionSegment(name="NAME"),
                )
            )
        )
        result = expand_word(word, state, vfs)
        assert result == ["hello world"]

    def test_double_quoted_prevents_splitting(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(VAR="a b c")
        word = _word(
            DoubleQuotedSegment(segments=(ParameterExpansionSegment(name="VAR"),))
        )
        result = expand_word(word, state, vfs)
        # Should NOT split — stays as one field
        assert result == ["a b c"]


class TestWordSplitting:
    def test_unquoted_var_splits(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(VAR="a b c")
        word = _word(ParameterExpansionSegment(name="VAR"))
        result = expand_word(word, state, vfs)
        assert result == ["a", "b", "c"]


class TestCommandSubstitution:
    def test_with_hook(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()

        def hook(cmd: str) -> str:
            return "/home/user\n"

        word = _word(CommandSubstitutionSegment(command="pwd"))
        result = expand_word(word, state, vfs, cmdsub_hook=hook)
        assert result == ["/home/user"]

    def test_without_hook(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(CommandSubstitutionSegment(command="pwd"))
        result = expand_word(word, state, vfs)
        assert result == [""]


class TestGlobbing:
    def test_glob_matches(self) -> None:
        vfs = VirtualFilesystem(
            initial_files={
                "/test/a.txt": "a",
                "/test/b.txt": "b",
                "/test/c.py": "c",
            }
        )
        state = _state()
        state.cwd = "/test"
        word = _word(GlobSegment(pattern="*.txt"))
        result = expand_word(word, state, vfs)
        assert "/test/a.txt" in result
        assert "/test/b.txt" in result
        assert "/test/c.py" not in result

    def test_glob_no_match_keeps_literal(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(GlobSegment(pattern="*.xyz"))
        result = expand_word(word, state, vfs)
        assert result == ["*.xyz"]


class TestArithmetic:
    def test_simple_addition(self) -> None:
        vfs = VirtualFilesystem()
        state = _state()
        word = _word(ArithmeticExpansionSegment(expression="1 + 2"))
        result = expand_word(word, state, vfs)
        assert result == ["3"]

    def test_variable_reference(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(X="10")
        word = _word(ArithmeticExpansionSegment(expression="$X + 5"))
        result = expand_word(word, state, vfs)
        assert result == ["15"]


class TestExpandWordSingle:
    def test_no_splitting(self) -> None:
        vfs = VirtualFilesystem()
        state = _state(VAR="a b c")
        word = _word(ParameterExpansionSegment(name="VAR"))
        result = expand_word_single(word, state, vfs)
        assert result == "a b c"
