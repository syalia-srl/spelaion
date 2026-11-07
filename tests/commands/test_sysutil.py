"""Tests for system utility commands.

seq, sleep, env, which, date, uname, whoami, id, yes, mktemp, comm.

Covers:
- seq: single arg, two args, three args, -s separator, -w padding
- sleep: returns immediately with exit 0
- env: prints exported vars; -u removes a var
- which: finds builtins, virtual commands, not found
- date: default output, +FORMAT, $AGENTSH_DATE override
- uname: default (-s), -a all, -r release, -m machine
- whoami: prints $USER or "root"
- id: prints uid/gid
- yes: outputs many "y" lines
- mktemp: creates file in /tmp, -d creates dir, -p custom parent
- comm: compare sorted files, -1 -2 -3 suppress columns
"""

from __future__ import annotations

import pytest

from agentsh.commands.sysutil import (
    cmd_comm,
    cmd_date,
    cmd_env,
    cmd_id,
    cmd_mktemp,
    cmd_seq,
    cmd_sleep,
    cmd_uname,
    cmd_which,
    cmd_whoami,
    cmd_yes,
)
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vfs() -> VirtualFilesystem:
    return VirtualFilesystem()


@pytest.fixture()
def state() -> ShellState:
    return ShellState()


@pytest.fixture()
def io_ctx() -> IOContext:
    return IOContext()


# ---------------------------------------------------------------------------
# seq
# ---------------------------------------------------------------------------


