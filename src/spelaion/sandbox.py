"""Sandbox: an emulated bash over host folders, with edit and write."""

from __future__ import annotations

import contextlib
import logging
import os
import pickle
import posixpath
import re
import socket
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import Callable
from multiprocessing.connection import Connection
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, TypeVar, cast, overload

from spelaion import _child
from spelaion._host import HostContext, HostHandler, add_attachment, show
from spelaion._tools import Tool, describe_bash, make_tools
from spelaion._types import Attachment, Limits, Result
from spelaion._wire import (
    BadMessage,
    Call,
    HostResult,
    Ready,
    Register,
    ToParent,
    decode,
    max_message,
)
from spelaion.semantics.resolve import BUILTIN_NAMES
from spelaion.vfs.mounts import Mount, MountFs

if TYPE_CHECKING:
    from spelaion._mcp import McpServer

H = TypeVar("H", bound=HostHandler)

_DEFAULT_LIMITS = Limits()

# A child starts in about 0.2 s; this only catches one that never does.
_START_TIMEOUT_S = 60

# A child that closed its socket exits at once; this only catches one that
# hangs on its way out.
_REAP_TIMEOUT_S = 5

# Letters, digits, "-", "_" and "."; a leading "-" would read as an option.
_COMMAND_NAME = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_.-]*")

# Words the parser reads as syntax wherever a command name could stand.
_KEYWORDS = frozenset(
    {"if", "then", "else", "elif", "fi", "do", "done", "case", "esac", "while"}
    | {"until", "for", "in", "function", "select", "time"}
)

_log = logging.getLogger("spelaion")


