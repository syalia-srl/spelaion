"""Unit tests for exec layer: pipelines, redirections, tool dispatch.

Covers:
- execute_pipeline: empty, single, multi-stage, pipefail semantics
- IOContext: default construction, read/write streams
- VFSWriteBuffer: accumulate writes, flush with truncate and append
- apply_redirections: all redirection operators against VFS
- dispatch_tool: found/not-found, stdin forwarding, output capture
"""

from __future__ import annotations

from io import StringIO

import pytest

from agentsh.ast.nodes import Redirection, Word
from agentsh.ast.spans import Point, Span
from agentsh.ast.words import LiteralSegment
from agentsh.exec.pipelines import execute_pipeline
from agentsh.exec.redirs import IOContext, VFSWriteBuffer, apply_redirections
from agentsh.exec.tool_dispatch import dispatch_tool
from agentsh.runtime.result import CommandResult
from agentsh.runtime.state import ShellState
from agentsh.tools.registry import ToolRegistry
from agentsh.vfs.filesystem import VirtualFilesystem

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SPAN = Span(0, 0, Point(0, 0), Point(0, 0))


def _word(text: str) -> Word:
    """Create a Word node with a single LiteralSegment."""
    return Word(segments=(LiteralSegment(value=text),), span=_SPAN)


def _redir(op: str, target: str, fd: int | None = None) -> Redirection:
    """Build a Redirection AST node."""
    return Redirection(op=op, fd=fd, target=_word(target), span=_SPAN)


