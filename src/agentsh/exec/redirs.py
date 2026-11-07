"""Redirection handling against the VirtualFilesystem.

All targets resolve to VFS paths. No real file I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.ast.nodes import Redirection
    from agentsh.exec.cmd_eval import CommandEvaluator
    from agentsh.exec.word_eval import CommandSubstitutionHook
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@dataclass
class IOContext:
    """Virtual I/O context for a command execution."""

    stdin: StringIO = field(default_factory=StringIO)
    stdout: StringIO = field(default_factory=StringIO)
    stderr: StringIO = field(default_factory=StringIO)
    executor: CommandEvaluator | None = None


def apply_redirections(  # noqa: C901
    redirections: tuple[Redirection, ...],
    io_ctx: IOContext,
    state: ShellState,
    vfs: VirtualFilesystem,
    cmdsub_hook: CommandSubstitutionHook | None = None,
) -> IOContext:
    """Apply redirections to an IOContext, reading/writing from VFS."""

    def _expand_target(word: Redirection) -> str:
        # Use executor's WordEvaluator if available, otherwise fall back
        if io_ctx.executor is not None:
            return io_ctx.executor.word_ev.eval_word_single(word.target)
        from agentsh.semantics.expand import expand_word_single

        return expand_word_single(word.target, state, vfs, cmdsub_hook)

    for redir in redirections:
        target_path = _expand_target(redir)
        op = redir.op
        fd = redir.fd
        abs_path = vfs.resolve(target_path, state.cwd)

        if op == "<<":
            # Here-doc: target word contains the document body
            io_ctx.stdin = StringIO(target_path)
        elif op == "<<<":
            # Here-string: target word is the string
            io_ctx.stdin = StringIO(target_path + "\n")
        elif op == "<":
            try:
                data = vfs.read(abs_path)
                io_ctx.stdin = StringIO(data.decode("utf-8", errors="replace"))
            except FileNotFoundError:
                io_ctx.stderr.write(f"agentsh: {target_path}: No such file\n")
        elif op == ">":
            buf = VFSWriteBuffer(vfs, abs_path, append=False)
            if fd == 2:
                io_ctx.stderr = buf
            else:
                io_ctx.stdout = buf
        elif op == ">>":
            buf = VFSWriteBuffer(vfs, abs_path, append=True)
            if fd == 2:
                io_ctx.stderr = buf
            else:
                io_ctx.stdout = buf
        elif op == "2>":
            io_ctx.stderr = VFSWriteBuffer(vfs, abs_path, append=False)
        elif op == "2>>":
            io_ctx.stderr = VFSWriteBuffer(vfs, abs_path, append=True)
        elif op == ">&":
            if target_path == "1":
                io_ctx.stderr = io_ctx.stdout
            elif target_path == "2":
                io_ctx.stdout = io_ctx.stderr
        elif op == "<&" and target_path == "-":
            io_ctx.stdin = StringIO()

    return io_ctx


class VFSWriteBuffer(StringIO):
    """A StringIO that flushes to VFS on close/getvalue."""

    def __init__(self, vfs: VirtualFilesystem, path: str, append: bool) -> None:
        super().__init__()
        self._vfs = vfs
        self._path = path
        self._append = append

    def flush_to_vfs(self) -> None:
        """Write accumulated content to VFS."""
        content = self.getvalue()
        self._vfs.write(self._path, content.encode("utf-8"), append=self._append)
