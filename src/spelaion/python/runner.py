"""Run CPython for WASI under wasmtime over a sandbox's mounts.

The guest sees the standard library at ``/lib`` and ``site/`` at ``/site``,
both read-only, and each mount at its own path. WASI gives it no sockets,
no processes and nothing outside those folders. A process compiles the
module once, or loads it from the cache, and keeps it for later calls.
"""

from __future__ import annotations

import errno
import functools
import tempfile
import threading
import time
from pathlib import Path

import wasmtime

from spelaion.python.fetch import PYTHON_WASI, cache_dir, compiled_name, site_name
from spelaion.vfs.mounts import MountFs

# Exit code for a call the epoch deadline stopped, as timeout(1) gives.
_TIMED_OUT = 124

_RESERVED = ("/lib", "/site")

_MISSING = (
    "python: CPython for WASI is missing from the cache; run spelaion fetch-python\n"
)

# How often the watcher samples the output files, the disk and the clock.
_TICK = 0.1

_modules: dict[Path, wasmtime.Module] = {}


@functools.cache
def engine() -> wasmtime.Engine:
    """This process's engine; every module and store here shares it."""
    config = wasmtime.Config()
    config.epoch_interruption = True
    return wasmtime.Engine(config)


@functools.cache
def _wasi_linker() -> wasmtime.Linker:
    linker = wasmtime.Linker(engine())
    linker.define_wasi()
    return linker


def compile_module(folder: Path) -> wasmtime.Module:
    """Compile *folder*'s ``python.wasm`` and serialise it beside it."""
    module = wasmtime.Module(engine(), (folder / "python.wasm").read_bytes())
    target = folder / compiled_name()
    with tempfile.NamedTemporaryFile(
        dir=folder, prefix=f"{target.name}.", delete=False
    ) as f:
        f.write(module.serialize())
    Path(f.name).replace(target)
    return module


def load_module(folder: Path) -> wasmtime.Module:
    """The compiled module for *folder*, loaded once per process."""
    module = _modules.get(folder)
    if module is None:
        path = folder / compiled_name()
        module = wasmtime.Module.deserialize_file(engine(), str(path))
        _modules[folder] = module
    return module


def reserved(path: str) -> bool:
    """Whether a mount at *path* would hide the guest's own folders."""
    return any(path == r or path.startswith(r + "/") for r in _RESERVED)


def run_raw(
    module: wasmtime.Module,
    argv: list[str],
    writable: dict[str, Path],
    readonly: dict[str, Path] | None = None,
) -> tuple[int, str]:
    """Run *argv* with guest folders *writable* and *readonly*; return code, stderr."""
    preopens = [(host, guest, True) for guest, host in writable.items()]
    preopens += [(host, guest, False) for guest, host in (readonly or {}).items()]
    with tempfile.TemporaryDirectory() as tmp:
        code, _, err = _run(
            module, argv, preopens=preopens, env={}, stdin="", tmp=Path(tmp)
        )
    return code, err


