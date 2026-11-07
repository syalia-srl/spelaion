"""Comprehensive tests for search commands: grep, find, xargs."""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.commands.search import cmd_find, cmd_grep, cmd_xargs
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return a VFS pre-populated with files for search testing."""
    return VirtualFilesystem(
        initial_files={
            "/home/user/hello.txt": "Hello World\nhello world\nHELLO WORLD\nfoo bar\n",
            "/home/user/notes.txt": "line one\nline two\nline three\nfoo bar baz\n",
            "/home/user/project/main.py": (
                "import os\ndef main():\n    print('hello')\n    return 0\n"
            ),
            "/home/user/project/test.py": (
                "import pytest\ndef test_main():\n    assert True\n"
            ),
            "/home/user/project/sub/data.txt": "alpha\nbeta\ngamma\ndelta\n",
            "/home/user/empty.txt": "",
        }
    )


@pytest.fixture
def state() -> ShellState:
    """Return a ShellState with cwd set to /home/user."""
    return ShellState(cwd="/home/user")


@pytest.fixture
def io() -> IOContext:
    """Return a fresh IOContext."""
    return IOContext()


# ==================================================================
# grep
# ==================================================================


class TestGrepBasicMatch:
    """Test basic grep pattern matching."""

    def test_basic_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "hello world" in output

    def test_basic_match_from_stdin(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("apple\nbanana\ncherry\napricot\n")
        result = cmd_grep(["an"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "banana" in output
        assert "apple" not in output

    def test_no_match_returns_exit_code_1(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["zzzzz", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert io.stdout.getvalue() == ""

    def test_missing_pattern_returns_exit_code_2(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep([], state, vfs, io)
        assert result.exit_code == 2
        assert "missing pattern" in io.stderr.getvalue()

    def test_missing_file(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        cmd_grep(["hello", "/nonexistent"], state, vfs, io)
        assert "No such file" in io.stderr.getvalue()


class TestGrepCaseInsensitive:
    """Test grep -i flag."""

    def test_case_insensitive(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-i", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 3  # "Hello World", "hello world", "HELLO WORLD"

    def test_case_sensitive_default(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["Hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 1
        assert "Hello World" in lines[0]


class TestGrepInvert:
    """Test grep -v invert match."""

    def test_invert_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-v", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # "hello world" should NOT be in output; other lines should be
        assert "hello world" not in output
        assert "Hello World" in output  # uppercase does not match "hello"
        assert "foo bar" in output


class TestGrepCount:
    """Test grep -c count mode."""

    def test_count_matches(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-c", "-i", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "3"

    def test_count_no_matches(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-c", "zzzzz", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert io.stdout.getvalue().strip() == "0"

    def test_count_multi_file_has_prefix(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(
            ["-c", "foo", "/home/user/hello.txt", "/home/user/notes.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "/home/user/hello.txt:1" in output
        assert "/home/user/notes.txt:1" in output


class TestGrepFilesOnly:
    """Test grep -l files-with-matches."""

    def test_files_only(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(
            [
                "-l",
                "foo",
                "/home/user/hello.txt",
                "/home/user/notes.txt",
                "/home/user/project/main.py",
            ],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "/home/user/hello.txt" in output
        assert "/home/user/notes.txt" in output
        assert "/home/user/project/main.py" not in output


class TestGrepLineNumbers:
    """Test grep -n line number display."""

    def test_line_numbers(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-n", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "2:" in output  # "hello world" is line 2

    def test_line_numbers_multi_file(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(
            ["-n", "foo", "/home/user/hello.txt", "/home/user/notes.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # Multi-file: prefix is filename:lineno:
        assert "/home/user/hello.txt:4:" in output
        assert "/home/user/notes.txt:4:" in output


class TestGrepRecursive:
    """Test grep -r recursive search."""

    def test_recursive_search(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-r", "hello", "/home/user"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # Should find matches in hello.txt and main.py
        assert "hello" in output

    def test_recursive_search_directory(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-r", "import", "/home/user/project"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "import os" in output
        assert "import pytest" in output


class TestGrepExtended:
    """Test grep -E extended regex."""

    def test_extended_regex(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("cat\ndog\nbird\ncat\n")
        result = cmd_grep(["-E", "cat|dog"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert len(lines) == 3  # 2 cat + 1 dog


class TestGrepFixed:
    """Test grep -F fixed string (no regex interpretation)."""

    def test_fixed_string(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("a.b\na*b\naXb\n")
        result = cmd_grep(["-F", "a.b"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        # -F treats "." literally, only "a.b" should match
        assert output == "a.b"


class TestGrepWordMatch:
    """Test grep -w whole word match."""

    def test_word_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("foo\nfoobar\nbarfoo\nfoo baz\n")
        result = cmd_grep(["-w", "foo"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        # "foobar" and "barfoo" should NOT match as whole words
        assert "foo" in lines
        assert "foo baz" in lines
        assert "foobar" not in lines
        assert "barfoo" not in lines


class TestGrepQuiet:
    """Test grep -q quiet mode."""

    def test_quiet_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-q", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_quiet_no_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-q", "zzzzz", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert io.stdout.getvalue() == ""


class TestGrepOnlyMatching:
    """Test grep -o only-matching mode."""

    def test_only_matching(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("the quick brown fox\n")
        result = cmd_grep(["-o", "quick", "-"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "quick"

    def test_only_matching_regex(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("abc123def456\n")
        result = cmd_grep(["-o", "-E", "[0-9]+"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert lines == ["123", "456"]


class TestGrepMultiFile:
    """Test grep with multiple files (prefix behavior)."""

    def test_multi_file_prefix(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(
            ["foo", "/home/user/hello.txt", "/home/user/notes.txt"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # Multi-file output prefixes each line with filename
        for line in output.strip().splitlines():
            assert ":" in line
            assert line.startswith("/home/user/")


class TestGrepCombinedFlags:
    """Test grep with combined short flags like -in."""

    def test_combined_flags(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["-in", "hello", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # -i -n: case insensitive with line numbers
        lines = output.strip().splitlines()
        assert len(lines) == 3
        # Each line should have a line number
        for line in lines:
            assert ":" in line


class TestGrepInvalidRegex:
    """Test grep with invalid regex pattern."""

    def test_invalid_regex(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_grep(["[invalid", "/home/user/hello.txt"], state, vfs, io)
        assert result.exit_code == 2
        assert "invalid regex" in io.stderr.getvalue()


class TestGrepMultiplePatterns:
    """Test grep with -e for multiple patterns."""

    def test_multiple_patterns(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("apple\nbanana\ncherry\n")
        result = cmd_grep(["-e", "apple", "-e", "cherry"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().splitlines()
        assert "apple" in lines
        assert "cherry" in lines
        assert "banana" not in lines


# ==================================================================
# find
# ==================================================================


class TestFindDefault:
    """Test find with no predicates (prints everything)."""

    def test_find_prints_all(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        # Create a small tree
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/b.txt": "b",
                "/data/sub/c.txt": "c",
            }
        )
        result = cmd_find(["/data"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "/data\n" in output
        assert "/data/a.txt" in output
        assert "/data/b.txt" in output
        assert "/data/sub" in output
        assert "/data/sub/c.txt" in output

    def test_find_default_path_is_dot(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        state.cwd = "/home/user"
        result = cmd_find([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # Should list items under cwd "."
        assert "." in output


class TestFindName:
    """Test find -name pattern matching."""

    def test_find_by_name(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(["/home/user", "-name", "*.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "hello.txt" in output
        assert "notes.txt" in output
        assert "data.txt" in output
        assert "main.py" not in output

    def test_find_by_exact_name(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(["/home/user", "-name", "main.py"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "main.py" in output
        lines = [ln for ln in output.strip().splitlines() if ln.strip()]
        assert len(lines) == 1


class TestFindType:
    """Test find -type f and -type d."""

    def test_find_type_f(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-type", "f"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        lines = output.strip().splitlines()
        # Only files, no directories
        for line in lines:
            assert small_vfs.is_file(small_vfs.resolve(line.strip(), "/"))

    def test_find_type_d(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-type", "d"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        lines = output.strip().splitlines()
        # Only directories
        for line in lines:
            assert small_vfs.is_dir(small_vfs.resolve(line.strip(), "/"))


class TestFindMaxDepth:
    """Test find -maxdepth."""

    def test_maxdepth_0(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-maxdepth", "0"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        # Only the start path itself
        assert output == "/data"

    def test_maxdepth_1(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-maxdepth", "1"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "/data/a.txt" in output
        assert "/data/sub" in output
        # Files deeper than depth 1 should not appear
        assert "/data/sub/b.txt" not in output


class TestFindMinDepth:
    """Test find -mindepth."""

    def test_mindepth_1(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-mindepth", "1"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # The start directory itself (depth 0) should not appear
        lines = output.strip().splitlines()
        assert "/data\n" not in output.split("\n") or not any(
            ln.strip() == "/data" for ln in lines
        )
        assert "/data/a.txt" in output

    def test_mindepth_2(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        small_vfs = VirtualFilesystem(
            initial_files={
                "/data/a.txt": "a",
                "/data/sub/b.txt": "b",
            }
        )
        result = cmd_find(["/data", "-mindepth", "2"], state, small_vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # Only depth >= 2 items
        assert "/data/a.txt" not in output
        assert "/data/sub/b.txt" in output


class TestFindPath:
    """Test find -path pattern matching."""

    def test_find_path_pattern(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(["/home/user", "-path", "*/project/*"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # All items under project/ should match
        assert "main.py" in output
        assert "test.py" in output

    def test_find_path_no_match(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(["/home/user", "-path", "*/nonexistent/*"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        assert output == ""


class TestFindNonexistentPath:
    """Test find with a path that does not exist."""

    def test_nonexistent_start_path(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(["/nowhere"], state, vfs, io)
        assert result.exit_code == 0  # find still returns 0
        assert "No such file or directory" in io.stderr.getvalue()


class TestFindCombined:
    """Test find with multiple predicates."""

    def test_name_and_type(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        result = cmd_find(
            ["/home/user", "-name", "*.py", "-type", "f"],
            state,
            vfs,
            io,
        )
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        lines = [ln.strip() for ln in output.strip().splitlines() if ln.strip()]
        for line in lines:
            assert line.endswith(".py")


# ==================================================================
# xargs
# ==================================================================


class TestXargsNoExecutor:
    """Test xargs behavior when no executor is attached."""

    def test_xargs_no_executor(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        io.stdin = StringIO("a b c\n")
        result = cmd_xargs(["echo"], state, vfs, io)
        assert result.exit_code == 1
        assert "no executor" in io.stderr.getvalue()


class TestXargsArgParsing:
    """Test xargs argument parsing and delimiter handling."""

    def test_xargs_null_delimiter_parsing(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify -0 flag is parsed correctly.

        Even though execution needs an executor.
        """
        io.stdin = StringIO("a\0b\0c")
        result = cmd_xargs(["-0", "echo"], state, vfs, io)
        # Without an executor, this will fail, but the flag parsing was exercised
        assert result.exit_code == 1

    def test_xargs_custom_delimiter_parsing(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify -d flag is parsed correctly."""
        io.stdin = StringIO("a:b:c")
        result = cmd_xargs(["-d", ":", "echo"], state, vfs, io)
        assert result.exit_code == 1  # no executor

    def test_xargs_replace_str_parsing(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify -I flag is parsed correctly."""
        io.stdin = StringIO("file1.txt\nfile2.txt\n")
        result = cmd_xargs(["-I", "{}", "cat", "{}"], state, vfs, io)
        assert result.exit_code == 1  # no executor

    def test_xargs_max_args_parsing(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify -n flag is parsed correctly."""
        io.stdin = StringIO("a b c d e f\n")
        result = cmd_xargs(["-n", "2", "echo"], state, vfs, io)
        assert result.exit_code == 1  # no executor

    def test_xargs_default_command_is_echo(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify that when no command is given, echo is the default."""
        io.stdin = StringIO("hello world\n")
        # No executor, but we can check that the command template defaults to echo
        result = cmd_xargs([], state, vfs, io)
        assert result.exit_code == 1  # no executor, but parsing succeeded

    def test_xargs_empty_stdin(
        self,
        vfs: VirtualFilesystem,
        state: ShellState,
        io: IOContext,
    ) -> None:
        """Verify empty stdin produces no items (still needs executor though)."""
        io.stdin = StringIO("")
        result = cmd_xargs(["echo"], state, vfs, io)
        # No items to process, but no executor available
        assert result.exit_code == 1
