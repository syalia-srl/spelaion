"""Sandbox: an emulated bash over host folders, with edit and write."""

from __future__ import annotations

import logging
import pickle
import socket
import subprocess
import sys
import threading
import time
import weakref
from multiprocessing.connection import Connection
from pathlib import Path
from types import TracebackType
from typing import Any

from spelaion import _child
from spelaion._types import Limits, Result
from spelaion._wire import Call, HostResult, Ready, ToParent
from spelaion.vfs.mounts import Mount, MountFs

_DEFAULT_LIMITS = Limits()

# A child starts in about 0.2 s; this only catches one that never does.
_START_TIMEOUT_S = 60

# A child that closed its socket exits at once; this only catches one that
# hangs on its way out.
_REAP_TIMEOUT_S = 5

_log = logging.getLogger("spelaion")


class Sandbox:
    """The three agent tools, ``bash``, ``edit`` and ``write``, over *mounts*.

    Files persist between calls; shell state (variables, functions, the
    working directory) starts afresh from *cwd* and *env* on every call.
    The shell runs in a child Python process under a memory limit, killed
    and restarted when a call outlives ``limits.timeout_s``. The child is
    its own entry point: it never imports the host's main script.
    """

    def __init__(
        self,
        mounts: list[Mount],
        *,
        cwd: str = "/",
        env: dict[str, str] | None = None,
        limits: Limits = _DEFAULT_LIMITS,
        python: bool = False,
    ) -> None:
        _check_mounts(mounts)
        fs = MountFs(list(mounts), max_disk=limits.max_disk)
        if not cwd.startswith("/") or not fs.is_dir(cwd):
            raise ValueError(f"cwd {cwd} is not an absolute path to a folder")
        self.limits = limits
        self.python = python
        self._mounts = list(mounts)
        self._cwd = cwd
        self._env = dict(env or {})
        self._host_names: set[str] = set()
        self._lock = threading.Lock()
        # Set by close() and the finalizer: no new child after it.
        self._closing = threading.Event()
        self._start()

    def bash(self, command: str) -> Result:
        """Run *command* in a fresh shell."""
        return self._call("bash", {"command": command})

    def edit(self, path: str, old: str, new: str) -> Result:
        """Replace the one occurrence of *old* in *path* with *new*."""
        return self._call("edit", {"path": path, "old": old, "new": new})

    def write(self, path: str, content: str) -> Result:
        """Create or overwrite *path* with *content*."""
        return self._call("write", {"path": path, "content": content})

    def close(self) -> None:
        """Stop the child process; later calls raise RuntimeError."""
        with self._lock:
            self._closing.set()
            self._finalizer()

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    @property
    def _child_pid(self) -> int:
        return self._process.pid

    def _serve_host(
        self, name: str, args: list[str], stdin: str, cwd: str, env: dict[str, str]
    ) -> Result:
        """Run host command *name* in this process for the child."""
        raise NotImplementedError(f"host command {name} is not available")

    def _call(self, kind: str, payload: dict[str, Any]) -> Result:
        with self._lock:
            if self._closing.is_set():
                raise RuntimeError("the sandbox is closed")
            if self._process.poll() is not None:
                self._restart()
            try:
                return self._exchange(kind, payload)
            except (BrokenPipeError, ConnectionResetError):
                # The child died before reading the call, so it never ran.
                self._restart()
            try:
                return self._exchange(kind, payload)
            except (EOFError, OSError):
                return self._died()

    def _exchange(self, kind: str, payload: dict[str, Any]) -> Result:
        """Send one call and serve the child until it is done or the deadline.

        Raises BrokenPipeError or ConnectionResetError when the child died
        without reading the call: a Unix socket closed with unread data
        resets its peer. A child that died after reading it gives a result.
        """
        try:
            if not self._ready:
                self._await_ready()
        except EOFError:
            return self._died()
        timeout = self.limits.timeout_s
        deadline = time.monotonic() + timeout
        call: Call = ("call", kind, payload)
        self._conn.send(call)
        served = False
        try:
            while self._wait(deadline):
                msg: ToParent = self._conn.recv()
                if msg[0] == "done":
                    return msg[1]
                served = True
                reply: HostResult = ("host_result", self._host(*msg[1:]))
                self._conn.send(reply)
        # Past the deadline, a dead child is a timeout: its own timer
        # (timeout_s + GRACE) ends it while a slow host command runs here.
        except EOFError:
            if time.monotonic() < deadline:
                return self._died()
        except OSError:
            if time.monotonic() < deadline:
                if not served:
                    raise
                return self._died()
        self._restart()
        return Result(
            stderr=f"spelaion: timed out after {timeout:g}s\n",
            exit_code=124,
            timed_out=True,
        )

    def _wait(self, deadline: float) -> bool:
        remaining = deadline - time.monotonic()
        return remaining > 0 and self._conn.poll(remaining)

    def _await_ready(self) -> None:
        """Wait for a (re)started child, so its start is not charged to a call."""
        if not self._conn.poll(_START_TIMEOUT_S):
            self._process.kill()
            raise EOFError
        msg: Ready = self._conn.recv()
        if msg[0] != "ready":
            raise RuntimeError(f"unexpected message from the child: {msg[0]}")
        self._ready = True

    def _died(self) -> Result:
        try:
            code = self._process.wait(_REAP_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            self._process.kill()
            code = self._process.wait()
        self._restart()
        return Result(
            stderr=f"spelaion: child exited ({code}); restarted\n", exit_code=125
        )

    def _host(
        self, name: str, args: list[str], stdin: str, cwd: str, env: dict[str, str]
    ) -> Result:
        try:
            return self._serve_host(name, args, stdin, cwd, env)
        except Exception:
            # The child waits for an answer; a failure must still send one.
            _log.exception("internal error running host command %s", name)
            return Result(stderr=f"{name}: internal error\n", exit_code=1)

    def _start(self) -> None:
        ours, theirs = socket.socketpair()
        fd = theirs.fileno()
        process = subprocess.Popen(
            # -I: the child's sys.path is the parent's, sent first.
            [sys.executable, "-I", "-c", _child.BOOTSTRAP, str(fd)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            pass_fds=(fd,),
            close_fds=True,
        )
        theirs.close()
        conn = Connection(ours.detach())
        args = (
            self._mounts,
            self._cwd,
            self._env,
            self.limits,
            self.python,
            set(self._host_names),
        )
        conn.send((sys.path, pickle.dumps(args)))
        self._process = process
        self._conn = conn
        self._ready = False
        # Also stops the child when the Sandbox is collected without close(),
        # and at interpreter exit. A child whose parent dies gets EOF, or its
        # own timer ends it if the parent died mid-call.
        self._finalizer = weakref.finalize(
            self, _shut_down, self._closing, process, conn
        )

    def _restart(self) -> None:
        self._finalizer.detach()
        _stop_child(self._process, self._conn)
        if self._closing.is_set():
            raise RuntimeError("the sandbox is closed")
        self._start()


def _shut_down(
    closing: threading.Event, process: subprocess.Popen[bytes], conn: Connection
) -> None:
    closing.set()
    _stop_child(process, conn)


def _stop_child(process: subprocess.Popen[bytes], conn: Connection) -> None:
    conn.close()
    process.kill()
    process.wait()


def _check_mounts(mounts: list[Mount]) -> None:
    """Every host folder exists, and no host folder lies inside another."""
    hosts: list[tuple[Mount, Path]] = []
    for m in mounts:
        host = Path(m.host).resolve()
        if not host.is_dir():
            raise FileNotFoundError(
                f"mount {m.path}: host folder {m.host} is missing or not a folder"
            )
        hosts.append((m, host))
    for i, (a, ha) in enumerate(hosts):
        for b, hb in hosts[i + 1 :]:
            if ha.is_relative_to(hb) or hb.is_relative_to(ha):
                raise ValueError(
                    f"mounts {a.path} and {b.path} overlap: their host folders "
                    f"{a.host} and {b.host} are the same or nested"
                )