def run_python(
    args: list[str],
    *,
    stdin: str,
    cwd: str,
    env: dict[str, str],
    fs: MountFs,
    deadline: float,
    memory_mb: int,
    max_output: int,
) -> tuple[str, str, int]:
    """Run ``python ARGS`` in *cwd* until *deadline* (``time.monotonic``).

    Returns stdout, stderr and the exit code. The guest is stopped when it
    prints more than *max_output* characters could take, or leaves the
    writable mounts over the disk cap; what it printed is kept.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "", "python: timed out\n", _TIMED_OUT
    folder = prepared()
    if folder is None:
        return "", _MISSING, 127
    module = load_module(folder)
    site = folder / site_name()
    preopens = [(folder / "lib", "/lib", False), (site, "/site", False)]
    preopens += [
        (Path(m.host), m.path, not m.readonly)
        for m in fs.mounts
        if not reserved(m.path)
    ]
    guest_env = {
        **env,
        "PYTHONPATH": "/site",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PWD": cwd,
    }
    cap = fs.max_disk
    # UTF-8 takes at most 4 bytes a character; each output file must also
    # fit under the child's RLIMIT_FSIZE, which is the disk cap.
    out_limit = 4 * max_output if cap is None else min(4 * max_output, cap)
    with tempfile.TemporaryDirectory() as tmp:
        try:
            code, out, err = _run(
                module,
                ["python", "-m", "_boot", cwd, "--", *args],
                preopens=preopens,
                env=guest_env,
                stdin=stdin,
                tmp=Path(tmp),
                watch=_Watch(deadline, out_limit, fs),
                memory=memory_mb * 2**20,
            )
        except _StdinTooLarge:
            return "", f"python: stdin is larger than the disk cap ({cap} bytes)\n", 1
    if cap is not None:
        used = fs.disk_used()
        # RLIMIT_FSIZE stops a single file at the cap exactly, and the guest
        # then fails on its own: that is the cap too.
        if used > cap or (used == cap and code != 0):
            err += f"python: disk cap exceeded ({used} of {cap} bytes)\n"
            code = 1
    return out, err, code


def prepared() -> Path | None:
    """The prepared folder, if the cache holds all of it; never builds.

    Only the parent process builds it (:func:`ensure_python`): the child
    would build under its own memory limit and deadline.
    """
    folder = cache_dir() / f"python-{PYTHON_WASI['version']}"
    for part in (folder / "lib", folder / compiled_name(), folder / site_name()):
        if not part.exists():
            return None
    return folder


class _StdinTooLarge(Exception):
    pass


class _Watch:
    """Stops the guest at its deadline, past the output bound or the disk cap.

    A thread samples every ``_TICK`` seconds; the disk walk runs less often
    when it is slow, so it never takes more than a tenth of the time.
    """

    def __init__(self, deadline: float, out_limit: int, fs: MountFs) -> None:
        self.deadline = deadline
        self.out_limit = out_limit
        self.fs = fs
        self.reason = ""
        self._done = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, eng: wasmtime.Engine, outputs: list[Path]) -> None:
        self._thread = threading.Thread(
            target=self._loop, args=(eng, outputs), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._done.set()
        if self._thread is not None:
            self._thread.join()

    def _loop(self, eng: wasmtime.Engine, outputs: list[Path]) -> None:
        cap = self.fs.max_disk
        next_walk = 0.0
        while not self._done.wait(min(_TICK, max(0, self.deadline - time.monotonic()))):
            now = time.monotonic()
            if now >= self.deadline:
                self.reason = "timeout"
                break
            if sum(_size(p) for p in outputs) > self.out_limit:
                self.reason = "output"
                break
            if cap is not None and now >= next_walk:
                used = self.fs.disk_used()
                spent = time.monotonic() - now
                next_walk = time.monotonic() + max(0, 9 * spent)
                if used > cap:
                    self.reason = "disk"
                    break
        else:
            return
        eng.increment_epoch()


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _read(path: Path, limit: int | None) -> str:
    with path.open("rb") as f:
        data = f.read() if limit is None else f.read(limit)
    return data.decode("utf-8", errors="replace")


def _run(
    module: wasmtime.Module,
    argv: list[str],
    *,
    preopens: list[tuple[Path, str, bool]],
    env: dict[str, str],
    stdin: str,
    tmp: Path,
    watch: _Watch | None = None,
    memory: int | None = None,
) -> tuple[int, str, str]:
    eng = engine()
    store = wasmtime.Store(eng)
    if memory is not None:
        store.set_limits(memory_size=memory)
    store.set_epoch_deadline(1)
    wasi = wasmtime.WasiConfig()
    wasi.argv = argv
    wasi.env = list(env.items())
    for host, guest, mutable in preopens:
        wasi.preopen_dir(str(host), guest, mutable)
    stdin_path, out_path, err_path = tmp / "stdin", tmp / "stdout", tmp / "stderr"
    try:
        stdin_path.write_text(stdin, encoding="utf-8", errors="surrogateescape")
    except OSError as e:
        if e.errno == errno.EFBIG:
            raise _StdinTooLarge from e
        raise
    wasi.stdin_file = str(stdin_path)
    wasi.stdout_file = str(out_path)
    wasi.stderr_file = str(err_path)
    store.set_wasi(wasi)
    linker = _wasi_linker()
    if watch is not None:
        watch.start(eng, [out_path, err_path])
    note = ""
    try:
        start = linker.instantiate(store, module).exports(store)["_start"]
        assert isinstance(start, wasmtime.Func)
        start(store)
        code = 0
    except wasmtime.ExitTrap as e:
        code = e.code
    except wasmtime.Trap as e:
        if e.trap_code != wasmtime.TrapCode.INTERRUPT:
            note, code = f"python: {str(e).splitlines()[0]}\n", 1
        elif watch is not None and watch.reason == "output":
            note, code = "python: output limit reached\n", 1
        elif watch is not None and watch.reason == "disk":
            # run_python names the cap, which the mounts are still over.
            code = 1
        else:
            note, code = "python: timed out\n", _TIMED_OUT
    except wasmtime.WasmtimeError as e:
        note, code = f"python: {str(e).splitlines()[0]}\n", 1
    finally:
        if watch is not None:
            watch.stop()
    limit = None if watch is None else watch.out_limit
    return code, _read(out_path, limit), _read(err_path, limit) + note
