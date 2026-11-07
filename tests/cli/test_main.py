"""Tests for the agentsh CLI entry point (cli/main.py).

Covers:
- parse subcommand: text output, JSON output, nonexistent file
- plan subcommand: JSON plan output
- run subcommand: successful execution, non-zero exit
- no-command / help: argparse behaviour
"""

from __future__ import annotations

import json

import pytest

from agentsh.cli.main import main

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def echo_script(tmp_path):
    """Create a temp script containing 'echo hello'."""
    p = tmp_path / "echo.sh"
    p.write_text("echo hello\n")
    return str(p)


@pytest.fixture()
def exit1_script(tmp_path):
    """Create a temp script containing 'exit 1'."""
    p = tmp_path / "exit1.sh"
    p.write_text("exit 1\n")
    return str(p)


@pytest.fixture()
def multi_cmd_script(tmp_path):
    """Create a temp script with multiple commands."""
    p = tmp_path / "multi.sh"
    p.write_text("X=hello\necho $X\n")
    return str(p)


# ---------------------------------------------------------------------------
# parse subcommand
# ---------------------------------------------------------------------------


class TestParseCommand:
    """Tests for 'agentsh parse <file>'."""

    def test_parse_success_text(self, echo_script, capsys):
        """parse with a valid script prints success message and returns 0."""
        rc = main(["parse", echo_script])
        assert rc == 0
        captured = capsys.readouterr()
        assert "Parsed successfully" in captured.out

    def test_parse_success_json(self, echo_script, capsys):
        """parse --json prints a JSON object with has_errors=false and an ast."""
        rc = main(["parse", "--json", echo_script])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["has_errors"] is False
        assert data["ast"] is not None
        assert data["ast"]["type"] == "Program"

    def test_parse_json_contains_ast_body(self, echo_script, capsys):
        """parse --json AST body should contain the echo command."""
        main(["parse", "--json", echo_script])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        body = data["ast"]["body"]
        assert len(body) >= 1
        # Drill into the first command and find the 'echo' word.
        first = body[0]
        # Depending on nesting (Pipeline, SimpleCommand, etc.), look for
        # SimpleCommand somewhere in the structure.
        assert _find_type(first, "SimpleCommand"), "Expected a SimpleCommand in the AST"

    def test_parse_nonexistent_file(self, tmp_path, capsys):
        """parse with a missing file returns non-zero."""
        bad_path = str(tmp_path / "does_not_exist.sh")
        rc = main(["parse", bad_path])
        assert rc != 0
        captured = capsys.readouterr()
        assert "Error" in captured.err

    def test_parse_invalid_syntax_json(self, tmp_path, capsys):
        """parse --json with invalid syntax still returns JSON with has_errors=true."""
        p = tmp_path / "bad.sh"
        p.write_text("if; then\n")
        main(["parse", "--json", str(p)])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["has_errors"] is True

    def test_parse_invalid_syntax_text(self, tmp_path, capsys):
        """parse (text mode) with invalid syntax returns non-zero."""
        p = tmp_path / "bad.sh"
        p.write_text("if; then\n")
        rc = main(["parse", str(p)])
        assert rc != 0


# ---------------------------------------------------------------------------
# plan subcommand
# ---------------------------------------------------------------------------


class TestPlanCommand:
    """Tests for 'agentsh plan <file>'."""

    def test_plan_success(self, echo_script, capsys):
        """plan with a valid script prints JSON plan and returns 0."""
        rc = main(["plan", echo_script])
        assert rc == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "steps" in data
        assert isinstance(data["steps"], list)
        assert len(data["steps"]) >= 1

    def test_plan_step_fields(self, echo_script, capsys):
        """Each plan step should have command, resolution, args, and effects."""
        main(["plan", echo_script])
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        step = data["steps"][0]
        assert "command" in step
        assert "resolution" in step
        assert "args" in step
        assert "effects" in step

    def test_plan_nonexistent_file(self, tmp_path, capsys):
        """plan with a missing file returns non-zero."""
        bad_path = str(tmp_path / "nope.sh")
        rc = main(["plan", bad_path])
        assert rc != 0

    def test_plan_invalid_syntax(self, tmp_path, capsys):
        """plan with invalid syntax returns non-zero."""
        p = tmp_path / "bad.sh"
        p.write_text("if; then\n")
        rc = main(["plan", str(p)])
        assert rc != 0


# ---------------------------------------------------------------------------
# run subcommand
# ---------------------------------------------------------------------------


class TestRunCommand:
    """Tests for 'agentsh run <file>'."""

    def test_run_echo(self, echo_script, capsys):
        """run a script with 'echo hello' returns 0 and prints hello."""
        rc = main(["run", echo_script])
        assert rc == 0
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_run_exit_1(self, exit1_script, capsys):
        """run a script with 'exit 1' returns 1."""
        rc = main(["run", exit1_script])
        assert rc == 1

    def test_run_exit_42(self, tmp_path):
        """run 'exit 42' returns 42."""
        p = tmp_path / "exit42.sh"
        p.write_text("exit 42\n")
        rc = main(["run", str(p)])
        assert rc == 42

    def test_run_nonexistent_file(self, tmp_path, capsys):
        """run with a missing file returns non-zero."""
        bad_path = str(tmp_path / "nope.sh")
        rc = main(["run", bad_path])
        assert rc != 0

    def test_run_multi_command(self, multi_cmd_script, capsys):
        """run a script with variable assignment and echo."""
        rc = main(["run", multi_cmd_script])
        assert rc == 0
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_run_stderr_output(self, tmp_path, capsys):
        """run a script that writes to stderr via echo >&2."""
        p = tmp_path / "stderr.sh"
        p.write_text("echo error >&2\n")
        rc = main(["run", str(p)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "error" in captured.err


# ---------------------------------------------------------------------------
# No command / help
# ---------------------------------------------------------------------------


class TestNoCommand:
    """Tests for invoking main without a subcommand or with --help."""

    def test_no_args_returns_nonzero(self, capsys):
        """Calling main with no arguments returns 1 and prints help."""
        rc = main([])
        assert rc == 1
        captured = capsys.readouterr()
        # argparse help should mention the program name or usage.
        assert "agentsh" in captured.out or "usage" in captured.out.lower()

    def test_help_raises_systemexit(self):
        """--help causes argparse to raise SystemExit(0)."""
        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_parse_help_raises_systemexit(self):
        """parse --help causes argparse to raise SystemExit(0)."""
        with pytest.raises(SystemExit) as exc_info:
            main(["parse", "--help"])
        assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_type(node_dict: dict, type_name: str) -> bool:
    """Recursively search a dict-based AST for a node with given type."""
    if node_dict.get("type") == type_name:
        return True
    for v in node_dict.values():
        if isinstance(v, dict):
            if _find_type(v, type_name):
                return True
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict) and _find_type(item, type_name):
                    return True
    return False