class TestSeq:
    """Tests for the seq command."""

    def test_single_arg(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq 5 should produce 1 through 5."""
        io = IOContext()
        result = cmd_seq(["5"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\n2\n3\n4\n5\n"

    def test_single_arg_one(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq 1 should produce just '1'."""
        io = IOContext()
        result = cmd_seq(["1"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\n"

    def test_two_args(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq 3 6 should produce 3, 4, 5, 6."""
        io = IOContext()
        result = cmd_seq(["3", "6"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "3\n4\n5\n6\n"

    def test_two_args_reverse_empty(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq 6 3 with default inc=1 produces no output (just a trailing newline)."""
        io = IOContext()
        result = cmd_seq(["6", "3"], state, vfs, io)
        assert result.exit_code == 0
        # No numbers generated, but the separator.join([]) + "\n" gives "\n"
        assert io.stdout.getvalue() == "\n"

    def test_three_args_increment(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq 1 2 9 should produce 1, 3, 5, 7, 9."""
        io = IOContext()
        result = cmd_seq(["1", "2", "9"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\n3\n5\n7\n9\n"

    def test_three_args_negative_increment(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq 5 -1 1 should produce 5, 4, 3, 2, 1."""
        io = IOContext()
        result = cmd_seq(["5", "-1", "1"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "5\n4\n3\n2\n1\n"

    def test_separator_option(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq -s ', ' 3 should produce '1, 2, 3'."""
        io = IOContext()
        result = cmd_seq(["-s", ", ", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1, 2, 3\n"

    def test_separator_space(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq -s ' ' 4 should produce '1 2 3 4'."""
        io = IOContext()
        result = cmd_seq(["-s", " ", "4"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1 2 3 4\n"

    def test_pad_width(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq -w 8 10 should produce 08, 09, 10."""
        io = IOContext()
        result = cmd_seq(["-w", "8", "10"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "08\n09\n10\n"

    def test_pad_width_single_digit(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq -w 1 3 should not need zero-padding (all same width)."""
        io = IOContext()
        result = cmd_seq(["-w", "1", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\n2\n3\n"

    def test_no_args_error(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq with no arguments should fail."""
        io = IOContext()
        result = cmd_seq([], state, vfs, io)
        assert result.exit_code == 1
        assert "missing operand" in io.stderr.getvalue()

    def test_invalid_arg(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """seq with non-numeric arg should fail."""
        io = IOContext()
        result = cmd_seq(["abc"], state, vfs, io)
        assert result.exit_code == 1
        assert "invalid" in io.stderr.getvalue()

    def test_separator_with_range(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq -s : 2 5 should produce '2:3:4:5'."""
        io = IOContext()
        result = cmd_seq(["-s", ":", "2", "5"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "2:3:4:5\n"

    def test_pad_width_combined_with_separator(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq -w -s ' ' 8 11 should produce '08 09 10 11'."""
        io = IOContext()
        result = cmd_seq(["-w", "-s", " ", "8", "11"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "08 09 10 11\n"


# ---------------------------------------------------------------------------
# sleep
# ---------------------------------------------------------------------------


class TestSleep:
    """Tests for the sleep command (virtual no-op)."""

    def test_sleep_returns_zero(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_sleep(["1"], state, vfs, io)
        assert result.exit_code == 0

    def test_sleep_no_args(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """sleep with no args still returns 0 (virtual)."""
        io = IOContext()
        result = cmd_sleep([], state, vfs, io)
        assert result.exit_code == 0

    def test_sleep_produces_no_output(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        cmd_sleep(["10"], state, vfs, io)
        assert io.stdout.getvalue() == ""
        assert io.stderr.getvalue() == ""


# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------


class TestEnv:
    """Tests for the env command."""

    def test_prints_exported_vars(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.exported_env = {"FOO": "bar", "BAZ": "qux"}
        io = IOContext()
        result = cmd_env([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "FOO=bar\n" in output
        assert "BAZ=qux\n" in output

    def test_exported_vars_sorted(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.exported_env = {"ZZZ": "last", "AAA": "first", "MMM": "middle"}
        io = IOContext()
        cmd_env([], state, vfs, io)
        lines = io.stdout.getvalue().strip().split("\n")
        assert lines == ["AAA=first", "MMM=middle", "ZZZ=last"]

    def test_unset_option(self, vfs: VirtualFilesystem) -> None:
        """env -u FOO should exclude FOO from output."""
        state = ShellState()
        state.exported_env = {"FOO": "bar", "BAZ": "qux"}
        io = IOContext()
        result = cmd_env(["-u", "FOO"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "FOO" not in output
        assert "BAZ=qux\n" in output

    def test_unset_multiple_vars(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.exported_env = {"A": "1", "B": "2", "C": "3"}
        io = IOContext()
        cmd_env(["-u", "A", "-u", "C"], state, vfs, io)
        output = io.stdout.getvalue()
        assert "A=" not in output
        assert "B=2\n" in output
        assert "C=" not in output

    def test_empty_env(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.exported_env = {}
        io = IOContext()
        result = cmd_env([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""


# ---------------------------------------------------------------------------
# which
# ---------------------------------------------------------------------------


class TestWhich:
    """Tests for the which command."""

    def test_finds_builtin(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """echo is a builtin and should be found."""
        io = IOContext()
        result = cmd_which(["echo"], state, vfs, io)
        assert result.exit_code == 0
        assert "shell builtin" in io.stdout.getvalue()

    def test_finds_virtual_command(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """seq is a registered virtual command."""
        io = IOContext()
        result = cmd_which(["seq"], state, vfs, io)
        assert result.exit_code == 0
        assert "virtual command" in io.stdout.getvalue()

    def test_not_found(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_which(["nonexistent_command_xyz"], state, vfs, io)
        assert result.exit_code == 1
        assert "no nonexistent_command_xyz" in io.stderr.getvalue()

    def test_finds_function(self, vfs: VirtualFilesystem) -> None:
        """which should find shell functions."""
        state = ShellState()
        # Add a mock function to state.functions
        state.functions["myfunc"] = object()  # type: ignore[assignment]
        io = IOContext()
        result = cmd_which(["myfunc"], state, vfs, io)
        assert result.exit_code == 0
        assert "shell function" in io.stdout.getvalue()

    def test_multiple_args_mixed(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """which with multiple args: some found, some not."""
        io = IOContext()
        result = cmd_which(["echo", "nonexistent_xyz"], state, vfs, io)
        assert result.exit_code == 1  # at least one not found
        stdout = io.stdout.getvalue()
        stderr = io.stderr.getvalue()
        assert "echo" in stdout
        assert "nonexistent_xyz" in stderr

    def test_multiple_builtins(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """which cd pwd should find both."""
        io = IOContext()
        result = cmd_which(["cd", "pwd"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# date
# ---------------------------------------------------------------------------


class TestDate:
    """Tests for the date command."""

    def test_default_output(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """date with no args should produce some output."""
        io = IOContext()
        result = cmd_date([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert len(output) > 0
        assert output.endswith("\n")

    def test_format_string(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """date +%Y should produce a 4-digit year."""
        io = IOContext()
        result = cmd_date(["+%Y"], state, vfs, io)
        assert result.exit_code == 0
        year = io.stdout.getvalue().strip()
        assert len(year) == 4
        assert year.isdigit()

    def test_format_date_only(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """date +%Y-%m-%d should produce a date like YYYY-MM-DD."""
        io = IOContext()
        result = cmd_date(["+%Y-%m-%d"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        parts = output.split("-")
        assert len(parts) == 3

    def test_agentsh_date_override(self, vfs: VirtualFilesystem) -> None:
        """$AGENTSH_DATE overrides the output."""
        state = ShellState()
        state.set_var("AGENTSH_DATE", "2024-01-01")
        io = IOContext()
        result = cmd_date([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "2024-01-01\n"

    def test_agentsh_date_overrides_format(self, vfs: VirtualFilesystem) -> None:
        """When $AGENTSH_DATE is set, format arguments are ignored."""
        state = ShellState()
        state.set_var("AGENTSH_DATE", "fixed-date")
        io = IOContext()
        result = cmd_date(["+%Y"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "fixed-date\n"


# ---------------------------------------------------------------------------
# uname
# ---------------------------------------------------------------------------


class TestUname:
    """Tests for the uname command."""

    def test_default_prints_sysname(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_uname([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "VirtualOS\n"

    def test_s_flag(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_uname(["-s"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "VirtualOS\n"

    def test_a_flag_all(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_uname(["-a"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        assert "VirtualOS" in output
        assert "agentsh" in output
        assert "1.0.0" in output
        assert "virtual" in output

    def test_r_flag_release(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_uname(["-r"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1.0.0\n"

    def test_m_flag_machine(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_uname(["-m"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "virtual\n"

    def test_n_flag_nodename(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_uname(["-n"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "agentsh\n"

    def test_combined_flags(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """uname -s -m should print sysname and machine."""
        io = IOContext()
        result = cmd_uname(["-s", "-m"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "VirtualOS virtual\n"


# ---------------------------------------------------------------------------
# whoami
# ---------------------------------------------------------------------------


class TestWhoami:
    """Tests for the whoami command."""

    def test_default_root(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """whoami with no $USER should print 'root'."""
        io = IOContext()
        result = cmd_whoami([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "root\n"

    def test_custom_user(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.set_var("USER", "alice")
        io = IOContext()
        result = cmd_whoami([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "alice\n"


# ---------------------------------------------------------------------------
# id
# ---------------------------------------------------------------------------


class TestId:
    """Tests for the id command."""

    def test_root_user(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """id with default user (root) should show uid=0."""
        io = IOContext()
        result = cmd_id([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "uid=0(root)" in output
        assert "gid=0(root)" in output

    def test_non_root_user(self, vfs: VirtualFilesystem) -> None:
        state = ShellState()
        state.set_var("USER", "bob")
        io = IOContext()
        result = cmd_id([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "uid=1000(bob)" in output
        assert "gid=1000(bob)" in output


# ---------------------------------------------------------------------------
# yes
# ---------------------------------------------------------------------------


class TestYes:
    """Tests for the yes command."""

    def test_default_output(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """yes with no args should output many 'y' lines."""
        io = IOContext()
        result = cmd_yes([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert output.startswith("y\ny\ny\n")
        lines = output.strip().split("\n")
        assert len(lines) == 10000

    def test_custom_text(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """yes hello should output many 'hello' lines."""
        io = IOContext()
        result = cmd_yes(["hello"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert output.startswith("hello\nhello\n")

    def test_custom_text_multiple_args(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """yes hello world should output 'hello world' lines."""
        io = IOContext()
        result = cmd_yes(["hello", "world"], state, vfs, io)
        assert result.exit_code == 0
        first_line = io.stdout.getvalue().split("\n")[0]
        assert first_line == "hello world"


# ---------------------------------------------------------------------------
# mktemp
# ---------------------------------------------------------------------------


class TestMktemp:
    """Tests for the mktemp command."""

    def test_creates_file_in_tmp(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_mktemp([], state, vfs, io)
        assert result.exit_code == 0
        path = io.stdout.getvalue().strip()
        assert path.startswith("/tmp/tmp.")
        assert vfs.exists(path)
        assert vfs.is_file(path)

    def test_creates_dir_with_d(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_mktemp(["-d"], state, vfs, io)
        assert result.exit_code == 0
        path = io.stdout.getvalue().strip()
        assert path.startswith("/tmp/tmp.")
        assert vfs.exists(path)
        assert vfs.is_dir(path)

    def test_custom_parent_with_p(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        vfs.mkdir("/mydir", parents=True)
        io = IOContext()
        result = cmd_mktemp(["-p", "/mydir"], state, vfs, io)
        assert result.exit_code == 0
        path = io.stdout.getvalue().strip()
        assert path.startswith("/mydir/tmp.")
        assert vfs.exists(path)

    def test_custom_parent_creates_parent(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """mktemp -p /newdir should create /newdir if it does not exist."""
        io = IOContext()
        result = cmd_mktemp(["-p", "/newdir"], state, vfs, io)
        assert result.exit_code == 0
        path = io.stdout.getvalue().strip()
        assert path.startswith("/newdir/tmp.")
        assert vfs.exists(path)

    def test_d_and_p_combined(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """mktemp -d -p /base should create a directory under /base."""
        io = IOContext()
        result = cmd_mktemp(["-d", "-p", "/base"], state, vfs, io)
        assert result.exit_code == 0
        path = io.stdout.getvalue().strip()
        assert path.startswith("/base/tmp.")
        assert vfs.is_dir(path)

    def test_unique_names(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Two calls to mktemp should produce different paths."""
        io1 = IOContext()
        io2 = IOContext()
        cmd_mktemp([], state, vfs, io1)
        cmd_mktemp([], state, vfs, io2)
        path1 = io1.stdout.getvalue().strip()
        path2 = io2.stdout.getvalue().strip()
        assert path1 != path2


# ---------------------------------------------------------------------------
# comm
# ---------------------------------------------------------------------------


class TestComm:
    """Tests for the comm command."""

    def _setup_files(
        self, vfs: VirtualFilesystem, file1_lines: list[str], file2_lines: list[str]
    ) -> tuple[str, str]:
        """Write two sorted files into the VFS and return their paths."""
        vfs.write("/a.txt", "\n".join(file1_lines).encode("utf-8"))
        vfs.write("/b.txt", "\n".join(file2_lines).encode("utf-8"))
        return "/a.txt", "/b.txt"

    def test_basic_comm(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm with two files shows three columns."""
        f1, f2 = self._setup_files(vfs, ["a", "b", "d"], ["b", "c", "d"])
        io = IOContext()
        result = cmd_comm([f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # col1 (only in file1): a
        assert "a\n" in output
        # col2 (only in file2): c (with one tab prefix)
        assert "\tc\n" in output
        # col3 (in both): b, d (with two tab prefixes)
        assert "\t\tb\n" in output
        assert "\t\td\n" in output

    def test_suppress_col1(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm -1 suppresses column 1 (lines only in file1)."""
        f1, f2 = self._setup_files(vfs, ["a", "b", "d"], ["b", "c", "d"])
        io = IOContext()
        result = cmd_comm(["-1", f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        lines = output.split("\n")
        # 'a' should not appear (it was only in file1)
        assert not any(line.strip() == "a" for line in lines)

    def test_suppress_col2(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm -2 suppresses column 2 (lines only in file2)."""
        f1, f2 = self._setup_files(vfs, ["a", "b", "d"], ["b", "c", "d"])
        io = IOContext()
        result = cmd_comm(["-2", f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        lines = output.split("\n")
        # 'c' should not appear (it was only in file2)
        assert not any("c" in line for line in lines)

    def test_suppress_col3(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm -3 suppresses column 3 (lines in both files)."""
        f1, f2 = self._setup_files(vfs, ["a", "b", "d"], ["b", "c", "d"])
        io = IOContext()
        result = cmd_comm(["-3", f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # 'b' and 'd' common lines should not appear
        # Only 'a' (col1) and 'c' (col2) should appear
        lines = [ln for ln in output.split("\n") if ln]
        stripped = [ln.strip() for ln in lines]
        assert "a" in stripped
        assert "c" in stripped
        assert "b" not in stripped
        assert "d" not in stripped

    def test_suppress_col12(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm -12 shows only lines common to both files."""
        f1, f2 = self._setup_files(vfs, ["a", "b", "d"], ["b", "c", "d"])
        io = IOContext()
        result = cmd_comm(["-12", f1, f2], state, vfs, io)
        assert result.exit_code == 0
        lines = [ln for ln in io.stdout.getvalue().split("\n") if ln]
        assert lines == ["b", "d"]

    def test_missing_operand(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_comm(["/a.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert "missing operand" in io.stderr.getvalue()

    def test_identical_files(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm on two identical files should have everything in column 3."""
        f1, f2 = self._setup_files(vfs, ["x", "y", "z"], ["x", "y", "z"])
        io = IOContext()
        result = cmd_comm([f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # All lines should be in column 3 (two tab prefixes)
        # Use rstrip to preserve leading tabs (strip would remove them)
        for line in output.rstrip("\n").split("\n"):
            assert line.startswith("\t\t")

    def test_no_overlap(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm on two files with no common lines."""
        f1, f2 = self._setup_files(vfs, ["a", "c"], ["b", "d"])
        io = IOContext()
        result = cmd_comm([f1, f2], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # No line should have double-tab prefix (col3)
        for line in output.strip().split("\n"):
            assert not line.startswith("\t\t")

    def test_file_not_found(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """comm should handle missing files gracefully."""
        vfs.write("/exists.txt", b"line1\n")
        io = IOContext()
        result = cmd_comm(["/exists.txt", "/nope.txt"], state, vfs, io)
        assert result.exit_code == 0  # comm still returns 0 per the implementation
        assert "No such file" in io.stderr.getvalue()
