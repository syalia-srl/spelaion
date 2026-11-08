"""Redirection handling against the Filesystem.

All targets resolve to VFS paths. No real file I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spelaion.ast.nodes import Redirection
    from spelaion.exec.cmd_eval import CommandEvaluator
    from spelaion.exec.word_eval import CommandSubstitutionHook
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem


@dataclass
class IOContext:
    """Virtual I/O context for a command execution."""

    stdin: StringIO = field(default_factory=StringIO)
    stdout: StringIO = field(default_factory=StringIO)
    stderr: StringIO = field(default_factory=StringIO)
    executor: CommandEvaluator | None = None


class RedirectionError(Exception):
    """A redirection failed; its message is already on stderr.

    Bash then skips the command and its status is 1.
    """


def apply_redirections(  # noqa: C901
    redirections: tuple[Redirection, ...],
    io_ctx: IOContext,
    state: ShellState,
    vfs: Filesystem,
    cmdsub_hook: CommandSubstitutionHook | None = None,
) -> IOContext:
    """Apply redirections to an IOContext, reading/writing from VFS."""

    def _expand_target(word: Redirection) -> str:
        # Use executor's WordEvaluator if available, otherwise fall back
        if io_ctx.executor is not None:
            return io_ctx.executor.word_ev.eval_word_single(word.target)
        from spelaion.semantics.expand import expand_word_single

        return expand_word_single(word.target, state, vfs, cmdsub_hook)

    for redir in redirections:
        target_path = _expand_target(redir)
        op = redir.op
        fd = redir.fd
        abs_path = vfs.resolve(target_path, state.cwd)

        if abs_path == "/dev/null" and op in (">", ">>", "2>", "2>>", "<"):
            # No mount holds /dev: discard the output, or read nothing.
            if op == "<":
                io_ctx.stdin = StringIO()
            elif op.startswith("2") or fd == 2:
                io_ctx.stderr = StringIO()
            else:
                io_ctx.stdout = StringIO()
        elif op == "<<":
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
                io_ctx.stderr.write(
                    f"spelaion: {target_path}: No such file or directory\n"
                )
                raise RedirectionError(target_path) from None
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

    def __init__(self, vfs: Filesystem, path: str, append: bool) -> None:
        super().__init__()
        self._vfs = vfs
        self._path = path
        self._append = append

    @property
    def path(self) -> str:
        """The sandbox path this buffer writes to."""
        return self._path

    def flush_to_vfs(self) -> None:
        """Write accumulated content to VFS."""
        content = self.getvalue()
        self._vfs.write(self._path, content.encode("utf-8"), append=self._append)
