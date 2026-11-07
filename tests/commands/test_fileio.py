"""Comprehensive tests for virtual file I/O and path utility commands.

Covers all commands in agentsh.commands.fileio (cat, head, tail, tee,
touch, mkdir, cp, mv, rm, ln) and agentsh.commands.pathutil (ls,
basename, dirname, realpath/readlink).
"""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.commands.fileio import (
    cmd_cat,
    cmd_cp,
    cmd_head,
    cmd_ln,
    cmd_mkdir,
    cmd_mv,
    cmd_rm,
    cmd_tail,
    cmd_tee,
    cmd_touch,
)
from agentsh.commands.pathutil import (
    cmd_basename,
    cmd_dirname,
    cmd_ls,
    cmd_realpath,
)
from agentsh.exec.redirs import IOContext
from agentsh.runtime.state import ShellState
from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return a VFS with a single seed file."""
    return VirtualFilesystem({"/hello.txt": "hello world\n"})


@pytest.fixture
def state() -> ShellState:
    """Return a ShellState rooted at /."""
    s = ShellState()
    s.cwd = "/"
    return s


@pytest.fixture
def io_ctx() -> IOContext:
    """Return a fresh IOContext."""
    return IOContext()


# ------------------------------------------------------------------
# cat
# ------------------------------------------------------------------


class TestCat:
    def test_read_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cat(["hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "hello world\n"

    def test_read_stdin(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("stdin content\n")
        result = cmd_cat([], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "stdin content\n"

    def test_read_stdin_with_dash(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("from stdin\n")
        result = cmd_cat(["-"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "from stdin\n"

    def test_number_lines(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/multi.txt", b"alpha\nbeta\ngamma\n")
        result = cmd_cat(["-n", "multi.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "1\talpha\n" in output
        assert "2\tbeta\n" in output
        assert "3\tgamma\n" in output

    def test_number_lines_across_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/a.txt", b"line1\n")
        vfs.write("/b.txt", b"line2\n")
        result = cmd_cat(["-n", "a.txt", "b.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "1\tline1\n" in output
        assert "2\tline2\n" in output

    def test_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/a.txt", b"aaa\n")
        vfs.write("/b.txt", b"bbb\n")
        result = cmd_cat(["a.txt", "b.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "aaa\nbbb\n"

    def test_nonexistent_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cat(["missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_partial_failure_with_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """First file exists, second does not. Output still has first file."""
        result = cmd_cat(["hello.txt", "missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert io_ctx.stdout.getvalue() == "hello world\n"
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_cat_directory_error(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/mydir")
        result = cmd_cat(["mydir"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "Is a directory" in io_ctx.stderr.getvalue()

    def test_double_dash_ignored(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cat(["--", "hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "hello world\n"

    def test_number_lines_no_trailing_newline(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """File content without trailing newline should still get a newline appended."""
        vfs.write("/no_nl.txt", b"no newline")
        result = cmd_cat(["-n", "no_nl.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert output.endswith("\n")


# ------------------------------------------------------------------
# head
# ------------------------------------------------------------------


class TestHead:
    def test_default_10_lines(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        content = "".join(f"line{i}\n" for i in range(20))
        vfs.write("/twenty.txt", content.encode())
        result = cmd_head(["twenty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output_lines = io_ctx.stdout.getvalue().splitlines()
        assert len(output_lines) == 10
        assert output_lines[0] == "line0"
        assert output_lines[9] == "line9"

    def test_n_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        content = "".join(f"line{i}\n" for i in range(20))
        vfs.write("/twenty.txt", content.encode())
        result = cmd_head(["-n", "3", "twenty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output_lines = io_ctx.stdout.getvalue().splitlines()
        assert len(output_lines) == 3
        assert output_lines == ["line0", "line1", "line2"]

    def test_shorthand_dash_number(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        content = "".join(f"line{i}\n" for i in range(10))
        vfs.write("/ten.txt", content.encode())
        result = cmd_head(["-5", "ten.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output_lines = io_ctx.stdout.getvalue().splitlines()
        assert len(output_lines) == 5

    def test_stdin(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("a\nb\nc\nd\ne\n")
        result = cmd_head(["-n", "2"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "a\nb\n"

    def test_fewer_lines_than_n(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/short.txt", b"only two\nlines\n")
        result = cmd_head(["short.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "only two\nlines\n"

    def test_nonexistent_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_head(["missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_invalid_number(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_head(["-n", "abc"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "invalid" in io_ctx.stderr.getvalue()

    def test_empty_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/empty.txt", b"")
        result = cmd_head(["empty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == ""


# ------------------------------------------------------------------
# tail
# ------------------------------------------------------------------


class TestTail:
    def test_default_10_lines(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        content = "".join(f"line{i}\n" for i in range(20))
        vfs.write("/twenty.txt", content.encode())
        result = cmd_tail(["twenty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output_lines = io_ctx.stdout.getvalue().splitlines()
        assert len(output_lines) == 10
        assert output_lines[0] == "line10"
        assert output_lines[9] == "line19"

    def test_n_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        content = "".join(f"line{i}\n" for i in range(20))
        vfs.write("/twenty.txt", content.encode())
        result = cmd_tail(["-n", "3", "twenty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output_lines = io_ctx.stdout.getvalue().splitlines()
        assert len(output_lines) == 3
        assert output_lines == ["line17", "line18", "line19"]

    def test_n_plus_from_start(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """tail -n +3 means 'starting from line 3'."""
        content = "line1\nline2\nline3\nline4\nline5\n"
        vfs.write("/five.txt", content.encode())
        result = cmd_tail(["-n", "+3", "five.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "line3\nline4\nline5\n"

    def test_stdin(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("a\nb\nc\nd\ne\n")
        result = cmd_tail(["-n", "2"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "d\ne\n"

    def test_fewer_lines_than_n(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/short.txt", b"only\ntwo\n")
        result = cmd_tail(["short.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "only\ntwo\n"

    def test_nonexistent_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_tail(["missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_empty_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/empty.txt", b"")
        result = cmd_tail(["empty.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == ""

    def test_n_plus_1_returns_all(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """tail -n +1 should return the entire file."""
        vfs.write("/all.txt", b"a\nb\nc\n")
        result = cmd_tail(["-n", "+1", "all.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "a\nb\nc\n"


# ------------------------------------------------------------------
# tee
# ------------------------------------------------------------------


class TestTee:
    def test_write_to_stdout_and_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("tee content\n")
        result = cmd_tee(["/output.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "tee content\n"
        assert vfs.read("/output.txt") == b"tee content\n"

    def test_append_mode(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/out.txt", b"existing\n")
        io_ctx.stdin = StringIO("new\n")
        result = cmd_tee(["-a", "/out.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/out.txt") == b"existing\nnew\n"

    def test_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("multi\n")
        result = cmd_tee(["/a.txt", "/b.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "multi\n"
        assert vfs.read("/a.txt") == b"multi\n"
        assert vfs.read("/b.txt") == b"multi\n"

    def test_no_files_only_stdout(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        io_ctx.stdin = StringIO("just stdout\n")
        result = cmd_tee([], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "just stdout\n"

    def test_overwrite_mode(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """Without -a, tee overwrites existing file content."""
        vfs.write("/out.txt", b"old content\n")
        io_ctx.stdin = StringIO("new content\n")
        result = cmd_tee(["/out.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/out.txt") == b"new content\n"


# ------------------------------------------------------------------
# touch
# ------------------------------------------------------------------


class TestTouch:
    def test_create_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_touch(["/new.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.exists("/new.txt")
        assert vfs.read("/new.txt") == b""

    def test_noop_on_existing(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_touch(["hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        # Content must not be overwritten
        assert vfs.read("/hello.txt") == b"hello world\n"

    def test_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_touch(["/a.txt", "/b.txt", "/c.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.exists("/a.txt")
        assert vfs.exists("/b.txt")
        assert vfs.exists("/c.txt")

    def test_create_in_subdirectory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """VFS write auto-creates parent dirs, so touch in a subdir should work."""
        result = cmd_touch(["/sub/dir/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.exists("/sub/dir/file.txt")


# ------------------------------------------------------------------
# mkdir
# ------------------------------------------------------------------


class TestMkdir:
    def test_simple(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mkdir(["mydir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.is_dir("/mydir")

    def test_parents(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mkdir(["-p", "a/b/c"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.is_dir("/a")
        assert vfs.is_dir("/a/b")
        assert vfs.is_dir("/a/b/c")

    def test_error_on_existing(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/existing")
        result = cmd_mkdir(["existing"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "File exists" in io_ctx.stderr.getvalue()

    def test_parents_no_error_on_existing(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """mkdir -p should not fail when directory already exists."""
        vfs.mkdir("/existing")
        result = cmd_mkdir(["-p", "existing"], state, vfs, io_ctx)
        assert result.exit_code == 0

    def test_missing_intermediate_without_parents(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mkdir(["deep/nested/dir"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file or directory" in io_ctx.stderr.getvalue()

    def test_multiple_dirs(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mkdir(["dir1", "dir2", "dir3"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.is_dir("/dir1")
        assert vfs.is_dir("/dir2")
        assert vfs.is_dir("/dir3")


# ------------------------------------------------------------------
# cp
# ------------------------------------------------------------------


class TestCp:
    def test_file_copy(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cp(["hello.txt", "/copy.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/copy.txt") == b"hello world\n"
        # Original still exists
        assert vfs.read("/hello.txt") == b"hello world\n"

    def test_recursive_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/src/a.txt", b"aaa")
        vfs.write("/src/b.txt", b"bbb")
        result = cmd_cp(["-r", "/src", "/dst"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dst/a.txt") == b"aaa"
        assert vfs.read("/dst/b.txt") == b"bbb"

    def test_copy_dir_without_recursive_fails(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/src")
        result = cmd_cp(["/src", "/dst"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "omitting directory" in io_ctx.stderr.getvalue()

    def test_dst_is_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """When dst is an existing directory, file is copied inside it."""
        vfs.mkdir("/dest")
        result = cmd_cp(["hello.txt", "/dest"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dest/hello.txt") == b"hello world\n"

    def test_nonexistent_source(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cp(["missing.txt", "/copy.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_cp(["only_one_arg"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing file operand" in io_ctx.stderr.getvalue()

    def test_recursive_with_R_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/src/file.txt", b"data")
        result = cmd_cp(["-R", "/src", "/dst"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dst/file.txt") == b"data"

    def test_recursive_with_long_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/src/file.txt", b"data")
        result = cmd_cp(["--recursive", "/src", "/dst"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dst/file.txt") == b"data"

    def test_recursive_nested_dirs(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/src/sub/deep.txt", b"deep")
        result = cmd_cp(["-r", "/src", "/dst"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dst/sub/deep.txt") == b"deep"


# ------------------------------------------------------------------
# mv
# ------------------------------------------------------------------


class TestMv:
    def test_rename_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mv(["hello.txt", "/renamed.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/renamed.txt") == b"hello world\n"
        assert not vfs.exists("/hello.txt")

    def test_move_into_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/dest")
        result = cmd_mv(["hello.txt", "/dest"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/dest/hello.txt") == b"hello world\n"
        assert not vfs.exists("/hello.txt")

    def test_error_on_nonexistent(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mv(["missing.txt", "/dst.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_mv(["only_one_arg"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing file operand" in io_ctx.stderr.getvalue()

    def test_rename_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/mydir/file.txt", b"content")
        result = cmd_mv(["/mydir", "/newdir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/newdir/file.txt") == b"content"
        assert not vfs.exists("/mydir")


# ------------------------------------------------------------------
# rm
# ------------------------------------------------------------------


class TestRm:
    def test_remove_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_rm(["hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/hello.txt")

    def test_recursive_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/dir/sub/file.txt", b"deep")
        result = cmd_rm(["-r", "/dir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/dir")

    def test_directory_without_recursive_fails(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/mydir")
        result = cmd_rm(["mydir"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "Is a directory" in io_ctx.stderr.getvalue()
        assert vfs.exists("/mydir")

    def test_force_nonexistent(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_rm(["-f", "missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stderr.getvalue() == ""

    def test_nonexistent_without_force(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_rm(["missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_rf_combined_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/dir/file.txt", b"data")
        result = cmd_rm(["-rf", "/dir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/dir")

    def test_fr_combined_flag(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/dir/file.txt", b"data")
        result = cmd_rm(["-fr", "/dir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/dir")

    def test_rf_force_on_nonexistent(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_rm(["-rf", "missing"], state, vfs, io_ctx)
        assert result.exit_code == 0

    def test_multiple_files(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/a.txt", b"a")
        vfs.write("/b.txt", b"b")
        result = cmd_rm(["/a.txt", "/b.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/a.txt")
        assert not vfs.exists("/b.txt")

    def test_R_flag_for_recursive(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/dir/file.txt", b"data")
        result = cmd_rm(["-R", "/dir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/dir")

    def test_long_flag_recursive(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/dir/file.txt", b"data")
        result = cmd_rm(["--recursive", "/dir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert not vfs.exists("/dir")

    def test_long_flag_force(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_rm(["--force", "missing.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0


# ------------------------------------------------------------------
# ln
# ------------------------------------------------------------------


class TestLn:
    def test_copy_based_link(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_ln(["hello.txt", "/link.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/link.txt") == b"hello world\n"
        # Source still exists
        assert vfs.read("/hello.txt") == b"hello world\n"

    def test_symbolic_flag_accepted(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """The -s flag is accepted (symlinks are copies in VFS)."""
        result = cmd_ln(["-s", "hello.txt", "/link.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert vfs.read("/link.txt") == b"hello world\n"

    def test_nonexistent_source(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_ln(["missing.txt", "/link.txt"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_ln(["only_one"], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing file operand" in io_ctx.stderr.getvalue()


# ------------------------------------------------------------------
# ls
# ------------------------------------------------------------------


class TestLs:
    def test_basic_listing(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """ls of / should show hello.txt."""
        result = cmd_ls([], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert "hello.txt" in io_ctx.stdout.getvalue()

    def test_long_format(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_ls(["-l"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "-rw-r--r--" in output
        assert "hello.txt" in output

    def test_long_format_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/subdir")
        result = cmd_ls(["-l"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "drwxr-xr-x" in output
        assert "subdir" in output

    def test_show_all(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """Files starting with . should only appear with -a."""
        vfs.write("/.hidden", b"secret")
        cmd_ls([], state, vfs, io_ctx)
        assert ".hidden" not in io_ctx.stdout.getvalue()

        io_ctx2 = IOContext()
        result_with = cmd_ls(["-a"], state, vfs, io_ctx2)
        assert result_with.exit_code == 0
        assert ".hidden" in io_ctx2.stdout.getvalue()

    def test_one_per_line(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/a.txt", b"")
        vfs.write("/b.txt", b"")
        result = cmd_ls(["-1"], state, vfs, io_ctx)
        assert result.exit_code == 0
        lines = io_ctx.stdout.getvalue().strip().splitlines()
        # Each entry on its own line
        assert "a.txt" in lines
        assert "b.txt" in lines
        assert "hello.txt" in lines

    def test_file_arg(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """ls on a specific file should just print that file."""
        result = cmd_ls(["hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert "hello.txt" in io_ctx.stdout.getvalue()

    def test_nonexistent_path(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_ls(["nosuchfile"], state, vfs, io_ctx)
        assert result.exit_code == 2
        assert "No such file" in io_ctx.stderr.getvalue()

    def test_specific_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/mydir/file1.txt", b"")
        vfs.write("/mydir/file2.txt", b"")
        result = cmd_ls(["/mydir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "file1.txt" in output
        assert "file2.txt" in output

    def test_combined_flags(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """Combined flags like -la should work."""
        vfs.write("/.hidden", b"secret")
        result = cmd_ls(["-la"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert ".hidden" in output
        assert "-rw-r--r--" in output or "drwxr-xr-x" in output

    def test_long_format_shows_size(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.write("/sized.txt", b"12345")
        result = cmd_ls(["-l", "/sized.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert "5" in io_ctx.stdout.getvalue()

    def test_empty_directory(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        vfs.mkdir("/emptydir")
        result = cmd_ls(["/emptydir"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == ""

    def test_ls_cwd_relative(self, state: ShellState, io_ctx: IOContext) -> None:
        """ls should respect the cwd for resolving '.'."""
        fs = VirtualFilesystem({"/home/user/file.txt": "data"})
        state.cwd = "/home/user"
        result = cmd_ls([], state, fs, io_ctx)
        assert result.exit_code == 0
        assert "file.txt" in io_ctx.stdout.getvalue()

    def test_recursive_listing(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """ls -R should list subdirectories recursively."""
        vfs.write("/proj/src/main.py", b"code")
        vfs.write("/proj/src/util.py", b"util")
        vfs.write("/proj/README.md", b"readme")
        result = cmd_ls(["-R", "/proj"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "/proj:" in output
        assert "src" in output
        assert "README.md" in output
        assert "/proj/src:" in output
        assert "main.py" in output
        assert "util.py" in output

    def test_multiple_directory_args_with_headers(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """When multiple paths are given, each gets a header line."""
        vfs.write("/dir1/a.txt", b"")
        vfs.write("/dir2/b.txt", b"")
        result = cmd_ls(["/dir1", "/dir2"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "/dir1:" in output
        assert "/dir2:" in output
        assert "a.txt" in output
        assert "b.txt" in output

    def test_ls_file_long_format(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """ls -l on a single file path should show long-format entry."""
        result = cmd_ls(["-l", "hello.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        output = io_ctx.stdout.getvalue()
        assert "-rw-r--r--" in output
        assert "hello.txt" in output
        # File is "hello world\n" = 12 bytes
        assert "12" in output


# ------------------------------------------------------------------
# basename
# ------------------------------------------------------------------


class TestBasename:
    def test_basic(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["/home/user/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "file.txt\n"

    def test_with_suffix(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["/home/user/file.txt", ".txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "file\n"

    def test_suffix_not_matching(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["/home/user/file.txt", ".py"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "file.txt\n"

    def test_trailing_slash_stripped(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["/home/user/dir/"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "dir\n"

    def test_root_path(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["/"], state, vfs, io_ctx)
        assert result.exit_code == 0
        # basename of "/" with rstrip("/") is "", posixpath.basename("") is ""
        assert io_ctx.stdout.getvalue() == "\n"

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename([], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing operand" in io_ctx.stderr.getvalue()

    def test_suffix_same_as_name(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """When the suffix equals the entire name, suffix is not stripped."""
        result = cmd_basename(["file.txt", "file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "file.txt\n"

    def test_simple_filename(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_basename(["README.md"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "README.md\n"


# ------------------------------------------------------------------
# dirname
# ------------------------------------------------------------------


class TestDirname:
    def test_basic(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname(["/home/user/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user\n"

    def test_root_file(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname(["/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/\n"

    def test_relative_path(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname(["dir/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "dir\n"

    def test_no_directory_part(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname(["file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        # posixpath.dirname("file.txt") == ""
        assert io_ctx.stdout.getvalue() == "\n"

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname([], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing operand" in io_ctx.stderr.getvalue()

    def test_deeply_nested(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_dirname(["/a/b/c/d/e.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/a/b/c/d\n"


# ------------------------------------------------------------------
# realpath / readlink
# ------------------------------------------------------------------


class TestRealpath:
    def test_absolute_path(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_realpath(["/home/user/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user/file.txt\n"

    def test_relative_path(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        state.cwd = "/home/user"
        result = cmd_realpath(["file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user/file.txt\n"

    def test_dot_resolution(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        state.cwd = "/home/user"
        result = cmd_realpath(["./file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user/file.txt\n"

    def test_dotdot_resolution(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        state.cwd = "/home/user"
        result = cmd_realpath(["../other/file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/other/file.txt\n"

    def test_multiple_paths(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        state.cwd = "/home"
        result = cmd_realpath(["user/a.txt", "user/b.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        lines = io_ctx.stdout.getvalue().strip().splitlines()
        assert lines == ["/home/user/a.txt", "/home/user/b.txt"]

    def test_missing_operand(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_realpath([], state, vfs, io_ctx)
        assert result.exit_code == 1
        assert "missing operand" in io_ctx.stderr.getvalue()

    def test_flags_are_ignored(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        """Flags like -f or -e should be silently skipped."""
        result = cmd_realpath(["-f", "/some/path"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/some/path\n"

    def test_double_slash_normalization(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        result = cmd_realpath(["/home//user///file.txt"], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user/file.txt\n"

    def test_trailing_dot(
        self, vfs: VirtualFilesystem, state: ShellState, io_ctx: IOContext
    ) -> None:
        state.cwd = "/home/user"
        result = cmd_realpath(["."], state, vfs, io_ctx)
        assert result.exit_code == 0
        assert io_ctx.stdout.getvalue() == "/home/user\n"
