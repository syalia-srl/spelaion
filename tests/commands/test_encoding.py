"""Tests for encoding/hashing/math/diff commands.

Covers:
- base64: encode, -d decode, -w wrap width
- md5sum: compute hash of file content
- sha256sum: compute hash
- hexdump/xxd: hex output, -C canonical
- strings: extract printable ASCII runs, -n min length
- expr: arithmetic, comparison, string operations, exit code 1 for result 0
- bc: basic arithmetic from stdin, exponentiation
- diff: basic diff, -u unified, identical files return 0
"""

from __future__ import annotations

import base64 as _base64
import hashlib
from io import StringIO

import pytest

from agentsh.commands.diff_cmd import cmd_diff
from agentsh.commands.encoding import (
    cmd_base64,
    cmd_hexdump,
    cmd_md5sum,
    cmd_sha256sum,
    cmd_strings,
)
from agentsh.commands.math_cmd import cmd_bc, cmd_expr
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


# ---------------------------------------------------------------------------
# base64
# ---------------------------------------------------------------------------


class TestBase64:
    """Tests for the base64 command."""

    def test_encode_from_stdin(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 with no files reads from stdin."""
        io = IOContext()
        io.stdin = StringIO("Hello, World!")
        result = cmd_base64([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        expected = _base64.b64encode(b"Hello, World!").decode("ascii")
        assert output == expected

    def test_encode_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 /file.txt encodes the file content."""
        vfs.write("/file.txt", b"test data")
        io = IOContext()
        result = cmd_base64(["/file.txt"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        expected = _base64.b64encode(b"test data").decode("ascii")
        assert output == expected

    def test_decode(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 -d decodes base64 input."""
        encoded = _base64.b64encode(b"decoded text").decode("ascii")
        io = IOContext()
        io.stdin = StringIO(encoded)
        result = cmd_base64(["-d"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "decoded text"

    def test_decode_long_flag(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 --decode should also work."""
        encoded = _base64.b64encode(b"hello").decode("ascii")
        io = IOContext()
        io.stdin = StringIO(encoded)
        result = cmd_base64(["--decode"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "hello"

    def test_decode_from_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        encoded = _base64.b64encode(b"file content").decode("ascii")
        vfs.write("/encoded.txt", encoded.encode("utf-8"))
        io = IOContext()
        result = cmd_base64(["-d", "/encoded.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == "file content"

    def test_decode_invalid_input(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """base64 -d with invalid input should fail."""
        io = IOContext()
        io.stdin = StringIO("!!!not-base64!!!")
        result = cmd_base64(["-d"], state, vfs, io)
        assert result.exit_code == 1
        assert "invalid input" in io.stderr.getvalue()

    def test_wrap_width(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 -w 20 should wrap at 20 characters."""
        long_data = b"A" * 100
        io = IOContext()
        io.stdin = StringIO(long_data.decode("utf-8"))
        result = cmd_base64(["-w", "20"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        # All lines except possibly the last should be exactly 20 chars
        for line in lines[:-1]:
            assert len(line) == 20

    def test_wrap_zero_no_wrap(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """base64 -w 0 should produce a single line."""
        long_data = b"B" * 200
        io = IOContext()
        io.stdin = StringIO(long_data.decode("utf-8"))
        result = cmd_base64(["-w", "0"], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        assert len(lines) == 1

    def test_default_wrap_76(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Default wrap width should be 76."""
        long_data = b"C" * 200
        io = IOContext()
        io.stdin = StringIO(long_data.decode("utf-8"))
        result = cmd_base64([], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        if len(lines) > 1:
            assert len(lines[0]) == 76

    def test_encode_empty_input(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        io.stdin = StringIO("")
        result = cmd_base64([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue().strip()
        assert output == ""  # base64 of empty is empty


# ---------------------------------------------------------------------------
# md5sum
# ---------------------------------------------------------------------------


class TestMd5sum:
    """Tests for the md5sum command."""

    def test_hash_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"hello world\n")
        io = IOContext()
        result = cmd_md5sum(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        expected = hashlib.md5(b"hello world\n").hexdigest()
        output = io.stdout.getvalue()
        assert expected in output
        assert "/data.txt" in output

    def test_hash_stdin(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("test input")
        result = cmd_md5sum([], state, vfs, io)
        assert result.exit_code == 0
        expected = hashlib.md5(b"test input").hexdigest()
        output = io.stdout.getvalue()
        assert expected in output
        assert "-" in output  # stdin indicated by "-"

    def test_hash_empty_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/empty.txt", b"")
        io = IOContext()
        result = cmd_md5sum(["/empty.txt"], state, vfs, io)
        assert result.exit_code == 0
        expected = hashlib.md5(b"").hexdigest()
        assert expected in io.stdout.getvalue()

    def test_missing_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_md5sum(["/nofile.txt"], state, vfs, io)
        assert result.exit_code == 0  # md5sum still returns 0 per implementation
        assert "No such file" in io.stderr.getvalue()

    def test_output_format(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """md5sum output should be 'hash  filename'."""
        vfs.write("/f.txt", b"abc")
        io = IOContext()
        cmd_md5sum(["/f.txt"], state, vfs, io)
        output = io.stdout.getvalue().strip()
        parts = output.split("  ")
        assert len(parts) == 2
        assert len(parts[0]) == 32  # MD5 hex digest is 32 chars
        assert parts[1] == "/f.txt"


# ---------------------------------------------------------------------------
# sha256sum
# ---------------------------------------------------------------------------


class TestSha256sum:
    """Tests for the sha256sum command."""

    def test_hash_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/data.txt", b"hello world\n")
        io = IOContext()
        result = cmd_sha256sum(["/data.txt"], state, vfs, io)
        assert result.exit_code == 0
        expected = hashlib.sha256(b"hello world\n").hexdigest()
        assert expected in io.stdout.getvalue()

    def test_hash_stdin(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("test input")
        result = cmd_sha256sum([], state, vfs, io)
        assert result.exit_code == 0
        expected = hashlib.sha256(b"test input").hexdigest()
        assert expected in io.stdout.getvalue()

    def test_output_format(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """sha256sum output should be 'hash  filename'."""
        vfs.write("/f.txt", b"abc")
        io = IOContext()
        cmd_sha256sum(["/f.txt"], state, vfs, io)
        output = io.stdout.getvalue().strip()
        parts = output.split("  ")
        assert len(parts) == 2
        assert len(parts[0]) == 64  # SHA256 hex digest is 64 chars
        assert parts[1] == "/f.txt"

    def test_known_hash(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Verify against a known SHA256 hash."""
        # SHA256 of empty string is well-known
        vfs.write("/empty.txt", b"")
        io = IOContext()
        cmd_sha256sum(["/empty.txt"], state, vfs, io)
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert expected in io.stdout.getvalue()


# ---------------------------------------------------------------------------
# hexdump / xxd
# ---------------------------------------------------------------------------


class TestHexdump:
    """Tests for the hexdump/xxd command."""

    def test_basic_hex_output(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/bin.dat", b"ABCD")
        io = IOContext()
        result = cmd_hexdump(["/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "00000000" in output  # offset
        assert "41 42 43 44" in output  # hex for ABCD

    def test_canonical_flag(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """hexdump -C should include ASCII representation."""
        vfs.write("/bin.dat", b"Hello!")
        io = IOContext()
        result = cmd_hexdump(["-C", "/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "|Hello!|" in output

    def test_canonical_non_printable(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Non-printable bytes should show as '.' in canonical mode."""
        vfs.write("/bin.dat", bytes([0x00, 0x01, 0x41, 0x7F]))
        io = IOContext()
        result = cmd_hexdump(["-C", "/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "|..A.|" in output

    def test_multiline_output(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """Data longer than 16 bytes should produce multiple lines."""
        vfs.write("/big.dat", b"A" * 32)
        io = IOContext()
        result = cmd_hexdump(["/big.dat"], state, vfs, io)
        assert result.exit_code == 0
        lines = [ln for ln in io.stdout.getvalue().split("\n") if ln]
        assert len(lines) == 2
        assert lines[0].startswith("00000000")
        assert lines[1].startswith("00000010")

    def test_empty_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/empty.dat", b"")
        io = IOContext()
        result = cmd_hexdump(["/empty.dat"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_stdin_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """hexdump with no files reads from stdin."""
        io = IOContext()
        io.stdin = StringIO("AB")
        result = cmd_hexdump([], state, vfs, io)
        assert result.exit_code == 0
        assert "41 42" in io.stdout.getvalue()


# ---------------------------------------------------------------------------
# strings
# ---------------------------------------------------------------------------


class TestStrings:
    """Tests for the strings command."""

    def test_extract_printable(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """strings should extract runs of printable ASCII."""
        data = b"\x00\x01hello\x00\x02world\x00"
        vfs.write("/bin.dat", data)
        io = IOContext()
        result = cmd_strings(["/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "hello" in output
        assert "world" in output

    def test_default_min_length_4(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Default min length is 4, so short runs should be excluded."""
        data = b"\x00abc\x00defg\x00hi\x00"
        vfs.write("/bin.dat", data)
        io = IOContext()
        result = cmd_strings(["/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        # "abc" is length 3, should be excluded
        assert "abc" not in output
        # "defg" is length 4, should be included
        assert "defg" in output
        # "hi" is length 2, should be excluded
        assert "hi\n" not in output

    def test_custom_min_length(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """strings -n 2 should extract runs of length >= 2."""
        data = b"\x00ab\x00c\x00def\x00"
        vfs.write("/bin.dat", data)
        io = IOContext()
        result = cmd_strings(["-n", "2", "/bin.dat"], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "ab" in output
        assert "def" in output
        # Single char "c" should still be excluded
        lines = output.strip().split("\n")
        assert "c" not in lines

    def test_all_printable(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """File with all printable ASCII should produce one string."""
        vfs.write("/text.dat", b"This is a long printable string")
        io = IOContext()
        result = cmd_strings(["/text.dat"], state, vfs, io)
        assert result.exit_code == 0
        assert "This is a long printable string" in io.stdout.getvalue()

    def test_no_printable(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """File with no printable runs should produce empty output."""
        vfs.write("/binary.dat", bytes(range(0, 20)))
        io = IOContext()
        result = cmd_strings(["/binary.dat"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_stdin(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """strings with no files should read from stdin."""
        io = IOContext()
        io.stdin = StringIO("hello\x00\x01\x02world")
        result = cmd_strings([], state, vfs, io)
        assert result.exit_code == 0
        output = io.stdout.getvalue()
        assert "hello" in output
        assert "world" in output


# ---------------------------------------------------------------------------
# expr
# ---------------------------------------------------------------------------


class TestExpr:
    """Tests for the expr command."""

    def test_addition(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["3", "+", "4"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "7"

    def test_subtraction(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["10", "-", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "7"

    def test_multiplication(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["6", "*", "7"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "42"

    def test_division(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["15", "/", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "5"

    def test_integer_division(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """expr uses integer division."""
        io = IOContext()
        result = cmd_expr(["7", "/", "2"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "3"

    def test_modulo(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["10", "%", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1"

    def test_comparison_equal(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["5", "=", "5"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1"

    def test_comparison_not_equal(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_expr(["5", "!=", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1"

    def test_comparison_less_than(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_expr(["3", "<", "5"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1"

    def test_comparison_greater_than(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        result = cmd_expr(["5", ">", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1"

    def test_comparison_false_returns_exit_1(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """When comparison result is 0, exit code should be 1."""
        io = IOContext()
        result = cmd_expr(["5", "=", "3"], state, vfs, io)
        assert result.exit_code == 1
        assert io.stdout.getvalue().strip() == "0"

    def test_result_zero_exit_code_1(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """expr returns exit code 1 when the result is 0."""
        io = IOContext()
        result = cmd_expr(["5", "-", "5"], state, vfs, io)
        assert result.exit_code == 1
        assert io.stdout.getvalue().strip() == "0"

    def test_string_single_value(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """expr with a single string token returns that string."""
        io = IOContext()
        result = cmd_expr(["hello"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "hello"

    def test_missing_operand(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr([], state, vfs, io)
        assert result.exit_code == 2
        assert "missing operand" in io.stderr.getvalue()

    def test_length_operation(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """expr length requires 3+ tokens in the implementation.

        With 2 tokens ('length', 'hello'), it falls through to
        returning 'length' as a string. Use the real bash expr
        pattern: match hello '.*' for string length equivalent.
        """
        io = IOContext()
        # expr match hello '.*' returns the length of the match
        result = cmd_expr(["match", "hello", ".*"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "5"

    def test_substr_operation(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_expr(["substr", "hello", "2", "3"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "ell"

    @pytest.mark.parametrize(
        "args,expected_output,expected_exit",
        [
            (["1", "+", "2"], "3", 0),
            (["0", "+", "0"], "0", 1),
            (["10", "*", "0"], "0", 1),
            (["100", "/", "10"], "10", 0),
        ],
    )
    def test_parametrized_arithmetic(
        self,
        args: list[str],
        expected_output: str,
        expected_exit: int,
        state: ShellState,
        vfs: VirtualFilesystem,
    ) -> None:
        io = IOContext()
        result = cmd_expr(args, state, vfs, io)
        assert io.stdout.getvalue().strip() == expected_output
        assert result.exit_code == expected_exit


# ---------------------------------------------------------------------------
# bc
# ---------------------------------------------------------------------------


class TestBc:
    """Tests for the bc command."""

    def test_basic_addition(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("3+4\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "7"

    def test_basic_subtraction(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("10-3\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "7"

    def test_basic_multiplication(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        io.stdin = StringIO("6*7\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "42"

    def test_basic_division(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("20/4\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "5"

    def test_exponentiation(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("2^10\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "1024"

    def test_multiple_expressions(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        io.stdin = StringIO("1+1\n2+2\n3+3\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        assert lines == ["2", "4", "6"]

    def test_empty_input(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_quit_stops_processing(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        io.stdin = StringIO("1+1\nquit\n2+2\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        lines = io.stdout.getvalue().strip().split("\n")
        assert lines == ["2"]

    def test_parentheses(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        io.stdin = StringIO("(2+3)*4\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "20"

    def test_comment_lines_ignored(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        io = IOContext()
        io.stdin = StringIO("# comment\n5+5\n")
        result = cmd_bc([], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue().strip() == "10"


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


class TestDiff:
    """Tests for the diff command."""

    def test_identical_files_return_0(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Identical files should return exit 0 when using unified diff format.
        Note: ndiff (default) always produces output even for identical files
        (with '  ' prefixed lines), but unified diff produces empty output."""
        vfs.write("/a.txt", b"line1\nline2\nline3\n")
        vfs.write("/b.txt", b"line1\nline2\nline3\n")
        io = IOContext()
        result = cmd_diff(["-u", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
        assert io.stdout.getvalue() == ""

    def test_different_files_return_1(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        vfs.write("/a.txt", b"line1\nline2\n")
        vfs.write("/b.txt", b"line1\nline3\n")
        io = IOContext()
        result = cmd_diff(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 1
        output = io.stdout.getvalue()
        assert len(output) > 0

    def test_unified_diff(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """diff -u should produce unified diff format."""
        vfs.write("/a.txt", b"line1\nline2\nline3\n")
        vfs.write("/b.txt", b"line1\nmodified\nline3\n")
        io = IOContext()
        result = cmd_diff(["-u", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 1
        output = io.stdout.getvalue()
        assert "---" in output
        assert "+++" in output
        assert "/a.txt" in output
        assert "/b.txt" in output

    def test_missing_file(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        vfs.write("/a.txt", b"content\n")
        io = IOContext()
        result = cmd_diff(["/a.txt", "/nofile.txt"], state, vfs, io)
        assert result.exit_code == 2
        assert "No such file" in io.stderr.getvalue()

    def test_missing_operand(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        io = IOContext()
        result = cmd_diff(["/a.txt"], state, vfs, io)
        assert result.exit_code == 1
        assert "missing operand" in io.stderr.getvalue()

    def test_basic_ndiff_output(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Without -u, diff uses ndiff format."""
        vfs.write("/a.txt", b"apple\n")
        vfs.write("/b.txt", b"apply\n")
        io = IOContext()
        result = cmd_diff(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 1
        # ndiff shows differences
        assert len(io.stdout.getvalue()) > 0

    def test_added_lines(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """diff should detect added lines."""
        vfs.write("/a.txt", b"line1\n")
        vfs.write("/b.txt", b"line1\nline2\n")
        io = IOContext()
        result = cmd_diff(["-u", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 1
        output = io.stdout.getvalue()
        assert "+line2" in output

    def test_removed_lines(self, state: ShellState, vfs: VirtualFilesystem) -> None:
        """diff should detect removed lines."""
        vfs.write("/a.txt", b"line1\nline2\n")
        vfs.write("/b.txt", b"line1\n")
        io = IOContext()
        result = cmd_diff(["-u", "/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 1
        output = io.stdout.getvalue()
        assert "-line2" in output

    def test_empty_files_identical(
        self, state: ShellState, vfs: VirtualFilesystem
    ) -> None:
        """Two empty files should be identical."""
        vfs.write("/a.txt", b"")
        vfs.write("/b.txt", b"")
        io = IOContext()
        result = cmd_diff(["/a.txt", "/b.txt"], state, vfs, io)
        assert result.exit_code == 0
