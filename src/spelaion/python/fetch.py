"""Download and prepare CPython for WASI, once per cache.

The prepared folder holds ``python.wasm``, the standard library in ``lib/``
compiled to bytecode, ``site-HASH/`` with PyYAML and ``_boot``, and the module
compiled for this machine and wasmtime version, which a later process loads
with :func:`wasmtime.Module.deserialize`.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import os
import shutil
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

PYTHON_WASI = {
    "version": "3.14.9",
    "url": (
        "https://github.com/brettcannon/cpython-wasi-build/releases/download/"
        "v3.14.9/python-3.14.9-wasi_sdk-24.zip"
    ),
    "sha256": "8de7834105edef8db8a13299e2587cf8945021dd8764f2691d83bbc25129dfa2",
}

_HERE = Path(__file__).parent

# The whole download, past which a slow link counts as a failure.
_DOWNLOAD_S = 600

# A work folder this old was left by a process that was killed mid-build.
_STALE_S = 600


def cache_dir() -> Path:
    """``$SPELAION_CACHE``, else ``$XDG_CACHE_HOME/spelaion``, else ``~/.cache``."""
    if env := os.environ.get("SPELAION_CACHE"):
        return Path(env)
    if xdg := os.environ.get("XDG_CACHE_HOME"):
        return Path(xdg) / "spelaion"
    return Path.home() / ".cache" / "spelaion"


@functools.cache
def compiled_name() -> str:
    """The compiled module's file name, which names the wasmtime version."""
    from importlib.metadata import version

    return f"python.wasm.cwasm-{version('wasmtime')}"


def ensure_python() -> Path:
    """Return the prepared folder; download and prepare it only if missing.

    Each part is written under a temporary name and renamed into place, so
    two processes racing on first use never see half of one.
    """
    cache = cache_dir()
    folder = cache / f"python-{PYTHON_WASI['version']}"
    _remove_stale(cache, folder)
    if not folder.is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        archive = _download(cache)
        _build(folder, lambda work: _unpack(archive, work))
        archive.unlink(missing_ok=True)
    if not (folder / compiled_name()).is_file():
        from spelaion.python.runner import compile_module

        compile_module(folder)
    if not (folder / site_name()).is_dir():
        _build(folder / site_name(), lambda work: _fill_site(folder, work))
    return folder


@functools.cache
def site_name() -> str:
    """The ``site`` folder's name, which names a hash of what it holds.

    A spelaion with another ``_boot`` or PyYAML gets its own folder, never
    the files an older one left in the cache.
    """
    h = hashlib.sha256()
    for path in _site_sources():
        h.update(path.relative_to(_HERE).as_posix().encode() + b"\0")
        h.update(path.read_bytes())
    return f"site-{h.hexdigest()[:12]}"


def _site_sources() -> list[Path]:
    vendor = _HERE / "vendor"
    files = [p for p in vendor.rglob("*") if p.is_file() and p.suffix != ".pyc"]
    return sorted([*files, _HERE / "_boot.py"])


def _build(target: Path, fill: Callable[[Path], None]) -> None:
    """Fill a temporary folder beside *target*, then rename it into place."""
    work = Path(tempfile.mkdtemp(prefix=f"{target.name}.", dir=target.parent))
    try:
        fill(work)
        work.chmod(0o755)
        try:
            work.rename(target)
        except OSError:
            # Another process prepared it first.
            if not target.is_dir():
                raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _download(cache: Path) -> Path:
    archive = cache / PYTHON_WASI["url"].rsplit("/", 1)[1]
    if archive.is_file() and _sha256(archive) == PYTHON_WASI["sha256"]:
        return archive
    fd, tmp = tempfile.mkstemp(prefix=f"{archive.name}.", dir=cache)
    try:
        deadline = time.monotonic() + _DOWNLOAD_S
        with (
            os.fdopen(fd, "wb") as out,
            urllib.request.urlopen(PYTHON_WASI["url"], timeout=60) as response,
        ):
            while block := response.read(2**16):
                out.write(block)
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"the CPython for WASI download took over {_DOWNLOAD_S}s"
                    )
        digest = _sha256(Path(tmp))
        if digest != PYTHON_WASI["sha256"]:
            raise RuntimeError(
                f"CPython for WASI download has sha256 {digest}, "
                f"expected {PYTHON_WASI['sha256']}"
            )
        os.replace(tmp, archive)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
    return archive


def _remove_stale(cache: Path, folder: Path) -> None:
    """Remove work folders and partial files a killed process left behind."""
    if not cache.is_dir():
        return
    left = [
        *cache.glob(f"{folder.name}.*"),
        *cache.glob("*.zip.*"),
        *folder.glob("site-*.*"),
        *folder.glob(f"{compiled_name()}.*"),
    ]
    old = time.time() - _STALE_S
    for path in left:
        with contextlib.suppress(FileNotFoundError):
            if path.lstat().st_mtime > old:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink()


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def _unpack(archive: Path, work: Path) -> None:
    """Unpack *archive* into *work* and compile the standard library."""
    with zipfile.ZipFile(archive) as z:
        z.extractall(work)
    from spelaion.python.runner import compile_module, run_raw

    module = compile_module(work)
    code, err = run_raw(
        module, ["python", "-m", "compileall", "-q", "/lib"], {"/lib": work / "lib"}
    )
    if code != 0:
        raise RuntimeError(f"compiling the standard library failed: {err}")


def _fill_site(folder: Path, work: Path) -> None:
    """Copy PyYAML and ``_boot`` into *work* and compile them."""
    skip = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(_HERE / "vendor" / "yaml", work / "yaml", ignore=skip)
    shutil.copy(_HERE / "vendor" / "LICENSE", work / "yaml" / "LICENSE")
    shutil.copy(_HERE / "_boot.py", work / "_boot.py")
    from spelaion.python.runner import load_module, run_raw

    code, err = run_raw(
        load_module(folder),
        ["python", "-m", "compileall", "-q", "/site"],
        {"/site": work},
        readonly={"/lib": folder / "lib"},
    )
    if code != 0:
        raise RuntimeError(f"compiling the python site folder failed: {err}")
