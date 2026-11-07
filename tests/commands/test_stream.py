"""Comprehensive tests for stream processing commands: sed, awk."""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.commands.stream import cmd_awk, cmd_sed
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return a VFS pre-populated with files for stream testing."""
    return VirtualFilesystem(
        initial_files={
            "/data/input.txt": "hello world\nfoo bar\nbaz qux\n",
            "/data/numbers.txt": "one 1\ntwo 2\nthree 3\nfour 4\nfive 5\n",
            "/data/csv.txt": (
                "name,age,city\nalice,30,paris\nbob,25,london\ncharlie,35,tokyo\n"
            ),
            "/data/log.txt": (
                "INFO: started\nERROR: failed\n"
                "INFO: running\nWARN: slow\nERROR: crash\n"
            ),
        }
    )


@pytest.fixture
def state() -> ShellState:
    """Return a ShellState with cwd set to /data."""
    return ShellState(cwd="/data")


@pytest.fixture
def io() -> IOContext:
    """Return a fresh IOContext."""
    return IOContext()


# ==================================================================
# sed
# ==================================================================


class TestSedBasicSubstitution:
    """Test sed s/pattern/replacement/ basic substitution."""

    def test_basic_substitute(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_sed(["s/hello/goodbye/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "goodbye world\n"

    def test_substitute_first_occurrence_only(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("aaa bbb aaa\n")
        result = cmd_sed(["s/aaa/xxx/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "xxx bbb aaa\n"

    def test_substitute_no_match_passes_through(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_sed(["s/zzz/yyy/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello world\n"

    def test_substitute_regex_pattern(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("abc123def\n")
        result = cmd_sed(["s/[0-9]+/NUM/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abcNUMdef\n"


class TestSedGlobalSubstitution:
    """Test sed s///g global flag."""

    def test_global_substitute(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("aaa bbb aaa\n")
        result = cmd_sed(["s/aaa/xxx/g"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "xxx bbb xxx\n"

    def test_global_substitute_multiple_lines(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("foo bar foo\nbaz foo baz\n")
        result = cmd_sed(["s/foo/XXX/g"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "XXX bar XXX" in output
        assert "baz XXX baz" in output


class TestSedSuppressAndPrint:
    """Test sed -n suppress + /pattern/p."""

    def test_suppress_with_pattern_print(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("apple\nbanana\ncherry\napricot\n")
        result = cmd_sed(["-n", "/^a/p"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["apple", "apricot"]

    def test_suppress_without_print_produces_no_output(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello\nworld\n")
        result = cmd_sed(["-n", "s/hello/goodbye/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_suppress_with_substitute_p_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\nfoo bar\nhello there\n")
        result = cmd_sed(["-n", "s/hello/goodbye/p"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "goodbye world" in lines[0]
        assert "goodbye there" in lines[1]


class TestSedAddressLines:
    """Test sed address expressions (line numbers, regex)."""

    def test_line_number_delete(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("line1\nline2\nline3\nline4\n")
        result = cmd_sed(["2d"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["line1", "line3", "line4"]

    def test_regex_address_delete(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("keep this\ndelete THIS\nkeep that\ndelete THAT\n")
        result = cmd_sed(["/delete/d"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["keep this", "keep that"]

    def test_last_line_address(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("first\nsecond\nlast\n")
        result = cmd_sed(["$d"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["first", "second"]

    def test_address_with_substitution(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("line1\nline2\nline3\n")
        result = cmd_sed(["2s/line/LINE/"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["line1", "LINE2", "line3"]


class TestSedInPlace:
    """Test sed -i in-place editing."""

    def test_in_place_edit(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_sed(
            ["-i", "s/hello/goodbye/", "/data/input.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        content = vfs.read("/data/input.txt").decode()
        assert "goodbye world" in content
        assert "hello world" not in content
        # stdout should be empty for in-place edit
        assert io.stdout.getvalue() == ""

    def test_in_place_edit_preserves_unmatched_lines(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_sed(
            ["-i", "s/foo/FOO/", "/data/input.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        content = vfs.read("/data/input.txt").decode()
        assert "hello world" in content
        assert "FOO bar" in content
        assert "baz qux" in content


class TestSedMultipleScripts:
    """Test sed with multiple -e scripts."""

    def test_multiple_e_scripts(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_sed(
            ["-e", "s/hello/goodbye/", "-e", "s/world/earth/"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "goodbye earth\n"

    def test_semicolon_separated_commands(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_sed(["s/hello/goodbye/;s/world/earth/"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "goodbye earth\n"


class TestSedQuit:
    """Test sed q (quit) command."""

    def test_quit_after_first_line(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("first\nsecond\nthird\n")
        result = cmd_sed(["1q"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        assert output == "first"

    def test_quit_after_pattern(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alpha\nbeta\ngamma\ndelta\n")
        result = cmd_sed(["/beta/q"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["alpha", "beta"]


class TestSedNoScript:
    """Test sed error when no script given."""

    def test_no_script_error(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_sed([], state, vfs, io)
        assert result.exit_code == 2
        assert "no script given" in io.stderr.getvalue()


class TestSedFileInput:
    """Test sed reading from file arguments."""

    def test_read_from_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_sed(["s/foo/FOO/", "/data/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "hello world" in output
        assert "FOO bar" in output

    def test_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_sed(["s/a/b/", "/data/nonexistent.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert "No such file" in io.stderr.getvalue()


class TestSedAlternateDelimiters:
    """Test sed with non-slash delimiters in s command."""

    def test_alternate_delimiter(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("/usr/local/bin\n")
        result = cmd_sed(["s|/usr/local|/opt|"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "/opt/bin\n"

    def test_hash_delimiter(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_sed(["s#hello#goodbye#"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "goodbye world\n"


# ==================================================================
# awk
# ==================================================================


class TestAwkBasicPrint:
    """Test awk basic print statements."""

    def test_print_first_field(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\nfoo bar\n")
        result = cmd_awk(["{print $1}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["hello", "foo"]

    def test_print_second_field(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\nfoo bar\n")
        result = cmd_awk(["{print $2}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["world", "bar"]

    def test_print_whole_line(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\nfoo bar\n")
        result = cmd_awk(["{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["hello world", "foo bar"]

    def test_print_whole_line_implicit(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\nfoo bar\n")
        result = cmd_awk(["{print}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["hello world", "foo bar"]

    def test_print_nonexistent_field(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_awk(["{print $5}"], state, vfs, io)
        assert result.exit_code == 0
        # Non-existent field should be empty string
        output = io.stdout.getvalue().strip()
        assert output == ""


class TestAwkFieldSeparator:
    """Test awk -F field separator."""

    def test_comma_separator(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alice,30,paris\nbob,25,london\n")
        result = cmd_awk(["-F", ",", "{print $1}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["alice", "bob"]

    def test_colon_separator(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("root:0:root\nuser:1000:user\n")
        result = cmd_awk(["-F", ":", "{print $1, $2}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["root 0", "user 1000"]

    def test_separator_attached_to_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a:b:c\n")
        result = cmd_awk(["-F:", "{print $2}"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "b"

    def test_tab_separator(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("name\tage\tcity\nalice\t30\tparis\n")
        result = cmd_awk(["-F", "\t", "{print $2}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["age", "30"]


class TestAwkBeginEnd:
    """Test awk BEGIN and END blocks."""

    def test_begin_block(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a\nb\n")
        result = cmd_awk(['BEGIN{print "header"} {print $0}'], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[0] == "header"
        assert "a" in lines
        assert "b" in lines

    def test_end_block(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a\nb\n")
        result = cmd_awk(['{print $0} END{print "footer"}'], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[-1] == "footer"

    def test_begin_and_end(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("x\ny\n")
        result = cmd_awk(
            ['BEGIN{print "start"} {print $0} END{print "done"}'],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[0] == "start"
        assert lines[-1] == "done"


class TestAwkNRNF:
    """Test awk NR and NF built-in variables."""

    def test_nr_variable(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alpha\nbeta\ngamma\n")
        result = cmd_awk(["{print NR, $0}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[0] == "1 alpha"
        assert lines[1] == "2 beta"
        assert lines[2] == "3 gamma"

    def test_nf_variable(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a b c\nd e\nf\n")
        result = cmd_awk(["{print NF}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["3", "2", "1"]


class TestAwkConditions:
    """Test awk condition expressions."""

    def test_nr_equals(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("line1\nline2\nline3\n")
        result = cmd_awk(["NR==2{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "line2"

    def test_field_equals_string(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alice 30\nbob 25\ncharlie 35\n")
        result = cmd_awk(['$1=="bob"{print $0}'], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "bob 25"

    def test_numeric_comparison(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alice 30\nbob 25\ncharlie 35\n")
        result = cmd_awk(["$2>28{print $1}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert "alice" in lines
        assert "charlie" in lines
        assert "bob" not in lines

    def test_nr_greater_than(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a\nb\nc\nd\n")
        result = cmd_awk(["NR>2{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["c", "d"]


class TestAwkRegexPatterns:
    """Test awk /regex/ patterns."""

    def test_regex_pattern(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("INFO: started\nERROR: failed\nINFO: running\nWARN: slow\n")
        result = cmd_awk(["/ERROR/{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "ERROR: failed"

    def test_regex_pattern_multiple_matches(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("INFO: started\nERROR: failed\nINFO: running\nWARN: slow\n")
        result = cmd_awk(["/INFO/{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert lines[0] == "INFO: started"
        assert lines[1] == "INFO: running"

    def test_no_pattern_matches_all(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a\nb\nc\n")
        result = cmd_awk(["{print $0}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["a", "b", "c"]


class TestAwkPrintWithComma:
    """Test awk print with comma (OFS)."""

    def test_comma_uses_ofs(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello world\n")
        result = cmd_awk(["{print $1, $2}"], state, vfs, io)
        assert result.exit_code == 0
        # Default OFS is space
        assert io.stdout.getvalue().strip() == "hello world"

    def test_multiple_fields_with_comma(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a b c d\n")
        result = cmd_awk(["{print $1, $3}"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "a c"


class TestAwkVariableAssignment:
    """Test awk -v variable assignment."""

    def test_v_flag_variable(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("hello\nworld\n")
        result = cmd_awk(
            ["-v", "prefix=>>", "{print prefix, $0}"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[0] == ">> hello"
        assert lines[1] == ">> world"

    def test_multiple_v_flags(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("test\n")
        result = cmd_awk(
            ["-v", "a=hello", "-v", "b=world", "{print a, b}"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "hello world"


class TestAwkFileInput:
    """Test awk reading from file arguments."""

    def test_read_from_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_awk(
            ["-F", ",", "{print $1}", "/data/csv.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["name", "alice", "bob", "charlie"]

    def test_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        cmd_awk(["{print $0}", "/data/nonexistent.txt"], state, vfs, io)
        assert "No such file" in io.stderr.getvalue()


class TestAwkMissingProgram:
    """Test awk error when no program given."""

    def test_no_program_error(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_awk([], state, vfs, io)
        assert result.exit_code == 2
        assert "missing program" in io.stderr.getvalue()


class TestAwkStringLiterals:
    """Test awk print with string literals."""

    def test_print_string_literal(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alice\nbob\n")
        result = cmd_awk(['{print "name:", $1}'], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines[0] == "name: alice"
        assert lines[1] == "name: bob"


class TestAwkNRTotal:
    """Test awk NR in END block for total line count."""

    def test_nr_in_end(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a\nb\nc\nd\n")
        result = cmd_awk(["END{print NR}"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "4"


class TestAwkFieldSeparatorFromFile:
    """Test awk with -F on file input (csv)."""

    def test_csv_processing(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = cmd_awk(
            ["-F", ",", "NR>1{print $1, $3}", "/data/csv.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["alice paris", "bob london", "charlie tokyo"]


class TestAwkNotEqual:
    """Test awk != comparison."""

    def test_not_equal(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("alice 30\nbob 25\ncharlie 35\n")
        result = cmd_awk(['$1!="bob"{print $0}'], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 2
        assert "bob" not in lines[0]
        assert "bob" not in lines[1]


class TestAwkLessThanEqual:
    """Test awk <= and >= comparisons."""

    def test_less_than_equal(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a 10\nb 20\nc 30\n")
        result = cmd_awk(["$2<=20{print $1}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["a", "b"]

    def test_greater_than_equal(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("a 10\nb 20\nc 30\n")
        result = cmd_awk(["$2>=20{print $1}"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["b", "c"]
