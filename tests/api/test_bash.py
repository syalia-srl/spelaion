"""Comprehensive tests for the Bash class API (agentsh.api.bash).

Covers:
- Basic usage (echo, file persistence, variable/function persistence)
- Constructor options (files, env, cwd, defaults)
- Per-run overrides (env, cwd, stdin, args)
- Custom commands (define_command, piped stdin, CommandContext)
- Filesystem helpers (read_file, write_file, write_files, file_exists)
- Error handling (syntax error, command not found, exit codes)
- Complex scenarios (pipelines, redirects, loops, conditionals, command
  substitution, multi-line scripts)
"""

from __future__ import annotations

from agentsh import Bash, CommandContext, RunResult, define_command

# =========================================================================
# Basic usage
# =========================================================================


class TestBasicUsage:
    """Tests matching core just-bash examples."""

    def test_echo_hello(self) -> None:
        bash = Bash()
        result = bash.run('echo "Hello"')
        assert result.stdout == "Hello\n"
        assert result.exit_code == 0

    def test_filesystem_persists_across_runs(self) -> None:
        bash = Bash()
        bash.run('echo "Hello" > greeting.txt')
        result = bash.run("cat greeting.txt")
        assert result.stdout == "Hello\n"
        assert result.exit_code == 0

    def test_variable_persistence(self) -> None:
        bash = Bash()
        bash.run("X=hello")
        result = bash.run("echo $X")
        assert result.stdout == "hello\n"

    def test_function_persistence(self) -> None:
        bash = Bash()
        bash.run('greet() { echo "hi $1"; }')
        result = bash.run("greet world")
        assert result.stdout == "hi world\n"


# =========================================================================
# Constructor options
# =========================================================================


class TestConstructorOptions:
    """Tests for Bash(...) constructor parameters."""

    def test_files_initial_filesystem(self) -> None:
        bash = Bash(files={"/data/f.txt": "content"})
        result = bash.run("cat /data/f.txt")
        assert result.stdout == "content"
        assert result.exit_code == 0

    def test_env_initial_variables(self) -> None:
        bash = Bash(env={"MY_VAR": "value"})
        result = bash.run("echo $MY_VAR")
        assert result.stdout == "value\n"

    def test_cwd_initial_working_directory(self) -> None:
        bash = Bash(cwd="/tmp")
        result = bash.run("pwd")
        assert result.stdout == "/tmp\n"

    def test_default_home_is_set(self) -> None:
        bash = Bash()
        result = bash.run("echo $HOME")
        assert result.stdout.strip() != ""
        assert result.stdout == "/home/user\n"

    def test_default_pwd_is_set(self) -> None:
        bash = Bash()
        result = bash.run("echo $PWD")
        assert result.stdout.strip() != ""

    def test_default_pwd_matches_cwd(self) -> None:
        bash = Bash(cwd="/opt")
        result = bash.run("echo $PWD")
        assert result.stdout == "/opt\n"


# =========================================================================
# Per-run overrides
# =========================================================================


class TestPerRunOverrides:
    """Tests for keyword arguments to bash.run()."""

    def test_env_override(self) -> None:
        bash = Bash()
        result = bash.run("echo $TEMP", env={"TEMP": "value"})
        assert result.stdout == "value\n"

    def test_cwd_override(self) -> None:
        bash = Bash(cwd="/")
        result = bash.run("pwd", cwd="/tmp")
        assert result.stdout == "/tmp\n"

    def test_stdin_input(self) -> None:
        bash = Bash()
        result = bash.run("cat", stdin="hello from stdin\n")
        assert result.stdout == "hello from stdin\n"

    def test_positional_args(self) -> None:
        bash = Bash()
        result = bash.run("echo $1 $2", args=["foo", "bar"])
        assert result.stdout == "foo bar\n"

    def test_positional_args_do_not_persist(self) -> None:
        bash = Bash()
        bash.run("echo $1", args=["temp"])
        result = bash.run("echo $1")
        # $1 should be empty after the run with args finishes
        assert result.stdout.strip() == ""


