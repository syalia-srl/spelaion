"""Run CPython for WASI under wasmtime over a sandbox's mounts.

The guest sees the standard library at ``/lib`` and ``site/`` at ``/site``,
both read-only, and each mount at its own path. WASI gives it no sockets,
no processes and nothing outside those folders. A process compiles the
module once, or loads it from the cache, and keeps it for later calls.
"""

from __future__ import annotations

import functools
import tempfile
import threading
import time
from pathlib import Path

import wasmtime

from spelaion.python.fetch import compiled_name, ensure_python, site_name
from spelaion.vfs.mounts import MountFs

# Exit code for a call the epoch deadline stopped, as timeout(1) gives.
_TIMED_OUT = 124

_RESERVED = ("/lib", "/site")

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
            module,
            argv,
            preopens=preopens,
            env={},
            stdin="",
            tmp=Path(tmp),
            timeout_s=None,
            memory=None,
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
) -> tuple[str, str, int]:
    """Run ``python ARGS`` in *cwd* until *deadline* (``time.monotonic``).

    Returns stdout, stderr and the exit code. A call that leaves the
    writable mounts over the disk cap fails, with what it printed kept.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return "", "python: timed out\n", _TIMED_OUT
    folder = ensure_python()
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
    with tempfile.TemporaryDirectory() as tmp:
        code, out, err = _run(
            module,
            ["python", "-m", "_boot", cwd, "--", *args],
            preopens=preopens,
            env=guest_env,
            stdin=stdin,
            tmp=Path(tmp),
            timeout_s=remaining,
            memory=memory_mb * 2**20,
        )
    cap = fs.max_disk
    if cap is not None and (used := fs.disk_used()) > cap:
        err += f"python: disk cap exceeded ({used} of {cap} bytes)\n"
        code = 1
    return out, err, code


def _run(
    module: wasmtime.Module,
    argv: list[str],
    *,
    preopens: list[tuple[Path, str, bool]],
    env: dict[str, str],
    stdin: str,
    tmp: Path,
    timeout_s: float | None,
    memory: int | None,
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
    stdin_path.write_text(stdin, encoding="utf-8", errors="surrogateescape")
    wasi.stdin_file = str(stdin_path)
    wasi.stdout_file = str(out_path)
    wasi.stderr_file = str(err_path)
    store.set_wasi(wasi)
    linker = _wasi_linker()
    timer = None
    if timeout_s is not None:
        timer = threading.Timer(timeout_s, eng.increment_epoch)
        timer.daemon = True
        timer.start()
    note = ""
    try:
        start = linker.instantiate(store, module).exports(store)["_start"]
        assert isinstance(start, wasmtime.Func)
        start(store)
        code = 0
    except wasmtime.ExitTrap as e:
        code = e.code
    except wasmtime.Trap as e:
        if e.trap_code == wasmtime.TrapCode.INTERRUPT:
            note, code = "python: timed out\n", _TIMED_OUT
        else:
            note, code = f"python: {str(e).splitlines()[0]}\n", 1
    except wasmtime.WasmtimeError as e:
        note, code = f"python: {str(e).splitlines()[0]}\n", 1
    finally:
        if timer is not None:
            timer.cancel()
    out = out_path.read_text(encoding="utf-8", errors="replace")
    err = err_path.read_text(encoding="utf-8", errors="replace") + note
    return code, out, err
