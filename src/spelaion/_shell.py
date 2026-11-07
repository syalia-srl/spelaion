"""One sandbox call at a time over a MountFs: the shell, edit and write.

The sandbox runs this in its own process for now; it is kept apart from
:class:`~spelaion.sandbox.Sandbox` so a child process can run it instead.
"""

from __future__ import annotations

import os
from typing import Any

from spelaion._truncate import truncate
from spelaion._types import Limits, Result
from spelaion.exec.executor import Executor
from spelaion.exec.redirs import IOContext
from spelaion.parser.frontend import parse_script
from spelaion.parser.normalize import normalize
from spelaion.policy.decisions import PolicyEngine
from spelaion.policy.rules import PolicyConfig
from spelaion.runtime.state import ShellState
from spelaion.tools.registry import ToolRegistry
from spelaion.vfs.mounts import Mount, MountFs

_CONTEXT_LINES = 3


class Shell:
    """Runs ``bash``, ``edit`` and ``write`` calls; files persist, state does not."""

    def __init__(
        self, mounts: list[Mount], cwd: str, env: dict[str, str], limits: Limits
    ) -> None:
        self.fs = MountFs(mounts, max_disk=limits.max_disk)
        self.cwd = cwd
        self.env = env
        self.limits = limits

    def call(self, kind: str, payload: dict[str, Any]) -> Result:
        """Run one call (*kind* is ``bash``, ``edit`` or ``write``)."""
        if kind == "bash":
            result = self.bash(payload["command"])
        elif kind == "edit":
            result = self.edit(payload["path"], payload["old"], payload["new"])
        elif kind == "write":
            result = self.write(payload["path"], payload["content"])
        else:
            raise ValueError(f"unknown call kind: {kind}")
        result.stdout = truncate(result.stdout, self.limits.max_output)
        result.stderr = truncate(result.stderr, self.limits.max_output)
        return result

    def bash(self, command: str) -> Result:
        state = ShellState()
        state.cwd = self.cwd
        state.set_var("PWD", self.cwd)
        for name, value in self.env.items():
            state.set_var(name, value)
            state.export_var(name, value)

        parsed = parse_script(command)
        if parsed.has_errors:
            return Result(stderr="spelaion: syntax error\n", exit_code=2)
        program, _diags = normalize(parsed.root_node, command)

        executor = Executor(
            state=state,
            vfs=self.fs,
            tools=ToolRegistry(),
            policy=PolicyEngine(config=PolicyConfig()),
        )
        io = IOContext()
        try:
            exit_code = executor.execute_node(program, io).exit_code
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            # A command bug must come back as a result, not end the call.
            io.stderr.write(f"spelaion: internal error: {type(e).__name__}: {e}\n")
            exit_code = 1
        return Result(
            stdout=io.stdout.getvalue(),
            stderr=io.stderr.getvalue(),
            exit_code=exit_code,
        )

    def write(self, path: str, content: str) -> Result:
        path = self.fs.resolve(path, self.cwd)
        try:
            self.fs.write(path, content.encode("utf-8"))
        except OSError as e:
            return _failed("write", path, e)
        return Result()

    def edit(self, path: str, old: str, new: str) -> Result:
        path = self.fs.resolve(path, self.cwd)
        shown = _shown(path)
        if not old:
            return Result(stderr="edit: old text is empty\n", exit_code=1)
        try:
            # Refuse a read-only file before reading it.
            self.fs.host_path(path, write=True)
            text = self.fs.read(path).decode("utf-8", errors="replace")
        except OSError as e:
            return _failed("edit", path, e)
        n = text.count(old)
        if n == 0:
            return Result(stderr=f"old text not found in {shown}\n", exit_code=1)
        if n > 1:
            return Result(
                stderr=(
                    f"old text occurs {n} times in {shown}; "
                    "include more surrounding lines to make it unique\n"
                ),
                exit_code=1,
            )
        start = text.index(old)
        updated = text[:start] + new + text[start + len(old) :]
        try:
            self.fs.write(path, updated.encode("utf-8"))
        except OSError as e:
            return _failed("edit", path, e)
        return Result(stdout=_context(updated, start, len(new)))


def _shown(path: str) -> str:
    return path.replace("\0", "\\0")


def _failed(cmd: str, path: str, e: OSError) -> Result:
    # MountFs errors name sandbox paths; print only the reason beside ours.
    reason = os.strerror(e.errno) if e.errno else "Input/output error"
    return Result(stderr=f"{cmd}: {_shown(path)}: {reason}\n", exit_code=1)


def _context(text: str, start: int, length: int) -> str:
    """The changed lines of *text* with up to three lines either side."""
    lines = text.splitlines(keepends=True)
    first = text.count("\n", 0, start)
    last = text.count("\n", 0, max(start, start + length - 1))
    lo = max(0, first - _CONTEXT_LINES)
    hi = min(len(lines), last + 1 + _CONTEXT_LINES)
    return "".join(lines[lo:hi])