# =========================================================================
# Custom commands
# =========================================================================


class TestCustomCommands:
    """Tests for define_command and custom command integration."""

    def test_custom_command_basic(self) -> None:
        hello = define_command(
            "hello",
            lambda args, ctx: RunResult(stdout="Hello!\n"),
        )
        bash = Bash(custom_commands=[hello])
        result = bash.run("hello")
        assert result.stdout == "Hello!\n"
        assert result.exit_code == 0

    def test_custom_command_receives_args(self) -> None:
        def greet_handler(args: list[str], ctx: CommandContext) -> RunResult:
            name = args[0] if args else "world"
            return RunResult(stdout=f"Hello, {name}!\n")

        greet = define_command("greet", greet_handler)
        bash = Bash(custom_commands=[greet])
        result = bash.run("greet Alice")
        assert result.stdout == "Hello, Alice!\n"

    def test_custom_command_receives_stdin_via_pipe(self) -> None:
        def upper_handler(args: list[str], ctx: CommandContext) -> RunResult:
            return RunResult(stdout=ctx.stdin.upper())

        upper = define_command("upper", upper_handler)
        bash = Bash(custom_commands=[upper])
        result = bash.run("echo test | upper")
        assert result.stdout == "TEST\n"

    def test_custom_command_has_context(self) -> None:
        captured: dict[str, object] = {}

        def inspector(args: list[str], ctx: CommandContext) -> RunResult:
            captured["cwd"] = ctx.cwd
            captured["env"] = dict(ctx.env)
            captured["has_fs"] = ctx.fs is not None
            return RunResult(stdout="ok\n")

        cmd = define_command("inspector", inspector)
        bash = Bash(
            cwd="/work",
            env={"KEY": "val"},
            custom_commands=[cmd],
        )
        bash.run("inspector")
        assert captured["cwd"] == "/work"
        assert captured["env"]["KEY"] == "val"  # type: ignore[index]
        assert captured["has_fs"] is True


# =========================================================================
# Filesystem helpers
# =========================================================================


class TestFilesystemHelpers:
    """Tests for Bash.write_file, read_file, write_files, file_exists."""

    def test_write_and_read_file(self) -> None:
        bash = Bash()
        bash.write_file("/test.txt", "content")
        assert bash.read_file("/test.txt") == "content"

    def test_write_files_multiple(self) -> None:
        bash = Bash()
        bash.write_files(
            {
                "/a.txt": "alpha",
                "/b.txt": "beta",
            }
        )
        assert bash.read_file("/a.txt") == "alpha"
        assert bash.read_file("/b.txt") == "beta"

    def test_file_exists_true(self) -> None:
        bash = Bash()
        bash.write_file("/exists.txt", "yes")
        assert bash.file_exists("/exists.txt") is True

    def test_file_exists_false(self) -> None:
        bash = Bash()
        assert bash.file_exists("/nope.txt") is False

    def test_write_file_readable_by_cat(self) -> None:
        bash = Bash()
        bash.write_file("/data.txt", "hello world")
        result = bash.run("cat /data.txt")
        assert result.stdout == "hello world"

    def test_run_write_readable_by_helper(self) -> None:
        bash = Bash()
        bash.run('echo "from shell" > /output.txt')
        content = bash.read_file("/output.txt")
        assert content.strip() == "from shell"


# =========================================================================
# Error handling
# =========================================================================


