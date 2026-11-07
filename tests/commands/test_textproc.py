"""Tests for text processing commands: sort, uniq, wc, cut, tr, rev, nl, paste."""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.commands.textproc import (
    cmd_cut,
    cmd_nl,
    cmd_paste,
    cmd_rev,
    cmd_sort,
    cmd_tr,
    cmd_uniq,
    cmd_wc,
)
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    return VirtualFilesystem()


@pytest.fixture
def state() -> ShellState:
    s = ShellState()
    s.cwd = "/"
    return s


@pytest.fixture
def io() -> IOContext:
    return IOContext()


def _make_io(stdin_text: str = "") -> IOContext:
    """Create an IOContext with the given stdin content."""
    ctx = IOContext()
    ctx.stdin = StringIO(stdin_text)
    return ctx


# ===================================================================
# sort
# ===================================================================


class TestSort:
    """Tests for cmd_sort."""

    def test_basic_sort(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("banana\napple\ncherry\n")
        result = cmd_sort([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "apple\nbanana\ncherry\n"

    def test_already_sorted(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\nb\nc\n")
        result = cmd_sort([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\nb\nc\n"

    def test_reverse(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("apple\nbanana\ncherry\n")
        result = cmd_sort(["-r"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "cherry\nbanana\napple\n"

    def test_numeric_sort(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("10\n2\n1\n20\n")
        result = cmd_sort(["-n"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\n2\n10\n20\n"

    def test_numeric_sort_reverse(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("10\n2\n1\n20\n")
        result = cmd_sort(["-n", "-r"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "20\n10\n2\n1\n"

    def test_numeric_sort_with_non_numeric(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("5\nabc\n3\n")
        result = cmd_sort(["-n"], state, vfs, io)
        assert result.exit_code == 0
        # Non-numeric values sort as 0.0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "abc"
        assert lines[1] == "3"
        assert lines[2] == "5"

    def test_unique(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("apple\nbanana\napple\ncherry\nbanana\n")
        result = cmd_sort(["-u"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert sorted(lines) == ["apple", "banana", "cherry"]
        # -u removes duplicates after sorting
        assert len(lines) == 3

    def test_key_field(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("b 2\na 3\nc 1\n")
        result = cmd_sort(["-k", "2"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "c 1"
        assert lines[1] == "b 2"
        assert lines[2] == "a 3"

    def test_key_field_numeric(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("x 10\ny 2\nz 1\n")
        result = cmd_sort(["-k", "2", "-n"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines == ["z 1", "y 2", "x 10"]

    def test_separator(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("b:2\na:3\nc:1\n")
        result = cmd_sort(["-t", ":", "-k", "2"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "c:1"
        assert lines[1] == "b:2"
        assert lines[2] == "a:3"

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_sort([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_single_line(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("only\n")
        result = cmd_sort([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "only\n"

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"banana\napple\ncherry\n")
        io = IOContext()
        result = cmd_sort(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "apple\nbanana\ncherry\n"

    def test_file_not_found(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_sort(["/missing.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert "No such file or directory" in io.stderr.getvalue()

    def test_key_field_out_of_range(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("a b\nc d\n")
        result = cmd_sort(["-k", "5"], state, vfs, io)
        assert result.exit_code == 0
        # Out-of-range field yields "" for all lines, order is stable-ish


# ===================================================================
# uniq
# ===================================================================


class TestUniq:
    """Tests for cmd_uniq."""

    def test_basic_dedup(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("aa\naa\nbb\nbb\ncc\n")
        result = cmd_uniq([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "aa\nbb\ncc\n"

    def test_non_adjacent_not_deduped(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("aa\nbb\naa\n")
        result = cmd_uniq([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "aa\nbb\naa\n"

    def test_count(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("aa\naa\naa\nbb\ncc\ncc\n")
        result = cmd_uniq(["-c"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert len(lines) == 3
        # Check counts are present — format is "      N line"
        assert "3 aa" in lines[0]
        assert "1 bb" in lines[1]
        assert "2 cc" in lines[2]

    def test_only_duplicates(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("aa\naa\nbb\ncc\ncc\n")
        result = cmd_uniq(["-d"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines == ["aa", "cc"]

    def test_only_unique(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("aa\naa\nbb\ncc\ncc\n")
        result = cmd_uniq(["-u"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines == ["bb"]

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_uniq([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_single_line(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("only\n")
        result = cmd_uniq([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "only\n"

    def test_all_same(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\na\na\na\n")
        result = cmd_uniq([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\n"

    def test_count_single_occurrence(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("hello\n")
        result = cmd_uniq(["-c"], state, vfs, io)
        assert result.exit_code == 0
        assert "1 hello" in io.stdout.getvalue()

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"aa\naa\nbb\n")
        io = IOContext()
        result = cmd_uniq(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "aa\nbb\n"


# ===================================================================
# wc
# ===================================================================


class TestWc:
    """Tests for cmd_wc."""

    def test_lines_only(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("line1\nline2\nline3\n")
        result = cmd_wc(["-l"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "3"

    def test_words_only(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("one two three\nfour five\n")
        result = cmd_wc(["-w"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "5"

    def test_bytes_only(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        text = "hello\n"
        io = _make_io(text)
        result = cmd_wc(["-c"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == str(len(text.encode("utf-8")))

    def test_all_together(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        text = "one two\nthree\n"
        io = _make_io(text)
        result = cmd_wc([], state, vfs, io)
        assert result.exit_code == 0
        parts = io.stdout.getvalue().strip().split()
        nlines, nwords, nbytes = int(parts[0]), int(parts[1]), int(parts[2])
        assert nlines == 2
        assert nwords == 3
        assert nbytes == len(text.encode("utf-8"))

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_wc([], state, vfs, io)
        assert result.exit_code == 0
        parts = io.stdout.getvalue().strip().split()
        assert parts == ["0", "0", "0"]

    def test_no_trailing_newline(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("hello")
        result = cmd_wc(["-l"], state, vfs, io)
        assert result.exit_code == 0
        # "hello" without newline: splitlines() gives 1 line
        assert io.stdout.getvalue().strip() == "1"

    def test_lines_and_words(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a b\nc d\n")
        result = cmd_wc(["-l", "-w"], state, vfs, io)
        assert result.exit_code == 0
        parts = io.stdout.getvalue().strip().split()
        assert parts == ["2", "4"]

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"one two\nthree\n")
        io = IOContext()
        result = cmd_wc(["-w", "/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "3"

    def test_multibyte_characters(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        # Unicode chars that are multi-byte in UTF-8
        text = "\u00e9\n"  # e-acute, 2 bytes in UTF-8
        io = _make_io(text)
        result = cmd_wc(["-c"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == str(len(text.encode("utf-8")))


# ===================================================================
# cut
# ===================================================================


class TestCut:
    """Tests for cmd_cut."""

    def test_field_selection(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\tb\tc\n")
        result = cmd_cut(["-f", "2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\n"

    def test_field_with_delimiter(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("a:b:c\nd:e:f\n")
        result = cmd_cut(["-d", ":", "-f", "2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\ne\n"

    def test_multiple_fields(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a:b:c:d\n")
        result = cmd_cut(["-d", ":", "-f", "1,3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a:c\n"

    def test_field_range(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a:b:c:d:e\n")
        result = cmd_cut(["-d", ":", "-f", "2-4"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b:c:d\n"

    def test_character_selection(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("abcdef\n")
        result = cmd_cut(["-c", "2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\n"

    def test_character_range(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abcdef\n")
        result = cmd_cut(["-c", "1-3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abc\n"

    def test_multiple_character_ranges(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("abcdef\n")
        result = cmd_cut(["-c", "1,3,5"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "ace\n"

    def test_field_out_of_range(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("a:b\n")
        result = cmd_cut(["-d", ":", "-f", "5"], state, vfs, io)
        assert result.exit_code == 0
        # Out-of-range field yields empty
        assert io.stdout.getvalue() == "\n"

    def test_multiline(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("one:two:three\nfour:five:six\n")
        result = cmd_cut(["-d", ":", "-f", "1,3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "one:three\nfour:six\n"

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_cut(["-d", ":", "-f", "1"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_inline_delimiter_flag(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Test -dX form (delimiter attached to flag)."""
        io = _make_io("a,b,c\n")
        result = cmd_cut(["-d,", "-f", "2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\n"

    def test_inline_field_flag(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Test -fN form (field attached to flag)."""
        io = _make_io("a\tb\tc\n")
        result = cmd_cut(["-f2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\n"

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"a:b:c\nd:e:f\n")
        io = IOContext()
        result = cmd_cut(["-d", ":", "-f", "2", "/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "b\ne\n"


# ===================================================================
# tr
# ===================================================================


class TestTr:
    """Tests for cmd_tr."""

    def test_basic_translate(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello")
        result = cmd_tr(["aeiou", "AEIOU"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hEllO"

    def test_translate_lower_to_upper(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("hello world\n")
        result = cmd_tr(["a-z", "A-Z"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "HELLO WORLD\n"

    def test_delete(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello world\n")
        result = cmd_tr(["-d", "aeiou"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hll wrld\n"

    def test_delete_digits(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abc123def456\n")
        result = cmd_tr(["-d", "0-9"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abcdef\n"

    def test_squeeze(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("aabbcc\n")
        result = cmd_tr(["-s", "a-z"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abc\n"

    def test_squeeze_spaces(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello    world\n")
        result = cmd_tr(["-s", " "], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello world\n"

    def test_translate_and_squeeze(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("aabbbcc\n")
        result = cmd_tr(["-s", "abc", "xyz"], state, vfs, io)
        assert result.exit_code == 0
        # Translate a->x, b->y, c->z then squeeze set2
        assert io.stdout.getvalue() == "xyz\n"

    def test_upper_class(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello\n")
        result = cmd_tr(["[:lower:]", "[:upper:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "HELLO\n"

    def test_delete_upper_class(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("Hello World\n")
        result = cmd_tr(["-d", "[:upper:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "ello orld\n"

    def test_digit_class(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abc123def\n")
        result = cmd_tr(["-d", "[:digit:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abcdef\n"

    def test_alpha_class(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abc123DEF\n")
        result = cmd_tr(["-d", "[:alpha:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "123\n"

    def test_alnum_class(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abc 123 !@#\n")
        result = cmd_tr(["-d", "[:alnum:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "  !@#\n"

    def test_space_class(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello world\there\n")
        result = cmd_tr(["-d", "[:space:]"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "helloworldhere"

    def test_escape_backslash(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\\b\\c\n")
        result = cmd_tr(["\\\\", "X"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "aXbXc\n"

    def test_escape_other(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Unrecognized escape \\x keeps the literal character x."""
        io = _make_io("axbxc\n")
        result = cmd_tr(["\\x", "Y"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "aYbYc\n"

    def test_missing_operand(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello\n")
        result = cmd_tr([], state, vfs, io)
        assert result.exit_code == 1
        assert "missing operand" in io.stderr.getvalue()

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_tr(["a-z", "A-Z"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_set2_shorter_than_set1(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """When set2 is shorter, its last char is extended."""
        io = _make_io("abc\n")
        result = cmd_tr(["abc", "x"], state, vfs, io)
        assert result.exit_code == 0
        # a->x, b->x, c->x
        assert io.stdout.getvalue() == "xxx\n"

    def test_escape_newline(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello\nworld\n")
        result = cmd_tr(["\\n", " "], state, vfs, io)
        assert result.exit_code == 0
        assert "\n" not in io.stdout.getvalue()

    def test_escape_tab(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\tb\n")
        result = cmd_tr(["\\t", " "], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a b\n"


# ===================================================================
# rev
# ===================================================================


class TestRev:
    """Tests for cmd_rev."""

    def test_basic_reverse(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello\nworld\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "olleh\ndlrow\n"

    def test_single_line(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abcdef\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "fedcba\n"

    def test_palindrome(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("racecar\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "racecar\n"

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_empty_lines(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("abc\n\ndef\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "cba\n\nfed\n"

    def test_single_char_lines(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("a\nb\nc\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\nb\nc\n"

    def test_with_spaces(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello world\n")
        result = cmd_rev([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "dlrow olleh\n"

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"abc\ndef\n")
        io = IOContext()
        result = cmd_rev(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "cba\nfed\n"


# ===================================================================
# nl
# ===================================================================


class TestNl:
    """Tests for cmd_nl."""

    def test_default_numbering(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Default -b t: number non-empty lines only."""
        io = _make_io("hello\n\nworld\n")
        result = cmd_nl([], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert len(lines) == 3
        # First line is numbered
        assert "1\thello" in lines[0]
        # Empty line is not numbered
        assert "\t" in lines[1]
        # Third line gets number 2
        assert "2\tworld" in lines[2]

    def test_number_all_lines(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("hello\n\nworld\n")
        result = cmd_nl(["-b", "a"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert "1\thello" in lines[0]
        assert "2\t" in lines[1]
        assert "3\tworld" in lines[2]

    def test_number_non_empty_only(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("a\n\nb\n\nc\n")
        result = cmd_nl(["-b", "t"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        # Only non-empty lines get numbers
        assert "1\ta" in lines[0]
        assert "2\tb" in lines[2]
        assert "3\tc" in lines[4]

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("")
        result = cmd_nl([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_single_line(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = _make_io("only\n")
        result = cmd_nl([], state, vfs, io)
        assert result.exit_code == 0
        assert "1\tonly" in io.stdout.getvalue()

    def test_numbering_increments(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("a\nb\nc\nd\ne\n")
        result = cmd_nl([], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        for i, line in enumerate(lines, 1):
            assert f"{i}\t" in line

    def test_inline_b_flag(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Test -ba form (flag value attached)."""
        io = _make_io("hello\n\nworld\n")
        result = cmd_nl(["-ba"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        # All lines including blank should be numbered
        assert "1\thello" in lines[0]
        assert "2\t" in lines[1]
        assert "3\tworld" in lines[2]

    def test_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"first\nsecond\n")
        io = IOContext()
        result = cmd_nl(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert "1\tfirst" in io.stdout.getvalue()
        assert "2\tsecond" in io.stdout.getvalue()


# ===================================================================
# paste
# ===================================================================


class TestPaste:
    """Tests for cmd_paste."""

    def test_two_files(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"1\n2\n3\n")
        vfs.write("/b.txt", b"a\nb\nc\n")
        io = IOContext()
        result = cmd_paste(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\ta\n2\tb\n3\tc\n"

    def test_custom_delimiter(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"1\n2\n3\n")
        vfs.write("/b.txt", b"a\nb\nc\n")
        io = IOContext()
        result = cmd_paste(["-d", ",", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1,a\n2,b\n3,c\n"

    def test_inline_delimiter(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Test -dX form (delimiter attached to flag)."""
        vfs.write("/a.txt", b"x\ny\n")
        vfs.write("/b.txt", b"1\n2\n")
        io = IOContext()
        result = cmd_paste(["-d|", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "x|1\ny|2\n"

    def test_unequal_length_files(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        vfs.write("/a.txt", b"1\n2\n3\n")
        vfs.write("/b.txt", b"a\n")
        io = IOContext()
        result = cmd_paste(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "1\ta"
        assert lines[1] == "2\t"
        assert lines[2] == "3\t"

    def test_three_files(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"1\n2\n")
        vfs.write("/b.txt", b"a\nb\n")
        vfs.write("/c.txt", b"x\ny\n")
        io = IOContext()
        result = cmd_paste(["/a.txt", "/b.txt", "/c.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\ta\tx\n2\tb\ty\n"

    def test_file_not_found(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"1\n2\n")
        io = IOContext()
        result = cmd_paste(["/a.txt", "/missing.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert "No such file or directory" in io.stderr.getvalue()

    def test_no_args_passthrough(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """With no arguments, paste passes through stdin."""
        io = _make_io("hello\nworld\n")
        result = cmd_paste([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello\nworld\n"

    def test_stdin_dash(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Test using '-' to read from stdin."""
        vfs.write("/a.txt", b"1\n2\n")
        io = _make_io("x\ny\n")
        result = cmd_paste(["/a.txt", "-"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "1\tx\n2\ty\n"

    def test_single_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"hello\nworld\n")
        io = IOContext()
        result = cmd_paste(["/a.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello\nworld\n"

    def test_empty_files(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"")
        vfs.write("/b.txt", b"")
        io = IOContext()
        result = cmd_paste(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""


# ===================================================================
# Cross-command integration-style tests
# ===================================================================


class TestStdinFromFile:
    """Verify that all stdin-consuming commands work from VFS files."""

    def test_sort_reads_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/input.txt", b"c\na\nb\n")
        io = IOContext()
        result = cmd_sort(["/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\nb\nc\n"

    def test_uniq_reads_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/input.txt", b"a\na\nb\n")
        io = IOContext()
        result = cmd_uniq(["/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\nb\n"

    def test_wc_reads_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/input.txt", b"one two\nthree\n")
        io = IOContext()
        result = cmd_wc(["-l", "/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "2"

    def test_rev_reads_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/input.txt", b"abc\n")
        io = IOContext()
        result = cmd_rev(["/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "cba\n"

    def test_nl_reads_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/input.txt", b"hello\nworld\n")
        io = IOContext()
        result = cmd_nl(["/input.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert "1\thello" in io.stdout.getvalue()
        assert "2\tworld" in io.stdout.getvalue()


class TestEdgeCases:
    """Edge cases and error handling across commands."""

    def test_sort_stability(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Equal-comparing lines preserve relative order (stable sort)."""
        io = _make_io("b 1\na 1\nc 1\n")
        result = cmd_sort(["-k", "2"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        # All keys are "1", so original order should be preserved
        assert lines == ["b 1", "a 1", "c 1"]

    def test_cut_no_flags(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """cut with no -f or -c just passes lines through."""
        io = _make_io("hello world\n")
        result = cmd_cut([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello world\n"

    def test_tr_only_set1_no_delete(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """tr with set1 only (no -d, no set2) passes through."""
        io = _make_io("hello\n")
        result = cmd_tr(["abc"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello\n"

    def test_uniq_count_and_duplicate(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Test -c and -d together."""
        io = _make_io("a\na\nb\nc\nc\n")
        result = cmd_uniq(["-c", "-d"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        # Only show duplicated lines, with counts
        assert len(lines) == 2
        assert "2 a" in lines[0]
        assert "2 c" in lines[1]

    def test_sort_unique_with_numeric(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = _make_io("3\n1\n2\n1\n3\n")
        result = cmd_sort(["-n", "-u"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines == ["1", "2", "3"]

    def test_sort_reads_stdin_via_dash(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Passing '-' explicitly should read from stdin."""
        io = _make_io("c\na\nb\n")
        result = cmd_sort(["-"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "a\nb\nc\n"

    def test_sort_stdin_mixed_with_file(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Using '-' among file arguments reads stdin and concatenates."""
        vfs.write("/a.txt", b"cherry\n")
        io = _make_io("apple\n")
        result = cmd_sort(["/a.txt", "-"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines == ["apple", "cherry"]

    def test_sort_directory_error(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Reading a directory should produce an error."""
        vfs.mkdir("/mydir")
        io = IOContext()
        result = cmd_sort(["/mydir"], state, vfs, io)
        assert result.exit_code == 1
        assert "Is a directory" in io.stderr.getvalue()

    def test_cut_inline_char_flag(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Test -cN form (chars attached to flag)."""
        io = _make_io("abcdef\n")
        result = cmd_cut(["-c1-3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "abc\n"

    def test_sort_key_with_comma_spec(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Key spec like '2,2' should use field 2."""
        io = _make_io("b 2\na 3\nc 1\n")
        result = cmd_sort(["-k", "2,2"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "c 1"

    def test_sort_key_with_dot_spec(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Key spec like '2.1' should use field 2."""
        io = _make_io("b 2\na 3\nc 1\n")
        result = cmd_sort(["-k", "2.1"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().splitlines()
        assert lines[0] == "c 1"

    def test_sort_key_invalid_value(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Invalid key spec should not crash (ValueError handled)."""
        io = _make_io("b\na\n")
        result = cmd_sort(["-k", "abc"], state, vfs, io)
        assert result.exit_code == 0
        # key_field stays None, falls back to full-line sort
        assert io.stdout.getvalue() == "a\nb\n"
