"""One sandbox call at a time over a MountFs: the shell, edit and write.

The sandbox's child process (:mod:`spelaion._child`) runs one of these.
"""

from __future__ import annotations

import logging
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

_log = logging.getLogger("spelaion")


class Shell:
    """Runs ``bash``, ``edit`` and ``write`` calls; files persist, state does not."""

    def __init__(
        self, mounts: list[Mount], cwd: str, env: dict[str, str], limits: Limits
    ) -> None:
        self.fs = MountFs(mounts, max_disk=limits.max_disk)
        self.cwd = cwd
        self.env = env
        self.limits = limits
        self.tools = ToolRegistry()

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

        try:
            command.encode("utf-8")
        except UnicodeError:
            return Result(
                stderr="spelaion: command is not valid Unicode text\n", exit_code=2
            )
        io = IOContext()
        try:
            parsed = parse_script(command)
            if parsed.has_errors:
                return Result(stderr="spelaion: syntax error\n", exit_code=2)
            program, _diags = normalize(parsed.root_node, command)
            executor = Executor(
                state=state,
                vfs=self.fs,
                tools=self.tools,
                policy=PolicyEngine(config=PolicyConfig()),
            )
            exit_code = executor.execute_node(program, io).exit_code
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 0
        except Exception as e:
            # A command bug must come back as a result, not end the call.
            _log.exception("internal error running a bash call")
            io.stderr.write(f"spelaion: internal error: {_describe(e)}\n")
            exit_code = 1
        return Result(
            stdout=io.stdout.getvalue(),
            stderr=io.stderr.getvalue(),
            exit_code=exit_code,
        )

    def write(self, path: str, content: str) -> Result:
        path = self.fs.resolve(path, self.cwd)
        try:
            data = content.encode("utf-8")
        except UnicodeError:
            return _not_unicode("write", "content")
        try:
            self.fs.write(path, data)
        except OSError as e:
            return _failed("write", path, e)
        except UnicodeError:
            return _not_unicode("write", "path")
        return Result()

    def edit(self, path: str, old: str, new: str) -> Result:
        path = self.fs.resolve(path, self.cwd)
        shown = _shown(path)
        if not old:
            return Result(stderr="edit: old text is empty\n", exit_code=1)
        try:
            # Refuse a read-only file before reading it.
            self.fs.host_path(path, write=True)
            text = self.fs.read(path).decode("utf-8")
        except OSError as e:
            return _failed("edit", path, e)
        except UnicodeDecodeError:
            return Result(stderr=f"edit: {shown}: not UTF-8 text\n", exit_code=1)
        except UnicodeError:
            return _not_unicode("edit", "path")
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
            data = updated.encode("utf-8")
        except UnicodeError:
            return _not_unicode("edit", "new text")
        try:
            self.fs.write(path, data)
        except OSError as e:
            return _failed("edit", path, e)
        return Result(stdout=_context(updated, start, len(new)))


def _shown(path: str) -> str:
    # A host name that is not UTF-8 decodes to lone surrogates; escape them.
    shown = path.replace("\0", "\\0")
    return shown.encode("utf-8", "backslashreplace").decode("utf-8")


def _not_unicode(cmd: str, what: str) -> Result:
    return Result(stderr=f"{cmd}: {what} is not valid Unicode text\n", exit_code=1)


def _describe(e: Exception) -> str:
    # An OSError's str() may name a host path; its reason alone cannot.
    if isinstance(e, OSError):
        reason = e.strerror or (os.strerror(e.errno) if e.errno else "")
        return f"{type(e).__name__}: {reason or 'Input/output error'}"
    return f"{type(e).__name__}: {e}"


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