class TestErrorHandling:
    """Tests for error conditions and exit codes."""

    def test_syntax_error_returns_exit_code_2(self) -> None:
        bash = Bash()
        result = bash.run("if then fi what")
        assert result.exit_code == 2
        assert "syntax error" in result.stderr.lower()

    def test_command_not_found_returns_exit_code_127(self) -> None:
        bash = Bash()
        result = bash.run("nonexistent_command_xyz")
        assert result.exit_code == 127
        assert "not found" in result.stderr.lower()

    def test_exit_1_returns_exit_code_1(self) -> None:
        bash = Bash()
        result = bash.run("exit 1")
        assert result.exit_code == 1

    def test_exit_0_returns_exit_code_0(self) -> None:
        bash = Bash()
        result = bash.run("exit 0")
        assert result.exit_code == 0

    def test_exit_42_returns_exit_code_42(self) -> None:
        bash = Bash()
        result = bash.run("exit 42")
        assert result.exit_code == 42

    def test_false_returns_exit_code_1(self) -> None:
        bash = Bash()
        result = bash.run("false")
        assert result.exit_code == 1


# =========================================================================
# Complex scenarios
# =========================================================================


class TestComplexScenarios:
    """Tests for pipelines, redirects, loops, conditionals, etc."""

    def test_pipeline_echo_tr(self) -> None:
        bash = Bash()
        result = bash.run("echo hello | tr a-z A-Z")
        assert result.stdout == "HELLO\n"

    def test_redirect_append_and_cat(self) -> None:
        bash = Bash()
        result = bash.run("echo a > /f; echo b >> /f; cat /f")
        assert result.stdout == "a\nb\n"

    def test_for_loop(self) -> None:
        bash = Bash()
        result = bash.run("for i in 1 2 3; do echo $i; done")
        assert result.stdout == "1\n2\n3\n"

    def test_if_statement_true_branch(self) -> None:
        bash = Bash()
        result = bash.run("if true; then echo yes; fi")
        assert result.stdout == "yes\n"

    def test_if_statement_false_branch(self) -> None:
        bash = Bash()
        result = bash.run("if false; then echo yes; else echo no; fi")
        assert result.stdout == "no\n"

    def test_command_substitution(self) -> None:
        bash = Bash()
        result = bash.run("echo $(echo nested)")
        assert result.stdout == "nested\n"

    def test_multiline_script(self) -> None:
        bash = Bash()
        script = """\
X=10
Y=20
echo $X
echo $Y
"""
        result = bash.run(script)
        assert result.stdout == "10\n20\n"

    def test_while_loop(self) -> None:
        bash = Bash()
        script = """\
i=0
while [ $i -lt 3 ]; do
  echo $i
  i=$((i + 1))
done
"""
        result = bash.run(script)
        assert result.stdout == "0\n1\n2\n"

    def test_nested_command_substitution(self) -> None:
        bash = Bash()
        result = bash.run("echo $(echo $(echo deep))")
        assert result.stdout == "deep\n"

    def test_variable_in_double_quotes(self) -> None:
        bash = Bash()
        bash.run('NAME="world"')
        result = bash.run('echo "hello $NAME"')
        assert result.stdout == "hello world\n"

    def test_single_quotes_no_expansion(self) -> None:
        bash = Bash()
        bash.run("X=hello")
        result = bash.run("echo '$X'")
        assert result.stdout == "$X\n"

    def test_semicolons_sequence(self) -> None:
        bash = Bash()
        result = bash.run("echo a; echo b; echo c")
        assert result.stdout == "a\nb\nc\n"

    def test_and_list(self) -> None:
        bash = Bash()
        result = bash.run("true && echo yes")
        assert result.stdout == "yes\n"

    def test_or_list(self) -> None:
        bash = Bash()
        result = bash.run("false || echo fallback")
        assert result.stdout == "fallback\n"

    def test_arithmetic_expansion(self) -> None:
        bash = Bash()
        result = bash.run("echo $((2 + 3))")
        assert result.stdout == "5\n"


# =========================================================================
# RunResult dataclass
# =========================================================================


class TestRunResult:
    """Tests for the RunResult dataclass itself."""

    def test_defaults(self) -> None:
        r = RunResult()
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.exit_code == 0

    def test_custom_values(self) -> None:
        r = RunResult(stdout="out", stderr="err", exit_code=42)
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.exit_code == 42