class Sandbox:
    """The three agent tools, ``bash``, ``edit`` and ``write``, over *mounts*.

    Files persist between calls; shell state (variables, functions, the
    working directory) starts afresh from *cwd* and *env* on every call.
    The shell runs in a child Python process under a memory limit, killed
    and restarted when a call outlives ``limits.timeout_s``. The child is
    its own entry point: it never imports the host's main script.

    Host commands (:meth:`command`) run in this process; ``show`` is one.
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
        # Each sandbox path normalised and each host folder resolved once, here:
        # a restarted child must not resolve a relative host against a later cwd.
        given = mounts
        mounts = [
            Mount(_normalize(m.path), Path(m.host).resolve(), m.readonly)
            for m in given
        ]
        _check_mounts(mounts)
        # The prepared folder, absolute, so a restarted child never reads
        # SPELAION_CACHE or a relative path again.
        self._python_folder: Path | None = None
        if python:
            from spelaion.python.fetch import cache_dir, ensure_python
            from spelaion.python.runner import reserved

            cache = cache_dir().resolve()
            for m in mounts:
                if reserved(m.path):
                    raise ValueError(
                        f"mount {m.path}: /lib and /site belong to python here"
                    )
                host = Path(m.host)
                # The cache holds native code the next process loads.
                if not m.readonly and (
                    cache.is_relative_to(host) or host.is_relative_to(cache)
                ):
                    raise ValueError(
                        f"mount {m.path}: a writable mount must not hold or lie "
                        f"inside the python cache {cache}"
                    )
            self._python_folder = ensure_python().resolve()
        fs = MountFs(list(mounts), max_disk=limits.max_disk)
        if not cwd.startswith("/") or not fs.is_dir(cwd):
            raise ValueError(f"cwd {cwd} is not an absolute path to a folder")
        self.limits = limits
        self.python = python
        self._mounts = list(mounts)
        self._cwd = cwd
        self._env = dict(env or {})
        self._fs = fs
        # Each mount's host folder, resolved and as given, longest first: an
        # exception's text names its sandbox path instead.
        hosts = {str(m.host): m.path for m in mounts}
        hosts.update(
            {
                str(Path(g.host)): m.path
                for g, m in zip(given, mounts, strict=True)
                if os.path.isabs(g.host)
            }
        )
        self._host_roots = sorted(
            ((h, p) for h, p in hosts.items() if h != "/"), key=lambda hp: -len(hp[0])
        )
        self._handlers: dict[str, HostHandler] = {"show": show}
        # What the child knows: all of these at start, the rest by "register".
        self._host_names: set[str] = set(self._handlers)
        self._unannounced: list[str] = []
        self._register_lock = threading.Lock()
        # Per call: its deadline and the attachments its host commands made.
        self._deadline = 0.0
        self._attachments: list[Attachment] = []
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

    def tools(self) -> list[Tool]:
        """``bash``, ``edit`` and ``write`` for an agent loop in this process.

        ``bash``'s description names the mounts, the working directory and
        the host commands registered when this is called.
        """
        description = describe_bash(
            self._mounts,
            self._cwd,
            self.python,
            list(self._handlers),
            self.limits.timeout_s,
        )
        return make_tools(self.bash, self.edit, self.write, description)

    def serve_mcp(
        self, host: str = "127.0.0.1", port: int = 0, token: str | None = None
    ) -> McpServer:
        """Serve :meth:`tools` over MCP's streamable HTTP at ``McpServer.url``.

        It listens on *host* only, at *port*, or a free port for 0, from a
        background thread. With a *token*, a request without the header
        ``Authorization: Bearer <token>`` gets 401; a *host* beyond loopback
        without a token raises ``ValueError``. Calls arriving together
        run one after the other. Each ``tools/list`` reads the host commands
        registered by then. Closing the sandbox does not stop the server:
        call ``McpServer.stop()``.
        """
        from spelaion._mcp import McpServer

        return McpServer(self.tools, host, port, token)

    @overload
    def command(self, name: str, /) -> Callable[[H], H]: ...
    @overload
    def command(self, name: H, /) -> H: ...
    def command(self, name: str | H, /) -> Callable[[H], H] | H:
        """Register a host command, as ``@sb.command`` or ``@sb.command("name")``.

        Bare, the name is the function's with ``_`` as ``-``: ``oikos_check``
        is ``oikos-check``. The function is returned unchanged. It runs in
        this process, called as ``handler(ctx, args)`` with a
        :class:`HostContext` and the arguments as the shell expanded them,
        and returns a :class:`Result`, which carries all of its output:
        what it prints goes to this process's own stdout and stderr, not the
        agent's. An exception it raises becomes ``name: message`` on stderr
        with exit code 1. ``SystemExit`` (argparse's, say) ends the command
        with its code, or with its message and exit code 1. Exit codes wrap
        to 0-255, as in bash. A
        ``KeyboardInterrupt`` ends the command and is raised from the call.

        ``ctx.remaining_s`` is the time left before the call's deadline,
        measured here. A handler that runs past it is not interrupted, but
        the call then returns the timeout result (exit 124) and the child
        restarts. Registering works before or after the first call; a name
        must be a command word, not a shell keyword or builtin, and not taken.
        """
        if callable(name):
            return self._register(name.__name__.replace("_", "-"), name)
        key = name
        self._check_name(key)

        def register(handler: H) -> H:
            return self._register(key, handler)

        return register

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

    def _check_name(self, name: str) -> None:
        if not _COMMAND_NAME.fullmatch(name):
            raise ValueError(f"{name!r} is not a command name")
        if name in _KEYWORDS:
            raise ValueError(f"{name} is a shell keyword")
        if name in BUILTIN_NAMES:
            raise ValueError(f"{name} is a builtin command")

    def _register(self, name: str, handler: H) -> H:
        self._check_name(name)
        with self._register_lock:
            if name in self._handlers:
                raise ValueError(f"host command {name} is already registered")
            self._handlers[name] = handler
            self._host_names.add(name)
            self._unannounced.append(name)
        return handler

    def _announce(self) -> None:
        """Tell a running child about the host commands registered since."""
        with self._register_lock:
            names, self._unannounced = self._unannounced, []
        for name in names:
            msg: Register = ("register", name)
            self._conn.send(msg)

    def _serve_host(
        self, name: str, args: list[str], stdin: str, cwd: str, env: dict[str, str]
    ) -> Result:
        """Run host command *name* in this process for the child."""
        handler = self._handlers.get(name)
        if handler is None:
            return Result(stderr=f"{name}: command not found\n", exit_code=127)
        ctx = HostContext(
            stdin=stdin,
            cwd=cwd,
            env=env,
            remaining_s=max(0.0, self._deadline - time.monotonic()),
            _fs=self._fs,
            _attachments=self._attachments,
        )
        try:
            result = cast(object, handler(ctx, args))
        except SystemExit as e:
            if e.code is None or isinstance(e.code, int):
                return Result(exit_code=int(e.code or 0) & 255)
            text = self._hide_hosts(str(e.code))
            return Result(stderr=f"{name}: {text}\n", exit_code=1)
        except Exception as e:
            return Result(stderr=f"{name}: {self._describe(e, ctx)}\n", exit_code=1)
        if not isinstance(result, Result):
            raise TypeError(f"host command {name} returned {type(result).__name__}")
        try:
            for attachment in result.attachments:
                add_attachment(self._attachments, attachment)
        except ValueError as e:
            stderr = f"{result.stderr}{name}: {e}\n"
            return Result(stdout=result.stdout, stderr=stderr, exit_code=1)
        # The child needs only the text; images stay here for the call's Result.
        # Exit codes wrap to 0-255, as in bash.
        return Result(
            stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code & 255
        )

    def _describe(self, e: Exception, ctx: HostContext) -> str:
        """A handler's exception as a message that names no host path."""
        if not isinstance(e, OSError):
            return self._hide_hosts(str(e) or type(e).__name__)
        reason = e.strerror or (os.strerror(e.errno) if e.errno else type(e).__name__)
        if any(e is r for r in ctx._raised):  # pyright: ignore[reportPrivateUsage]
            return self._hide_hosts(f"{e.filename}: {reason}")
        shown = self._sandbox_path(e.filename)
        return self._hide_hosts(f"{shown}: {reason}" if shown else reason)

    def _hide_hosts(self, text: str) -> str:
        """*text* with each mount's host folder written as its sandbox path."""
        for host, path in self._host_roots:
            # The host folder itself, or a path under it, not a longer name.
            text = re.sub(
                re.escape(host) + r"(/|(?![\w.-]))",
                lambda m, path=path: path.rstrip("/") + "/" if m[1] else path,
                text,
            )
        return text

    def _sandbox_path(self, filename: object) -> str | None:
        """The sandbox path for a host path inside a mount, else None."""
        if not isinstance(filename, str) or not filename.startswith("/"):
            return None
        host = Path(os.path.normpath(filename))
        for m in self._mounts:
            root = Path(m.host)
            if host.is_relative_to(root):
                rel = host.relative_to(root).as_posix()
                return m.path if rel == "." else m.path.rstrip("/") + "/" + rel
        return None

    def _call(self, kind: str, payload: dict[str, Any]) -> Result:
        with self._lock:
            if self._closing.is_set():
                raise RuntimeError("the sandbox is closed")
            if self._process.poll() is not None:
                self._restart()
            try:
                try:
                    return self._exchange(kind, payload)
                except (BrokenPipeError, ConnectionResetError):
                    # The child died before reading the call, so it never ran.
                    self._restart()
                try:
                    return self._exchange(kind, payload)
                except (EOFError, OSError):
                    return self._died()
            except KeyboardInterrupt:
                # The child is somewhere in the call; the next one needs a
                # child that is not.
                self._restart()
                raise

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
        except BadMessage as e:
            return self._refused(e)
        self._announce()
        timeout = self.limits.timeout_s
        deadline = time.monotonic() + timeout
        self._deadline = deadline
        self._attachments = []
        call: Call = ("call", kind, payload)
        self._conn.send(call)
        served = False
        try:
            while self._wait(deadline):
                msg = cast(ToParent, self._recv("done", "host"))
                if msg[0] == "done":
                    result = msg[1]
                    result.attachments = self._attachments
                    return result
                served = True
                try:
                    reply: HostResult = ("host_result", self._host(*msg[1:]))
                except KeyboardInterrupt:
                    # Answer so the child is not left waiting; _call then
                    # restarts it, since its done would answer the next call.
                    stopped = Result(stderr=f"{msg[1]}: interrupted\n", exit_code=130)
                    # A dead child must not turn the interrupt into a retry.
                    with contextlib.suppress(OSError):
                        self._conn.send(("host_result", stopped))
                    raise
                self._conn.send(reply)
        except BadMessage as e:
            return self._refused(e)
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
        self._recv("ready")
        self._ready = True

    def _recv(self, *tags: str) -> ToParent | Ready:
        """The child's next message, one of *tags*; raises BadMessage."""
        try:
            data = self._conn.recv_bytes(max_message(self.limits))
        except OSError:
            # Connection stops reading after a message past maxlength.
            if not self._conn.readable:
                raise BadMessage("an oversized message") from None
            raise
        return decode(data, tags)

    def _refused(self, e: BadMessage) -> Result:
        """The child broke the protocol: it is not trusted to go on."""
        self._restart()
        return Result(stderr=f"spelaion: child sent {e}; restarted\n", exit_code=125)

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
        except KeyboardInterrupt:
            raise
        except BaseException:
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
        with self._register_lock:
            # This child gets them all at start.
            host_names = set(self._host_names)
            self._unannounced = []
        args = (
            self._mounts,
            self._cwd,
            self._env,
            self.limits,
            self._python_folder,
            host_names,
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


def _normalize(path: str) -> str:
    """A sandbox path normalised lexically, as MountFs reads it."""
    return "/" + posixpath.normpath("/" + path.lstrip("/")).lstrip("/")


def _check_mounts(mounts: list[Mount]) -> None:
    """Every host folder exists, no host folder lies inside another, and no
    two mounts share a sandbox path."""
    paths: dict[str, Mount] = {}
    for m in mounts:
        path = posixpath.normpath("/" + m.path.lstrip("/"))
        if path in paths:
            raise ValueError(
                f"mounts {paths[path].path} and {m.path} have the same sandbox path"
            )
        paths[path] = m
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
