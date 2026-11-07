"""Tests for shared I/O helpers in agentsh.commands._io."""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.commands._io import read_binary_inputs, read_text, read_text_inputs
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return a VFS pre-populated with test files."""
    return VirtualFilesystem(
        initial_files={
            "/data/hello.txt": "hello world\n",
            "/data/goodbye.txt": "goodbye world\n",
            "/data/binary.bin": b"\x00\x01\x02\xff",
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
# read_text
# ==================================================================


class TestReadText:
    """Tests for the read_text() helper."""

    def test_reads_file_contents(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_text("/data/hello.txt", state, vfs, io, "mytest")
        assert result == "hello world\n"

    def test_reads_relative_path(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_text("hello.txt", state, vfs, io, "mytest")
        assert result == "hello world\n"

    def test_reads_stdin_on_dash(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("stdin content\n")
        result = read_text("-", state, vfs, io, "mytest")
        assert result == "stdin content\n"

    def test_returns_none_on_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_text("/data/nonexistent.txt", state, vfs, io, "mytest")
        assert result is None

    def test_error_message_on_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text("/data/nonexistent.txt", state, vfs, io, "mytest")
        stderr = io.stderr.getvalue()
        assert "No such file or directory" in stderr

    def test_error_message_includes_cmd_name_on_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text("/data/nonexistent.txt", state, vfs, io, "wc")
        stderr = io.stderr.getvalue()
        assert "wc:" in stderr

    def test_returns_none_on_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_text("/data", state, vfs, io, "mytest")
        assert result is None

    def test_error_message_on_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text("/data", state, vfs, io, "mytest")
        stderr = io.stderr.getvalue()
        assert "Is a directory" in stderr

    def test_error_message_includes_cmd_name_on_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text("/data", state, vfs, io, "cat")
        stderr = io.stderr.getvalue()
        assert "cat:" in stderr

    def test_different_cmd_names_in_error(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text("/data/missing", state, vfs, io, "head")
        stderr = io.stderr.getvalue()
        assert "head:" in stderr


# ==================================================================
# read_text_inputs
# ==================================================================


class TestReadTextInputs:
    """Tests for the read_text_inputs() helper."""

    def test_reads_multiple_files_concatenated(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        text, exit_code = read_text_inputs(
            ["/data/hello.txt", "/data/goodbye.txt"], state, vfs, io, "cat"
        )
        assert exit_code == 0
        assert "hello world\n" in text
        assert "goodbye world\n" in text
        # Concatenated in order
        assert text == "hello world\ngoodbye world\n"

    def test_stdin_fallback_when_no_files(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("from stdin\n")
        text, exit_code = read_text_inputs([], state, vfs, io, "cat")
        assert exit_code == 0
        assert text == "from stdin\n"

    def test_stdin_fallback_when_dash(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("from stdin dash\n")
        text, exit_code = read_text_inputs(["-"], state, vfs, io, "cat")
        assert exit_code == 0
        assert text == "from stdin dash\n"

    def test_exit_code_1_on_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        text, exit_code = read_text_inputs(
            ["/data/nonexistent.txt"], state, vfs, io, "cat"
        )
        assert exit_code == 1
        # No content from the missing file
        assert text == ""

    def test_mixes_valid_and_invalid_files(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        text, exit_code = read_text_inputs(
            ["/data/hello.txt", "/data/nonexistent.txt", "/data/goodbye.txt"],
            state,
            vfs,
            io,
            "cat",
        )
        assert exit_code == 1
        # Valid files are still concatenated
        assert "hello world\n" in text
        assert "goodbye world\n" in text

    def test_error_message_on_missing_in_multi(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_text_inputs(["/data/hello.txt", "/data/nope.txt"], state, vfs, io, "wc")
        stderr = io.stderr.getvalue()
        assert "wc:" in stderr
        assert "No such file or directory" in stderr

    def test_single_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        text, exit_code = read_text_inputs(["/data/hello.txt"], state, vfs, io, "cat")
        assert exit_code == 0
        assert text == "hello world\n"

    def test_all_files_missing(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        text, exit_code = read_text_inputs(
            ["/data/a.txt", "/data/b.txt"], state, vfs, io, "cat"
        )
        assert exit_code == 1
        assert text == ""


# ==================================================================
# read_binary_inputs
# ==================================================================


class TestReadBinaryInputs:
    """Tests for the read_binary_inputs() helper."""

    def test_reads_binary_data(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(["/data/binary.bin"], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "/data/binary.bin"
        assert data == b"\x00\x01\x02\xff"

    def test_reads_text_file_as_bytes(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(["/data/hello.txt"], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "/data/hello.txt"
        assert data == b"hello world\n"

    def test_stdin_as_bytes_when_no_files(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("stdin bytes\n")
        result = read_binary_inputs([], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "-"
        assert data == b"stdin bytes\n"

    def test_stdin_as_bytes_with_dash(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("dash stdin\n")
        result = read_binary_inputs(["-"], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "-"
        assert data == b"dash stdin\n"

    def test_none_for_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(["/data/nonexistent.bin"], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "/data/nonexistent.bin"
        assert data is None

    def test_error_message_includes_cmd_name(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_binary_inputs(["/data/nonexistent.bin"], state, vfs, io, "xxd")
        stderr = io.stderr.getvalue()
        assert "xxd:" in stderr
        assert "No such file or directory" in stderr

    def test_error_message_includes_cmd_name_on_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        read_binary_inputs(["/data"], state, vfs, io, "base64")
        stderr = io.stderr.getvalue()
        assert "base64:" in stderr
        assert "Is a directory" in stderr

    def test_none_for_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(["/data"], state, vfs, io, "xxd")
        assert len(result) == 1
        filename, data = result[0]
        assert filename == "/data"
        assert data is None

    def test_multiple_files_mixed(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(
            ["/data/hello.txt", "/data/nonexistent.bin", "/data/binary.bin"],
            state,
            vfs,
            io,
            "xxd",
        )
        assert len(result) == 3
        assert result[0] == ("/data/hello.txt", b"hello world\n")
        assert result[1] == ("/data/nonexistent.bin", None)
        assert result[2] == ("/data/binary.bin", b"\x00\x01\x02\xff")

    def test_multiple_files_all_valid(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        result = read_binary_inputs(
            ["/data/hello.txt", "/data/binary.bin"], state, vfs, io, "xxd"
        )
        assert len(result) == 2
        assert result[0][1] == b"hello world\n"
        assert result[1][1] == b"\x00\x01\x02\xff"

    def test_dash_mixed_with_files(
        self, vfs: VirtualFilesystem, state: ShellState, io: IOContext
    ) -> None:
        io.stdin = StringIO("from stdin")
        result = read_binary_inputs(["/data/hello.txt", "-"], state, vfs, io, "xxd")
        assert len(result) == 2
        assert result[0] == ("/data/hello.txt", b"hello world\n")
        assert result[1] == ("-", b"from stdin")
