"""The sandbox's child process: one Shell, serving calls until the pipe closes."""

from __future__ import annotations

import os
import resource
import signal
from multiprocessing.connection import Connection

from spelaion._shell import Shell
from spelaion._types import Limits, Result
from spelaion._wire import TEST_HOOKS, Done, Host, ToChild
from spelaion.runtime.result import CommandResult
from spelaion.vfs.mounts import Mount


def main(
    conn: Connection,
    mounts: list[Mount],
    cwd: str,
    env: dict[str, str],
    limits: Limits,
    python: bool,
    host_names: set[str],
) -> None:
    """Serve ``call`` messages on *conn* until the parent closes it."""
    limit = limits.memory_mb * 2**20
    resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
    # Ctrl-C reaches the whole process group; the parent decides what stops.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    shell = Shell(mounts, cwd, env, limits)
    for name in host_names:
        shell.tools.register(name, _HostProxy(name, conn, shell))
    if os.environ.get(TEST_HOOKS) == "1":
        shell.tools.register("kill_self_for_test", _KillSelf())
    while True:
        try:
            msg: ToChild = conn.recv()
        except EOFError:
            return
        if msg[0] != "call":
            raise RuntimeError(f"unexpected message from the parent: {msg[0]}")
        done: Done = ("done", shell.call(msg[1], msg[2]))
        conn.send(done)


class _HostProxy:
    """Runs host command *name* in the parent and waits for its result."""

    def __init__(self, name: str, conn: Connection, shell: Shell) -> None:
        self._name = name
        self._conn = conn
        self._shell = shell

    @property
    def name(self) -> str:
        return self._name

    def invoke(self, args: list[str], stdin: str | None = None) -> CommandResult:
        request: Host = (
            "host",
            self._name,
            list(args),
            stdin or "",
            self._shell.cwd,
            dict(self._shell.env),
        )
        self._conn.send(request)
        msg = self._conn.recv()
        if msg[0] != "host_result":
            raise RuntimeError(f"unexpected message from the parent: {msg[0]}")
        result: Result = msg[1]
        return CommandResult(
            exit_code=result.exit_code, stdout=result.stdout, stderr=result.stderr
        )


class _KillSelf:
    """Test only: the child dies mid-call, as a kernel kill or segfault would."""

    @property
    def name(self) -> str:
        return "kill_self_for_test"

    def invoke(self, args: list[str], stdin: str | None = None) -> CommandResult:
        os._exit(9)
