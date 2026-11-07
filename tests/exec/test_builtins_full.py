"""Comprehensive tests for all shell builtins.

Covers: builtin_read, builtin_shift, builtin_return, builtin_set,
builtin_local, builtin_declare, builtin_printf, builtin_echo,
builtin_export, builtin_unset, builtin_test (via BoolEvaluator).
"""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.exec.builtins import (
    ReturnSignal,
    builtin_declare,
    builtin_echo,
    builtin_export,
    builtin_local,
    builtin_printf,
    builtin_read,
    builtin_return,
    builtin_set,
    builtin_shift,
    builtin_test,
    builtin_unset,
)
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def state() -> ShellState:
    s = ShellState()
    s.cwd = "/"
    return s


@pytest.fixture
def vfs() -> VirtualFilesystem:
    return VirtualFilesystem()


@pytest.fixture
def io_ctx() -> IOContext:
    return IOContext()


def _make_io(stdin_text: str = "") -> IOContext:
    """Build an IOContext with pre-filled stdin."""
    ctx = IOContext()
    ctx.stdin = StringIO(stdin_text)
    return ctx


# ==================================================================
# builtin_read
# ==================================================================


class TestBuiltinRead:
    """Tests for the read builtin."""

    def test_read_single_variable(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("hello world\n")
        result = builtin_read(["myvar"], state, vfs, io)
        assert result.exit_code == 0
        assert state.get_var("myvar") == "hello world"

    def test_read_into_reply_when_no_var(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("some input\n")
        result = builtin_read([], state, vfs, io)
        assert result.exit_code == 0
        assert state.get_var("REPLY") == "some input"

    def test_read_multiple_variables(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("alpha beta gamma delta\n")
        result = builtin_read(["a", "b", "c"], state, vfs, io)
        assert result.exit_code == 0
        assert state.get_var("a") == "alpha"
        assert state.get_var("b") == "beta"
        # Last variable gets the rest of the line
        assert state.get_var("c") == "gamma delta"

    def test_read_multiple_variables_fewer_words(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("one\n")
        result = builtin_read(["x", "y", "z"], state, vfs, io)
        assert result.exit_code == 0
        assert state.get_var("x") == "one"
        assert state.get_var("y") == ""
        assert state.get_var("z") == ""

    def test_read_empty_stdin_returns_1(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("")
        result = builtin_read(["var"], state, vfs, io)
        assert result.exit_code == 1

    def test_read_strips_trailing_newline(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = _make_io("no trailing newline\n")
        result = builtin_read(["line"], state, vfs, io)
        assert result.exit_code == 0
        val = state.get_var("line")
        assert val == "no trailing newline"

    def test_read_without_trailing_newline(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        """Still works when stdin has no trailing newline."""
        io = _make_io("partial")
        result = builtin_read(["v"], state, vfs, io)
        assert result.exit_code == 0
        assert state.get_var("v") == "partial"


# ==================================================================
# builtin_shift
# ==================================================================


class TestBuiltinShift:
    """Tests for the shift builtin."""

    def test_shift_default(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.positional_params = ["a", "b", "c"]
        result = builtin_shift([], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.positional_params == ["b", "c"]

    def test_shift_by_n(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.positional_params = ["a", "b", "c", "d"]
        result = builtin_shift(["2"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.positional_params == ["c", "d"]

    def test_shift_all(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.positional_params = ["a", "b"]
        result = builtin_shift(["2"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.positional_params == []

    def test_shift_out_of_range(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        state.positional_params = ["a"]
        io = IOContext()
        result = builtin_shift(["5"], state, vfs, io)
        assert result.exit_code == 1
        assert "out of range" in io.stderr.getvalue()

    def test_shift_non_numeric(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        state.positional_params = ["a"]
        io = IOContext()
        result = builtin_shift(["abc"], state, vfs, io)
        assert result.exit_code == 1
        stderr = io.stderr.getvalue()
        assert "numeric argument required" in stderr

    def test_shift_empty_params(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        state.positional_params = []
        io = IOContext()
        result = builtin_shift([], state, vfs, io)
        assert result.exit_code == 1
        assert "out of range" in io.stderr.getvalue()


# ==================================================================
# builtin_return
# ==================================================================


class TestBuiltinReturn:
    """Tests for the return builtin."""

    def test_return_raises_signal_code_0(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        with pytest.raises(ReturnSignal) as exc_info:
            builtin_return([], state, vfs, io_ctx)
        assert exc_info.value.exit_code == 0

    def test_return_with_specified_code(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        with pytest.raises(ReturnSignal) as exc_info:
            builtin_return(["42"], state, vfs, io_ctx)
        assert exc_info.value.exit_code == 42

    def test_return_non_numeric_defaults_to_1(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        with pytest.raises(ReturnSignal) as exc_info:
            builtin_return(["notanum"], state, vfs, io_ctx)
        assert exc_info.value.exit_code == 1

    def test_return_signal_is_exception(self) -> None:
        sig = ReturnSignal(7)
        assert isinstance(sig, Exception)
        assert isinstance(sig, ReturnSignal)
        assert sig.exit_code == 7


# ==================================================================
# builtin_set
# ==================================================================


class TestBuiltinSet:
    """Tests for the set builtin."""

    def test_no_args_prints_all_variables(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        state.set_var("FOO", "bar")
        state.set_var("BAZ", "qux")
        io = IOContext()
        result = builtin_set([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "FOO=bar" in output
        assert "BAZ=qux" in output

    def test_set_e_enables_errexit(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        assert state.options.errexit is False
        builtin_set(["-e"], state, vfs, io_ctx)
        assert state.options.errexit is True

    def test_set_plus_e_disables_errexit(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.options.errexit = True
        builtin_set(["+e"], state, vfs, io_ctx)
        assert state.options.errexit is False

    def test_set_u_enables_nounset(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-u"], state, vfs, io_ctx)
        assert state.options.nounset is True

    def test_set_plus_u_disables_nounset(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.options.nounset = True
        builtin_set(["+u"], state, vfs, io_ctx)
        assert state.options.nounset is False

    def test_set_x_enables_xtrace(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-x"], state, vfs, io_ctx)
        assert state.options.xtrace is True

    def test_set_f_enables_noglob(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-f"], state, vfs, io_ctx)
        assert state.options.noglob is True

    def test_set_o_pipefail_enables(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-o", "pipefail"], state, vfs, io_ctx)
        assert state.options.pipefail is True

    def test_set_plus_o_pipefail_disables(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.options.pipefail = True
        builtin_set(["+o", "pipefail"], state, vfs, io_ctx)
        assert state.options.pipefail is False

    def test_set_double_dash_positional(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(
            ["--", "alpha", "beta", "gamma"],
            state,
            vfs,
            io_ctx,
        )
        expected = ["alpha", "beta", "gamma"]
        assert state.positional_params == expected

    def test_set_double_dash_empty(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.positional_params = ["old"]
        builtin_set(["--"], state, vfs, io_ctx)
        assert state.positional_params == []

    def test_set_combined_flags(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-eu"], state, vfs, io_ctx)
        assert state.options.errexit is True
        assert state.options.nounset is True

    def test_set_combined_disable(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.options.errexit = True
        state.options.nounset = True
        builtin_set(["+eu"], state, vfs, io_ctx)
        assert state.options.errexit is False
        assert state.options.nounset is False

    def test_set_mixed_flags_and_positional(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        builtin_set(["-e", "--", "x", "y"], state, vfs, io_ctx)
        assert state.options.errexit is True
        assert state.positional_params == ["x", "y"]


# ==================================================================
# builtin_local
# ==================================================================


class TestBuiltinLocal:
    """Tests for the local builtin."""

    def test_local_with_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        result = builtin_local(["x=hello"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("x") == "hello"

    def test_local_without_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        result = builtin_local(["x"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("x") == ""

    def test_local_preserves_existing(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.set_var("x", "existing")
        result = builtin_local(["x"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("x") == "existing"

    def test_local_multiple_declarations(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        result = builtin_local(["a=1", "b=2", "c"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("a") == "1"
        assert state.get_var("b") == "2"
        assert state.get_var("c") == ""

    def test_local_value_with_equals(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        """local x=a=b should set x to 'a=b'."""
        result = builtin_local(["x=a=b"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("x") == "a=b"

    def test_local_empty_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        result = builtin_local(["x="], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert state.get_var("x") == ""


# ==================================================================
# builtin_declare
# ==================================================================


class TestBuiltinDeclare:
    """Tests for the declare builtin (delegates to local)."""

    def test_declare_with_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_declare(["myvar=42"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("myvar") == "42"

    def test_declare_without_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_declare(["myvar"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("myvar") == ""

    def test_declare_multiple(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_declare(["a=hello", "b=world"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("a") == "hello"
        assert state.get_var("b") == "world"


# ==================================================================
# builtin_printf (edge cases)
# ==================================================================


class TestBuiltinPrintf:
    """Tests for the printf builtin."""

    def test_percent_s(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%s", "hello"], state, vfs, io)
        assert io.stdout.getvalue() == "hello"

    def test_percent_d(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%d", "42"], state, vfs, io)
        assert io.stdout.getvalue() == "42"

    def test_percent_d_non_numeric(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%d", "abc"], state, vfs, io)
        assert io.stdout.getvalue() == "0"

    def test_literal_percent(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["100%%"], state, vfs, io)
        assert io.stdout.getvalue() == "100%"

    def test_newline_escape(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["line1\\nline2"], state, vfs, io)
        assert io.stdout.getvalue() == "line1\nline2"

    def test_tab_escape(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["col1\\tcol2"], state, vfs, io)
        assert io.stdout.getvalue() == "col1\tcol2"

    def test_backslash_escape(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["back\\\\slash"], state, vfs, io)
        assert io.stdout.getvalue() == "back\\slash"

    def test_missing_arg_for_s(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%s"], state, vfs, io)
        assert io.stdout.getvalue() == ""

    def test_missing_arg_for_d(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%d"], state, vfs, io)
        # Missing arg "" -> int("") fails -> outputs 0
        assert io.stdout.getvalue() == "0"

    def test_multiple_format_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%s is %d", "age", "30"], state, vfs, io)
        assert io.stdout.getvalue() == "age is 30"

    def test_no_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        result = builtin_printf([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_plain_text(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["just text"], state, vfs, io)
        assert io.stdout.getvalue() == "just text"

    def test_mixed_escapes_and_formats(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        fmt = "Name: %s\\nAge: %d\\n"
        builtin_printf([fmt, "Alice", "25"], state, vfs, io)
        assert io.stdout.getvalue() == "Name: Alice\nAge: 25\n"

    def test_percent_d_negative(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_printf(["%d", "-7"], state, vfs, io)
        assert io.stdout.getvalue() == "-7"

    def test_extra_args_cycle(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        """Extra args cause the format string to be re-applied (cycling)."""
        io = IOContext()
        builtin_printf(["%s", "used", "again"], state, vfs, io)
        assert io.stdout.getvalue() == "usedagain"


# ==================================================================
# builtin_echo (edge cases)
# ==================================================================


class TestBuiltinEcho:
    """Tests for the echo builtin."""

    def test_echo_no_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        result = builtin_echo([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "\n"

    def test_echo_single_arg(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_echo(["hello"], state, vfs, io)
        assert io.stdout.getvalue() == "hello\n"

    def test_echo_multiple_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_echo(["hello", "world", "foo"], state, vfs, io)
        assert io.stdout.getvalue() == "hello world foo\n"

    def test_echo_n_no_newline(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_echo(["-n", "hello"], state, vfs, io)
        assert io.stdout.getvalue() == "hello"

    def test_echo_n_no_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_echo(["-n"], state, vfs, io)
        assert io.stdout.getvalue() == ""

    def test_echo_n_multiple_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        builtin_echo(["-n", "a", "b", "c"], state, vfs, io)
        assert io.stdout.getvalue() == "a b c"

    def test_echo_returns_success(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        result = builtin_echo(["test"], state, vfs, io)
        assert result.exit_code == 0


# ==================================================================
# builtin_export (edge cases)
# ==================================================================


class TestBuiltinExport:
    """Tests for the export builtin."""

    def test_export_var_with_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_export(["FOO=bar"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("FOO") == "bar"
        assert state.exported_env["FOO"] == "bar"

    def test_export_existing_var_without_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.set_var("EXISTING", "value123")
        r = builtin_export(["EXISTING"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.exported_env["EXISTING"] == "value123"

    def test_export_nonexistent_var(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_export(["NEWVAR"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.exported_env["NEWVAR"] == ""

    def test_export_no_args_prints_all(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        state.export_var("A", "1")
        state.export_var("B", "2")
        io = IOContext()
        result = builtin_export([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert 'declare -x A="1"' in output
        assert 'declare -x B="2"' in output

    def test_export_multiple_vars(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_export(["X=10", "Y=20"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.exported_env["X"] == "10"
        assert state.exported_env["Y"] == "20"

    def test_export_value_with_equals_sign(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_export(["PATH=/usr/bin:/bin"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("PATH") == "/usr/bin:/bin"

    def test_export_empty_value(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_export(["EMPTY="], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("EMPTY") == ""
        assert state.exported_env["EMPTY"] == ""


# ==================================================================
# builtin_unset
# ==================================================================


class TestBuiltinUnset:
    """Tests for the unset builtin."""

    def test_unset_variable(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.set_var("TO_REMOVE", "value")
        r = builtin_unset(["TO_REMOVE"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("TO_REMOVE") is None

    def test_unset_exported_variable(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.export_var("EXPORTED", "val")
        r = builtin_unset(["EXPORTED"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert "EXPORTED" not in state.exported_env

    def test_unset_with_v_flag(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.set_var("VAR", "hello")
        r = builtin_unset(["-v", "VAR"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("VAR") is None

    def test_unset_with_f_flag(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        """The -f flag is skipped; args are still processed."""
        state.set_var("FUNC_VAR", "data")
        r = builtin_unset(["-f", "FUNC_VAR"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("FUNC_VAR") is None

    def test_unset_nonexistent_no_error(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_unset(["DOES_NOT_EXIST"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_unset_multiple_variables(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        state.set_var("A", "1")
        state.set_var("B", "2")
        state.set_var("C", "3")
        r = builtin_unset(["A", "B", "C"], state, vfs, io_ctx)
        assert r.exit_code == 0
        assert state.get_var("A") is None
        assert state.get_var("B") is None
        assert state.get_var("C") is None

    def test_unset_no_args(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_unset([], state, vfs, io_ctx)
        assert r.exit_code == 0


# ==================================================================
# builtin_test / [ (comprehensive via BoolEvaluator)
# ==================================================================


class TestBuiltinTest:
    """Tests for the test / [ builtin."""

    # -- File tests ------------------------------------------------

    def test_f_existing_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/tmp/file.txt", b"content")
        r = builtin_test(["-f", "/tmp/file.txt"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_f_nonexistent(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-f", "/nope"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_f_directory_is_not_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.mkdir("/mydir")
        r = builtin_test(["-f", "/mydir"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_d_existing_directory(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.mkdir("/testdir")
        r = builtin_test(["-d", "/testdir"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_d_file_is_not_dir(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/afile", b"data")
        r = builtin_test(["-d", "/afile"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_e_existing_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/exists", b"x")
        r = builtin_test(["-e", "/exists"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_e_existing_dir(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.mkdir("/existdir")
        r = builtin_test(["-e", "/existdir"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_e_nonexistent(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-e", "/nope"], state, vfs, io_ctx)
        assert r.exit_code == 1

    # -- String tests ----------------------------------------------

    def test_z_empty_string(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-z", ""], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_z_nonempty_string(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-z", "hello"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_n_nonempty_string(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-n", "hello"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_n_empty_string(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-n", ""], state, vfs, io_ctx)
        assert r.exit_code == 1

    # -- String comparisons ----------------------------------------

    def test_equal_strings(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "=", "abc"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_equal_strings_double_eq(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "==", "abc"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_not_equal_strings_eq(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "=", "xyz"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_not_equal_strings(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "!=", "xyz"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_not_equal_same_strings(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "!=", "abc"], state, vfs, io_ctx)
        assert r.exit_code == 1

    # -- Integer comparisons ---------------------------------------

    def test_eq_equal(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-eq", "5"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_eq_not_equal(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-eq", "6"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_ne(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-ne", "6"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_ne_same(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-ne", "5"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_lt(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["3", "-lt", "5"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_lt_not(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-lt", "3"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_gt(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-gt", "3"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_le(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["3", "-le", "3"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_le_less(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["2", "-le", "3"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_le_greater(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["4", "-le", "3"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_ge(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["3", "-ge", "3"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_ge_greater(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["5", "-ge", "3"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_ge_less(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["2", "-ge", "3"], state, vfs, io_ctx)
        assert r.exit_code == 1

    # -- Logical operators -----------------------------------------

    def test_and_both_true(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "-a", "xyz"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_and_one_empty(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "-a", ""], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_or_both_true(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["abc", "-o", "xyz"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_or_one_empty(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["", "-o", "xyz"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_or_both_empty(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["", "-o", ""], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_not_true_becomes_false(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["!", "hello"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_not_empty_becomes_true(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["!", ""], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_not_binary_true_becomes_false(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        """4-arg form: ! <binary-expr> is negated."""
        r = builtin_test(["!", "5", "-eq", "5"], state, vfs, io_ctx)
        # ! (5 -eq 5) -> ! True -> False -> exit 1
        assert r.exit_code == 1

    def test_not_binary_false_becomes_true(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["!", "5", "-eq", "6"], state, vfs, io_ctx)
        # ! (5 -eq 6) -> ! False -> True -> exit 0
        assert r.exit_code == 0

    # -- Bracket syntax --------------------------------------------

    def test_bracket_strips_trailing(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        """[ -z '' ] strips the trailing ] and evaluates."""
        r = builtin_test(["-z", "", "]"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_bracket_string_comparison(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["foo", "=", "foo", "]"], state, vfs, io_ctx)
        assert r.exit_code == 0

    # -- Edge cases ------------------------------------------------

    def test_no_args_returns_1(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test([], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_single_nonempty_string_is_true(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["anything"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_single_empty_string_is_false(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test([""], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_integer_comparison_non_numeric(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        """Non-numeric args to int comparison return false."""
        r = builtin_test(["abc", "-eq", "def"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_r_existing_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/readable", b"content")
        r = builtin_test(["-r", "/readable"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_w_existing_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/writable", b"content")
        r = builtin_test(["-w", "/writable"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_x_existing_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/executable", b"content")
        r = builtin_test(["-x", "/executable"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_s_nonempty_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/nonempty", b"data")
        r = builtin_test(["-s", "/nonempty"], state, vfs, io_ctx)
        assert r.exit_code == 0

    def test_s_empty_file(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        vfs.write("/emptyfile", b"")
        r = builtin_test(["-s", "/emptyfile"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_s_nonexistent(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-s", "/nope"], state, vfs, io_ctx)
        assert r.exit_code == 1

    def test_negative_integer_comparison(
        self,
        state: ShellState,
        vfs: VirtualFilesystem,
        io_ctx: IOContext,
    ) -> None:
        r = builtin_test(["-1", "-lt", "0"], state, vfs, io_ctx)
        assert r.exit_code == 0