class _StubTool:
    """A tool implementation for testing dispatch_tool."""

    def __init__(
        self,
        tool_name: str,
        exit_code: int = 0,
        stdout: str = "",
        stderr: str = "",
        echo_stdin: bool = False,
    ) -> None:
        self._name = tool_name
        self._exit_code = exit_code
        self._stdout = stdout
        self._stderr = stderr
        self._echo_stdin = echo_stdin
        self.last_args: list[str] = []
        self.last_stdin: str | None = None

    @property
    def name(self) -> str:
        return self._name

    def invoke(
        self,
        args: list[str],
        stdin: str | None = None,
    ) -> CommandResult:
        self.last_args = args
        self.last_stdin = stdin
        out = stdin if self._echo_stdin and stdin else self._stdout
        return CommandResult(
            exit_code=self._exit_code,
            stdout=out,
            stderr=self._stderr,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def vfs() -> VirtualFilesystem:
    return VirtualFilesystem()


@pytest.fixture()
def state() -> ShellState:
    return ShellState()


@pytest.fixture()
def registry() -> ToolRegistry:
    return ToolRegistry()


# ===========================================================================
# 1. execute_pipeline
# ===========================================================================


class TestExecutePipelineEmpty:
    """An empty pipeline should return exit code 0 with no output."""

    def test_empty_returns_zero(self) -> None:
        result = execute_pipeline([])
        assert result.exit_code == 0

    def test_empty_has_empty_stdout(self) -> None:
        result = execute_pipeline([])
        assert result.stdout == ""


class TestExecutePipelineSingleCommand:
    """A single-command pipeline should run exactly that command."""

    def test_single_command_exit_code(self) -> None:
        def cmd(io: IOContext) -> CommandResult:
            return CommandResult(exit_code=42)

        result = execute_pipeline([cmd])
        assert result.exit_code == 42

    def test_single_command_reads_input(self) -> None:
        def cmd(io: IOContext) -> CommandResult:
            data = io.stdin.read()
            return CommandResult(exit_code=0, stdout=data)

        result = execute_pipeline([cmd], input_text="hello")
        assert result.exit_code == 0
        assert result.stdout == "hello"

    def test_single_command_writes_to_io_stdout(self) -> None:
        def cmd(io: IOContext) -> CommandResult:
            io.stdout.write("from io")
            return CommandResult(exit_code=0)

        result = execute_pipeline([cmd])
        assert result.exit_code == 0


class TestExecutePipelineTwoCommands:
    """Two-command pipeline: first command's io.stdout feeds second's stdin."""

    def test_stdout_to_stdin(self) -> None:
        def producer(io: IOContext) -> CommandResult:
            io.stdout.write("piped data")
            return CommandResult(exit_code=0)

        def consumer(io: IOContext) -> CommandResult:
            data = io.stdin.read()
            io.stdout.write(data.upper())
            return CommandResult(exit_code=0)

        result = execute_pipeline([producer, consumer])
        assert result.exit_code == 0
        assert result.stdout == "PIPED DATA"

    def test_exit_code_is_last(self) -> None:
        def first(io: IOContext) -> CommandResult:
            io.stdout.write("x")
            return CommandResult(exit_code=5)

        def second(io: IOContext) -> CommandResult:
            return CommandResult(exit_code=0)

        result = execute_pipeline([first, second])
        assert result.exit_code == 0


class TestExecutePipelineThreeCommands:
    """Three-command pipeline chain passes data through all stages."""

    def test_three_stage_chain(self) -> None:
        def stage1(io: IOContext) -> CommandResult:
            io.stdout.write("abc")
            return CommandResult(exit_code=0)

        def stage2(io: IOContext) -> CommandResult:
            data = io.stdin.read()
            io.stdout.write(data + "def")
            return CommandResult(exit_code=0)

        def stage3(io: IOContext) -> CommandResult:
            data = io.stdin.read()
            io.stdout.write(data + "ghi")
            return CommandResult(exit_code=0)

        result = execute_pipeline([stage1, stage2, stage3])
        assert result.stdout == "abcdefghi"
        assert result.exit_code == 0


class TestExecutePipelinePipefail:
    """pipefail controls which exit code is returned from the pipeline."""

    def test_pipefail_false_uses_last_exit_code(self) -> None:
        def failing(io: IOContext) -> CommandResult:
            io.stdout.write("data")
            return CommandResult(exit_code=1)

        def passing(io: IOContext) -> CommandResult:
            io.stdout.write("ok")
            return CommandResult(exit_code=0)

        result = execute_pipeline([failing, passing], pipefail=False)
        assert result.exit_code == 0

    def test_pipefail_true_uses_rightmost_nonzero(self) -> None:
        def fail_with_2(io: IOContext) -> CommandResult:
            io.stdout.write("a")
            return CommandResult(exit_code=2)

        def fail_with_3(io: IOContext) -> CommandResult:
            io.stdout.write("b")
            return CommandResult(exit_code=3)

        def succeed(io: IOContext) -> CommandResult:
            io.stdout.write("c")
            return CommandResult(exit_code=0)

        result = execute_pipeline([fail_with_2, fail_with_3, succeed], pipefail=True)
        assert result.exit_code == 3

    def test_pipefail_true_all_zero(self) -> None:
        def ok(io: IOContext) -> CommandResult:
            io.stdout.write("ok")
            return CommandResult(exit_code=0)

        result = execute_pipeline([ok, ok], pipefail=True)
        assert result.exit_code == 0

    def test_pipefail_true_first_fails(self) -> None:
        def fail(io: IOContext) -> CommandResult:
            io.stdout.write("x")
            return CommandResult(exit_code=7)

        def ok(io: IOContext) -> CommandResult:
            io.stdout.write("y")
            return CommandResult(exit_code=0)

        result = execute_pipeline([fail, ok], pipefail=True)
        assert result.exit_code == 7


class TestExecutePipelineEmptyOutput:
    """Pipeline where commands produce no output."""

    def test_empty_output_propagation(self) -> None:
        def silent(io: IOContext) -> CommandResult:
            return CommandResult(exit_code=0)

        def reader(io: IOContext) -> CommandResult:
            data = io.stdin.read()
            io.stdout.write(f"got:{data}")
            return CommandResult(exit_code=0)

        result = execute_pipeline([silent, reader])
        assert result.stdout == "got:"


# ===========================================================================
# 2. IOContext
# ===========================================================================


class TestIOContextDefaults:
    """IOContext default construction provides empty StringIO streams."""

    def test_default_stdin_is_empty(self) -> None:
        io = IOContext()
        assert io.stdin.read() == ""

    def test_default_stdout_is_empty(self) -> None:
        io = IOContext()
        assert io.stdout.getvalue() == ""

    def test_default_stderr_is_empty(self) -> None:
        io = IOContext()
        assert io.stderr.getvalue() == ""

    def test_executor_is_none(self) -> None:
        io = IOContext()
        assert io.executor is None


class TestIOContextReadWrite:
    """IOContext streams support reading and writing."""

    def test_write_and_read_stdout(self) -> None:
        io = IOContext()
        io.stdout.write("hello")
        assert io.stdout.getvalue() == "hello"

    def test_write_and_read_stderr(self) -> None:
        io = IOContext()
        io.stderr.write("error msg")
        assert io.stderr.getvalue() == "error msg"

    def test_stdin_with_preloaded_data(self) -> None:
        io = IOContext(stdin=StringIO("preloaded"))
        assert io.stdin.read() == "preloaded"

    def test_multiple_writes_accumulate(self) -> None:
        io = IOContext()
        io.stdout.write("first")
        io.stdout.write(" second")
        assert io.stdout.getvalue() == "first second"


# ===========================================================================
# 3. VFSWriteBuffer
# ===========================================================================


class TestVFSWriteBufferFlush:
    """VFSWriteBuffer.flush_to_vfs writes accumulated content to VFS."""

    def test_flush_creates_file(self, vfs: VirtualFilesystem) -> None:
        buf = VFSWriteBuffer(vfs, "/output.txt", append=False)
        buf.write("hello world")
        buf.flush_to_vfs()
        assert vfs.read("/output.txt") == b"hello world"

    def test_flush_truncate_overwrites(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/file.txt", b"old content")
        buf = VFSWriteBuffer(vfs, "/file.txt", append=False)
        buf.write("new content")
        buf.flush_to_vfs()
        assert vfs.read("/file.txt") == b"new content"

    def test_flush_append(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/file.txt", b"start ")
        buf = VFSWriteBuffer(vfs, "/file.txt", append=True)
        buf.write("end")
        buf.flush_to_vfs()
        assert vfs.read("/file.txt") == b"start end"

    def test_multiple_writes_before_flush(self, vfs: VirtualFilesystem) -> None:
        buf = VFSWriteBuffer(vfs, "/multi.txt", append=False)
        buf.write("line1\n")
        buf.write("line2\n")
        buf.write("line3\n")
        buf.flush_to_vfs()
        assert vfs.read("/multi.txt") == b"line1\nline2\nline3\n"

    def test_empty_flush(self, vfs: VirtualFilesystem) -> None:
        buf = VFSWriteBuffer(vfs, "/empty.txt", append=False)
        buf.flush_to_vfs()
        assert vfs.read("/empty.txt") == b""

    def test_append_to_nonexistent_creates_file(self, vfs: VirtualFilesystem) -> None:
        buf = VFSWriteBuffer(vfs, "/new.txt", append=True)
        buf.write("brand new")
        buf.flush_to_vfs()
        assert vfs.read("/new.txt") == b"brand new"


# ===========================================================================
# 4. apply_redirections
# ===========================================================================


class TestApplyRedirectionsInputFromFile:
    """< reads stdin from a VFS file."""

    def test_stdin_from_file(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        vfs.write("/input.txt", b"file contents")
        io = IOContext()
        redir = _redir("<", "/input.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        assert result_io.stdin.read() == "file contents"

    def test_stdin_missing_file(
        self, vfs: VirtualFilesystem, state: ShellState
    ) -> None:
        io = IOContext()
        redir = _redir("<", "/nonexistent.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        stderr_output = result_io.stderr.getvalue()
        assert "No such file" in stderr_output
        assert "/nonexistent.txt" in stderr_output


class TestApplyRedirectionsOutputTruncate:
    """> redirects stdout to VFS file with truncation."""

    def test_stdout_to_new_file(
        self, vfs: VirtualFilesystem, state: ShellState
    ) -> None:
        io = IOContext()
        redir = _redir(">", "/out.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        result_io.stdout.write("output data")
        assert isinstance(result_io.stdout, VFSWriteBuffer)
        result_io.stdout.flush_to_vfs()
        assert vfs.read("/out.txt") == b"output data"

    def test_stdout_truncates_existing(
        self, vfs: VirtualFilesystem, state: ShellState
    ) -> None:
        vfs.write("/out.txt", b"old stuff")
        io = IOContext()
        redir = _redir(">", "/out.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        result_io.stdout.write("new stuff")
        result_io.stdout.flush_to_vfs()
        assert vfs.read("/out.txt") == b"new stuff"


class TestApplyRedirectionsOutputAppend:
    """>> appends stdout to VFS file."""

    def test_stdout_append(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        vfs.write("/out.txt", b"existing ")
        io = IOContext()
        redir = _redir(">>", "/out.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        result_io.stdout.write("appended")
        assert isinstance(result_io.stdout, VFSWriteBuffer)
        result_io.stdout.flush_to_vfs()
        assert vfs.read("/out.txt") == b"existing appended"


class TestApplyRedirectionsStderr:
    """2> redirects stderr to VFS file."""

    def test_stderr_redirect(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        io = IOContext()
        redir = _redir("2>", "/err.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        result_io.stderr.write("error output")
        assert isinstance(result_io.stderr, VFSWriteBuffer)
        result_io.stderr.flush_to_vfs()
        assert vfs.read("/err.txt") == b"error output"


class TestApplyRedirectionsDuplicateFd:
    """>& duplicates file descriptors."""

    def test_stderr_to_stdout(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        io = IOContext()
        redir = _redir(">&", "1")
        result_io = apply_redirections((redir,), io, state, vfs)
        assert result_io.stderr is result_io.stdout

    def test_stdout_to_stderr(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        io = IOContext()
        redir = _redir(">&", "2")
        result_io = apply_redirections((redir,), io, state, vfs)
        assert result_io.stdout is result_io.stderr


class TestApplyRedirectionsCloseStdin:
    """<&- closes stdin (replaces with empty StringIO)."""

    def test_close_stdin(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        io = IOContext(stdin=StringIO("data to discard"))
        redir = _redir("<&", "-")
        result_io = apply_redirections((redir,), io, state, vfs)
        assert result_io.stdin.read() == ""


class TestApplyRedirectionsMultiple:
    """Multiple redirections are applied in order."""

    def test_two_redirections(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        vfs.write("/input.txt", b"hello")
        io = IOContext()
        redir_in = _redir("<", "/input.txt")
        redir_out = _redir(">", "/output.txt")
        result_io = apply_redirections((redir_in, redir_out), io, state, vfs)
        # stdin was redirected from /input.txt
        assert result_io.stdin.read() == "hello"
        # stdout was redirected to /output.txt
        assert isinstance(result_io.stdout, VFSWriteBuffer)
        result_io.stdout.write("processed")
        result_io.stdout.flush_to_vfs()
        assert vfs.read("/output.txt") == b"processed"

    def test_stderr_and_merge(self, vfs: VirtualFilesystem, state: ShellState) -> None:
        """2>/err.txt followed by >&1 merges stderr into stdout."""
        io = IOContext()
        redir_err = _redir("2>", "/err.txt")
        redir_merge = _redir(">&", "1")
        result_io = apply_redirections((redir_err, redir_merge), io, state, vfs)
        # After 2>/err.txt, stderr is a VFSWriteBuffer.
        # After >&1, stderr should point to stdout.
        assert result_io.stderr is result_io.stdout

    def test_redirect_relative_path(
        self, vfs: VirtualFilesystem, state: ShellState
    ) -> None:
        """Relative paths are resolved against state.cwd."""
        state.cwd = "/home/user"
        vfs.mkdir("/home/user", parents=True)
        io = IOContext()
        redir = _redir(">", "output.txt")
        result_io = apply_redirections((redir,), io, state, vfs)
        result_io.stdout.write("data")
        result_io.stdout.flush_to_vfs()
        assert vfs.read("/home/user/output.txt") == b"data"


# ===========================================================================
# 5. dispatch_tool
# ===========================================================================


class TestDispatchToolFound:
    """When the tool is in the registry, dispatch invokes it."""

    def test_basic_invocation(self, registry: ToolRegistry) -> None:
        tool = _StubTool("mock", exit_code=0, stdout="mock output")
        registry.register("mock", tool)
        io = IOContext()
        result = dispatch_tool("mock", ["arg1", "arg2"], registry, io)
        assert result.exit_code == 0
        assert result.stdout == "mock output"
        assert tool.last_args == ["arg1", "arg2"]

    def test_output_written_to_io(self, registry: ToolRegistry) -> None:
        tool = _StubTool("mock", stdout="tool stdout", stderr="tool stderr")
        registry.register("mock", tool)
        io = IOContext()
        dispatch_tool("mock", [], registry, io)
        assert io.stdout.getvalue() == "tool stdout"
        assert io.stderr.getvalue() == "tool stderr"

    def test_exit_code_propagated(self, registry: ToolRegistry) -> None:
        tool = _StubTool("fail", exit_code=42)
        registry.register("fail", tool)
        io = IOContext()
        result = dispatch_tool("fail", [], registry, io)
        assert result.exit_code == 42


class TestDispatchToolNotFound:
    """When the tool is not in the registry, dispatch returns 127."""

    def test_missing_tool_returns_127(self, registry: ToolRegistry) -> None:
        io = IOContext()
        result = dispatch_tool("nonexistent", [], registry, io)
        assert result.exit_code == 127

    def test_missing_tool_writes_stderr(self, registry: ToolRegistry) -> None:
        io = IOContext()
        dispatch_tool("nonexistent", [], registry, io)
        stderr_output = io.stderr.getvalue()
        assert "nonexistent" in stderr_output
        assert "command not found" in stderr_output

    def test_missing_tool_result_stderr(self, registry: ToolRegistry) -> None:
        io = IOContext()
        result = dispatch_tool("gone", [], registry, io)
        assert "command not found" in result.stderr


class TestDispatchToolStdin:
    """Tools receive stdin text from the IOContext."""

    def test_stdin_forwarded_to_tool(self, registry: ToolRegistry) -> None:
        tool = _StubTool("cat", echo_stdin=True)
        registry.register("cat", tool)
        io = IOContext(stdin=StringIO("stdin data"))
        result = dispatch_tool("cat", [], registry, io)
        assert tool.last_stdin == "stdin data"
        assert result.stdout == "stdin data"

    def test_empty_stdin_becomes_none(self, registry: ToolRegistry) -> None:
        tool = _StubTool("cmd")
        registry.register("cmd", tool)
        io = IOContext(stdin=StringIO(""))
        dispatch_tool("cmd", [], registry, io)
        assert tool.last_stdin is None

    def test_stdin_with_args(self, registry: ToolRegistry) -> None:
        tool = _StubTool("grep", echo_stdin=True)
        registry.register("grep", tool)
        io = IOContext(stdin=StringIO("line1\nline2"))
        dispatch_tool("grep", ["-i", "pattern"], registry, io)
        assert tool.last_args == ["-i", "pattern"]
        assert tool.last_stdin == "line1\nline2"


class TestDispatchToolOutputStreams:
    """Tool stdout/stderr are written to IOContext streams."""

    def test_only_stdout(self, registry: ToolRegistry) -> None:
        tool = _StubTool("echo", stdout="hello\n", stderr="")
        registry.register("echo", tool)
        io = IOContext()
        dispatch_tool("echo", ["hello"], registry, io)
        assert io.stdout.getvalue() == "hello\n"
        assert io.stderr.getvalue() == ""

    def test_only_stderr(self, registry: ToolRegistry) -> None:
        tool = _StubTool("warn", stdout="", stderr="warning!\n")
        registry.register("warn", tool)
        io = IOContext()
        dispatch_tool("warn", [], registry, io)
        assert io.stdout.getvalue() == ""
        assert io.stderr.getvalue() == "warning!\n"

    def test_both_streams(self, registry: ToolRegistry) -> None:
        tool = _StubTool("mixed", stdout="out", stderr="err")
        registry.register("mixed", tool)
        io = IOContext()
        dispatch_tool("mixed", [], registry, io)
        assert io.stdout.getvalue() == "out"
        assert io.stderr.getvalue() == "err"

    def test_no_output(self, registry: ToolRegistry) -> None:
        tool = _StubTool("silent", stdout="", stderr="")
        registry.register("silent", tool)
        io = IOContext()
        dispatch_tool("silent", [], registry, io)
        assert io.stdout.getvalue() == ""
        assert io.stderr.getvalue() == ""
