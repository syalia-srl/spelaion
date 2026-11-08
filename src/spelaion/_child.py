"""The sandbox's child process: one Shell, serving calls until the socket closes.

The parent starts ``python -I -c BOOTSTRAP <fd>``. The first message on *fd*
is the parent's ``sys.path`` and the pickled startup arguments, so the child
finds spelaion wherever the parent found it, and never imports the host's
main script.
"""

from __future__ import annotations

import os
import pickle
import resource
import signal
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import TYPE_CHECKING

from spelaion._shell import OUT_OF_MEMORY, Shell
from spelaion._types import Limits, Result
from spelaion._wire import TEST_HOOKS, Done, Host, Ready, ToChild, max_message
from spelaion.commands import python_cmd as python_cmds
from spelaion.runtime.result import CommandResult
from spelaion.vfs.mounts import Mount, MountFs

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem

# Runs before spelaion is importable: only the standard library.
BOOTSTRAP = (
    "import sys\n"
    "from multiprocessing.connection import Connection\n"
    "conn = Connection(int(sys.argv[1]))\n"
    "sys.path[:], args = conn.recv()\n"
    "from spelaion._child import serve\n"
    "serve(conn, args)\n"
)

# The child's own deadline is the parent's plus this, so it only fires when
# the parent died mid-call and can no longer kill the child.
GRACE = 5.0

# The guest's epoch deadline is this much after the call's, so the parent
# always reports the timeout first; the epoch only backs up the parent.
PYTHON_LAG = 0.5

# Under TEST_HOOKS, replaces GRACE so a test can outlive the child's timer fast.
TEST_GRACE = "SPELAION_TEST_GRACE"


def serve(conn: Connection, args: bytes) -> None:
    """Unpickle the startup arguments from *args* and run :func:`main`."""
    main(conn, *pickle.loads(args))


def main(
    conn: Connection,
    mounts: list[Mount],
    cwd: str,
    env: dict[str, str],
    limits: Limits,
    python: Path | None,
    host_names: set[str],
) -> None:
    """Serve ``call`` messages on *conn* until the parent closes it.

    *python* is the prepared CPython for WASI folder, or None for no python.
    """
    limit = limits.memory_mb * 2**20
    resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
    # No single file the child writes passes the disk cap; a write past it
    # fails with EFBIG instead of ending the process.
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limits.max_disk, limits.max_disk))
    # Ctrl-C reaches the whole process group; the parent decides what stops.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # SIGALRM's default action ends the process even inside a C loop (a
    # catastrophic regex), where a Python handler would never run.
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    shell = Shell(mounts, cwd, env, limits)
    python_cmd = _Python(limits, python) if python is not None else None
    if python_cmd is not None:
        python_cmds.install(python_cmd)
    bound = max_message(limits)
    for name in host_names:
        shell.tools.register(name, _HostProxy(name, conn, shell, bound))
    grace = GRACE
    if os.environ.get(TEST_HOOKS) == "1":
        shell.tools.register("kill_self_for_test", _KillSelf())
        shell.tools.register("forge_for_test", _Forge(conn, bound))
        grace = float(os.environ.get(TEST_GRACE, GRACE))
    ready: Ready = ("ready",)
    conn.send(ready)
    while True:
        try:
            msg: ToChild = conn.recv()
        except EOFError:
            return
        if msg[0] == "register":
            shell.tools.register(msg[1], _HostProxy(msg[1], conn, shell, bound))
            continue
        if msg[0] != "call":
            raise RuntimeError(f"unexpected message from the parent: {msg[0]}")
        signal.setitimer(signal.ITIMER_REAL, limits.timeout_s + grace)
        if python_cmd is not None:
            # After the parent's deadline as known here; the itimer fires later.
            python_cmd.deadline = time.monotonic() + limits.timeout_s + PYTHON_LAG
        try:
            result = shell.call(msg[1], msg[2])
        except MemoryError:
            result = Result(stderr=OUT_OF_MEMORY, exit_code=1)
        done: Done = ("done", result)
        conn.send(done)
        signal.setitimer(signal.ITIMER_REAL, 0)


class _Python:
    """``python`` and ``python3``: CPython for WASI over the shell's mounts."""

    def __init__(self, limits: Limits, folder: Path) -> None:
        self.limits = limits
        self.folder = folder
        self.deadline = 0.0

    def __call__(
        self, args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
    ) -> CommandResult:
        from spelaion.python.runner import run_python

        assert isinstance(vfs, MountFs)
        out, err, code = run_python(
            args,
            stdin=io.stdin.read(),
            cwd=state.cwd,
            env=dict(state.exported_env),
            fs=vfs,
            folder=self.folder,
            deadline=self.deadline,
            memory_mb=self.limits.memory_mb,
            max_output=self.limits.max_output,
        )
        io.stdout.write(out)
        io.stderr.write(err)
        return CommandResult(exit_code=code)


class _HostProxy:
    """Runs host command *name* in the parent and waits for its result.

    The executor calls :meth:`invoke_in` with the calling shell's state, so
    the parent sees the live cwd and exported variables. A request over
    *bound* bytes, which the parent would refuse, is never sent.
    """

    def __init__(self, name: str, conn: Connection, shell: Shell, bound: int) -> None:
        self._name = name
        self._conn = conn
        self._shell = shell
        self._bound = bound

    @property
    def name(self) -> str:
        return self._name

    def invoke(self, args: list[str], stdin: str | None = None) -> CommandResult:
        return self._send(args, stdin, self._shell.cwd, dict(self._shell.env))

    def invoke_in(
        self, state: ShellState, args: list[str], stdin: str | None = None
    ) -> CommandResult:
        return self._send(args, stdin, state.cwd, dict(state.exported_env))

    def _send(
        self, args: list[str], stdin: str | None, cwd: str, env: dict[str, str]
    ) -> CommandResult:
        request: Host = ("host", self._name, list(args), stdin or "", cwd, env)
        data = pickle.dumps(request)
        if len(data) > self._bound:
            return CommandResult(exit_code=1, stderr=f"{self._name}: input too large\n")
        self._conn.send_bytes(data)
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


class _Forge:
    """Test only: send the parent a message it must refuse, then wait to die.

    ``forge_for_test class MARKER`` sends a pickle that would create MARKER
    if the parent loaded any class; ``big`` one past the size bound;
    ``shape`` a message of the wrong shape.
    """

    def __init__(self, conn: Connection, bound: int) -> None:
        self._conn = conn
        self._bound = bound

    @property
    def name(self) -> str:
        return "forge_for_test"

    def invoke(self, args: list[str], stdin: str | None = None) -> CommandResult:
        if args[0] == "class":
            self._conn.send_bytes(pickle.dumps(("done", _Opens(args[1]))))
        elif args[0] == "big":
            self._conn.send_bytes(b"\0" * (self._bound + 1))
        else:
            self._conn.send(("host", 1))
        try:
            self._conn.recv()
        finally:
            os._exit(1)


class _Opens:
    def __init__(self, path: str) -> None:
        self.path = path

    def __reduce__(self) -> tuple[object, tuple[str, str]]:
        return (open, (self.path, "w"))
