"""Tests for the tree-sitter parser frontend."""

from agentsh.parser.frontend import parse_script


class TestParseScript:
    def test_simple_command(self) -> None:
        result = parse_script("echo hello")
        assert not result.has_errors
        assert result.root_node.type == "program"

    def test_quoted_arguments(self) -> None:
        result = parse_script('echo "hello world"')
        assert not result.has_errors

    def test_single_quoted(self) -> None:
        result = parse_script("echo 'hello world'")
        assert not result.has_errors

    def test_pipeline(self) -> None:
        result = parse_script("echo hello | cat")
        assert not result.has_errors

    def test_and_list(self) -> None:
        result = parse_script("true && echo ok")
        assert not result.has_errors

    def test_or_list(self) -> None:
        result = parse_script("false || echo fallback")
        assert not result.has_errors

    def test_subshell(self) -> None:
        result = parse_script("(echo hello)")
        assert not result.has_errors

    def test_group(self) -> None:
        result = parse_script("{ echo hello; }")
        assert not result.has_errors

    def test_assignment(self) -> None:
        result = parse_script("FOO=bar echo $FOO")
        assert not result.has_errors

    def test_variable_expansion(self) -> None:
        result = parse_script('echo "$HOME"')
        assert not result.has_errors

    def test_command_substitution(self) -> None:
        result = parse_script("echo $(pwd)")
        assert not result.has_errors

    def test_redirection(self) -> None:
        result = parse_script("echo hello > output.txt")
        assert not result.has_errors

    def test_malformed_syntax_has_diagnostics(self) -> None:
        result = parse_script("echo (")
        assert result.has_errors
        assert len(result.diagnostics) > 0

    def test_sequence(self) -> None:
        result = parse_script("echo a; echo b")
        assert not result.has_errors

    def test_function_definition(self) -> None:
        result = parse_script("greet() { echo hello; }")
        assert not result.has_errors

    def test_source_span_present(self) -> None:
        result = parse_script("echo hello")
        assert result.root_node.start_byte == 0
        assert result.root_node.end_byte == 10

    def test_empty_script(self) -> None:
        result = parse_script("")
        assert not result.has_errors

    def test_multiline_script(self) -> None:
        result = parse_script("echo hello\necho world\n")
        assert not result.has_errors
