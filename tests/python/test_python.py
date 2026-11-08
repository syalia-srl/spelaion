"""python and python3: CPython for WASI over the sandbox's mounts."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import Limits, Mount, Sandbox
from spelaion.cli.main import main
from spelaion.python import fetch, runner
from spelaion.python.runner import run_python
from spelaion.vfs.mounts import MountFs

pytestmark = pytest.mark.wasi


_LIMITS = Limits()


def _sandbox(tmp_path: Path, limits: Limits = _LIMITS) -> Sandbox:
    ro, rw = tmp_path / "ro", tmp_path / "rw"
    ro.mkdir()
    rw.mkdir()
    return Sandbox(
        [Mount("/project", ro, readonly=True), Mount("/scratch", rw)],
        cwd="/scratch",
        limits=limits,
        python=True,
    )


@pytest.fixture
def sb(tmp_path: Path) -> Iterator[Sandbox]:
    with _sandbox(tmp_path) as s:
        yield s


@pytest.fixture
def sb_2s(tmp_path: Path) -> Iterator[Sandbox]:
    with _sandbox(tmp_path, Limits(timeout_s=2)) as s:
        yield s


@pytest.fixture
def sb_cap_1mb(tmp_path: Path) -> Iterator[Sandbox]:
    with _sandbox(tmp_path, Limits(max_disk=1_000_000)) as s:
        yield s


def _timed(sb: Sandbox, command: str) -> float:
    t = time.perf_counter()
    r = sb.bash(command)
    assert r.exit_code == 0, r.stderr
    return time.perf_counter() - t


# --- From the brief ---------------------------------------------------------


def test_print(sb: Sandbox) -> None:
    assert sb.bash("python -c 'print(1)'").stdout == "1\n"


def test_yaml(sb: Sandbox) -> None:
    r = sb.bash("python3 -c 'import yaml; print(yaml.safe_dump({\"a\": 1}).strip())'")
    assert r.stdout == "a: 1\n"


def test_cwd_matches_shell(sb: Sandbox) -> None:
    r = sb.bash("cd /scratch && python -c 'import os; print(os.getcwd())'")
    assert r.stdout == "/scratch\n"


@pytest.fixture
def sb_root(tmp_path: Path) -> Iterator[Sandbox]:
    ro, rw = tmp_path / "ro", tmp_path / "rw"
    ro.mkdir()
    rw.mkdir()
    mounts = [Mount("/project", ro, readonly=True), Mount("/scratch", rw)]
    with Sandbox(mounts, cwd="/", python=True) as s:
        yield s


def test_cwd_root(sb_root: Sandbox) -> None:
    r = sb_root.bash("python -c 'print(1)'")
    assert (r.exit_code, r.stdout, r.stderr) == (0, "1\n", "")


def test_cwd_root_script_by_absolute_path(sb_root: Sandbox) -> None:
    sb_root.write("/scratch/s.py", "import sys; print(sys.argv)\n")
    r = sb_root.bash("python /scratch/s.py x")
    assert (r.exit_code, r.stdout) == (0, "['/scratch/s.py', 'x']\n")


def test_cwd_above_mounts(tmp_path: Path) -> None:
    with Sandbox([Mount("/a/b", tmp_path)], cwd="/a", python=True) as s:
        r = s.bash("python -c 'import os; print(os.getcwd())'")
    assert (r.exit_code, r.stdout, r.stderr) == (0, "/\n", "")


def test_pipes(sb: Sandbox) -> None:
    r = sb.bash(
        "echo 3 | python -c 'import sys; print(int(sys.stdin.read()) * 2)' | cat"
    )
    assert r.stdout == "6\n"


def test_script_file(sb: Sandbox) -> None:
    sb.write("/scratch/s.py", "import sys; print(sys.argv[1:])")
    assert sb.bash("python /scratch/s.py a b").stdout == "['a', 'b']\n"


def test_writes_scratch(sb: Sandbox) -> None:
    sb.bash('python -c \'open("/scratch/o", "w").write("x")\'')
    assert sb.bash("cat /scratch/o").stdout == "x"


def test_readonly(sb: Sandbox) -> None:
    r = sb.bash('python -c \'open("/project/z", "w")\'')
    assert "Operation not permitted" in r.stderr


def test_no_etc(sb: Sandbox) -> None:
    assert sb.bash("python -c 'open(\"/etc/passwd\")'").exit_code == 1


def test_no_socket(sb: Sandbox) -> None:
    r = sb.bash("python -c 'import socket; socket.socket().connect((\"1.1.1.1\", 80))'")
    assert "Not supported" in r.stderr


def test_infinite_loop(sb_2s: Sandbox) -> None:
    r = sb_2s.bash("python -c 'while True: pass'")
    assert r.timed_out
    # The parent's deadline (send + timeout_s) comes before the guest's epoch
    # deadline (arrival + timeout_s), so the parent stops and restarts the
    # child; the child's own itimer (timeout_s + GRACE) never gets to fire.
    assert r.stderr == "spelaion: timed out after 2s\n"


def test_disk_cap_after_python(sb_cap_1mb: Sandbox) -> None:
    r = sb_cap_1mb.bash(
        'python -c \'open("/scratch/big", "wb").write(b"x" * 2_000_000)\''
    )
    assert r.exit_code != 0 and "disk" in r.stderr
    assert sb_cap_1mb.write("/scratch/more", "x").exit_code == 1


def test_import_yaml_fast(sb: Sandbox) -> None:
    sb.bash("python -c 'import yaml'")
    t = min(_timed(sb, "python -c 'import yaml'") for _ in range(5))
    assert t < 0.3


# --- The python CLI, as _boot gives it -------------------------------------


def test_cwd_relative_script(sb: Sandbox) -> None:
    sb.write("/scratch/s.py", "import sys; print(sys.argv[0])")
    assert sb.bash("python s.py").stdout == "s.py\n"


def test_module(sb: Sandbox) -> None:
    r = sb.bash("echo '{\"a\":1}' | python -m json.tool --compact")
    assert r.stdout == '{"a":1}\n'


def test_stdin_script(sb: Sandbox) -> None:
    r = sb.bash("echo 'import sys; print(sys.argv)' | python - x")
    assert r.stdout == "['-', 'x']\n"


def test_c_argv(sb: Sandbox) -> None:
    r = sb.bash("python -c 'import sys; print(sys.argv)' a")
    assert r.stdout == "['-c', 'a']\n"


def test_exit_code(sb: Sandbox) -> None:
    assert sb.bash("python -c 'raise SystemExit(3)'").exit_code == 3


def test_missing_script(sb: Sandbox) -> None:
    r = sb.bash("python /scratch/nope.py")
    assert r.exit_code == 2 and "No such file or directory" in r.stderr


def test_exported_env(sb: Sandbox) -> None:
    r = sb.bash("export X=7; python -c 'import os; print(os.environ[\"X\"])'")
    assert r.stdout == "7\n"


def test_stdlib_seal(sb: Sandbox) -> None:
    r = sb.bash("python -c 'import subprocess; subprocess.run([\"ls\"])'")
    assert r.exit_code == 1
    assert r.stderr.endswith("OSError: [Errno 58] wasi does not support processes.\n")


def test_lib_and_site_readonly(sb: Sandbox) -> None:
    r = sb.bash('python -c \'open("/site/x", "w")\'')
    assert "Operation not permitted" in r.stderr


# --- Symlinks the guest makes inside a writable mount ----------------------


def test_symlink_inside_mount_is_followed(sb: Sandbox) -> None:
    sb.write("/scratch/t", "hi")
    r = sb.bash('python -c \'import os; os.symlink("t", "/scratch/l")\'')
    assert r.exit_code == 0, r.stderr
    assert sb.bash("cat /scratch/l").stdout == "hi"
    assert sb.bash("python -c 'print(open(\"/scratch/l\").read())'").stdout == "hi\n"


def test_symlink_outside_mount_is_unreadable(sb: Sandbox, tmp_path: Path) -> None:
    secret = tmp_path / "secret"
    secret.write_text("no")
    sb.bash(f'python -c \'import os; os.symlink("{secret}", "/scratch/out")\'')
    sb.bash('python -c \'import os; os.symlink("../ro", "/scratch/up")\'')
    for path in ("/scratch/out", "/scratch/up/x"):
        assert "no" not in sb.bash(f"cat {path}").stdout
        r = sb.bash(f"python -c 'print(open(\"{path}\").read())'")
        assert r.exit_code != 0
    link = tmp_path / "rw" / "out"
    assert not link.exists() or os.readlink(link) != str(secret)


# --- Memory -----------------------------------------------------------------


@pytest.mark.parametrize("memory_mb", [256, 1024])
def test_runs_under_memory_limit(tmp_path: Path, memory_mb: int) -> None:
    with _sandbox(tmp_path, Limits(memory_mb=memory_mb)) as s:
        r = s.bash("python -c 'import yaml; x = bytearray(50 * 2**20); print(len(x))'")
        assert r.stdout == f"{50 * 2**20}\n", r.stderr


def test_guest_allocation_over_limit(tmp_path: Path) -> None:
    with _sandbox(tmp_path, Limits(memory_mb=256)) as s:
        r = s.bash("python -c 'x = bytearray(1024**3)'")
        assert r.exit_code != 0 and "MemoryError" in r.stderr
        assert s.bash("python -c 'print(2)'").stdout == "2\n"


# --- Without python ---------------------------------------------------------


def test_not_available(tmp_path: Path) -> None:
    with Sandbox([Mount("/scratch", tmp_path)], cwd="/scratch") as s:
        for name in ("python", "python3"):
            r = s.bash(f"{name} -c 'print(1)'")
            assert r.exit_code == 127
            assert r.stderr == f"{name}: not available in this sandbox\n"


def test_mount_over_lib_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="/lib and /site"):
        Sandbox([Mount("/lib", tmp_path)], python=True)


# --- _boot ------------------------------------------------------------------


def test_traceback_shows_only_the_agents_code(sb: Sandbox) -> None:
    r = sb.bash("python -c '1/0'")
    assert r.exit_code == 1
    assert r.stderr.startswith("Traceback (most recent call last):\n")
    assert 'File "<string>", line 1' in r.stderr and "_boot" not in r.stderr
    assert r.stderr.endswith("ZeroDivisionError: division by zero\n")


def test_unknown_option(sb: Sandbox) -> None:
    r = sb.bash("python -X")
    assert r.exit_code == 2 and "Unknown option: -X" in r.stderr


# --- The runner -------------------------------------------------------------


def _run(tmp_path: Path, code: str, deadline: float) -> tuple[str, str, int]:
    return run_python(
        ["-c", code],
        stdin="",
        cwd="/scratch",
        env={},
        fs=MountFs([Mount("/scratch", tmp_path)]),
        folder=fetch.ensure_python(),
        deadline=deadline,
        memory_mb=256,
        max_output=30_000,
    )


def test_epoch_deadline_stops_the_guest(tmp_path: Path) -> None:
    t = time.monotonic()
    _, err, code = _run(tmp_path, "while True: pass", t + 1)
    assert code == 124 and err == "python: timed out\n"
    assert time.monotonic() - t < 3


def test_deadline_already_past(tmp_path: Path) -> None:
    assert _run(tmp_path, "print(1)", time.monotonic() - 1)[2] == 124


def test_module_is_loaded_once(tmp_path: Path) -> None:
    _run(tmp_path, "pass", time.monotonic() + 30)
    module = runner.load_module(fetch.ensure_python())
    _run(tmp_path, "pass", time.monotonic() + 30)
    assert runner.load_module(fetch.ensure_python()) is module


# --- Fetching ---------------------------------------------------------------


def test_cache_dir_order(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SPELAION_CACHE", str(tmp_path / "a"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "x"))
    assert fetch.cache_dir() == tmp_path / "a"
    monkeypatch.delenv("SPELAION_CACHE")
    assert fetch.cache_dir() == tmp_path / "x" / "spelaion"
    monkeypatch.delenv("XDG_CACHE_HOME")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert fetch.cache_dir() == tmp_path / ".cache" / "spelaion"


def test_bad_download_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "python.zip"
    fake.write_bytes(b"not the build")
    cache = tmp_path / "cache"
    monkeypatch.setenv("SPELAION_CACHE", str(cache))
    monkeypatch.setitem(fetch.PYTHON_WASI, "url", fake.as_uri())
    with pytest.raises(RuntimeError, match="sha256"):
        fetch.ensure_python()
    assert list(cache.iterdir()) == []


def test_cli_fetch_python(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["fetch-python"]) == 0
    assert capsys.readouterr().out == f"{fetch.ensure_python()}\n"


def test_missing_module(sb: Sandbox) -> None:
    r = sb.bash("python -m nosuchmod")
    assert r.exit_code == 1 and r.stderr == "python: No module named nosuchmod\n"


# --- Output and disk while the guest runs -----------------------------------

# Every write test stays bounded, so a regression cannot fill the disk.
_SMALL = Limits(timeout_s=10, max_output=10_000, max_disk=1_000_000)


@pytest.fixture
def sb_small(tmp_path: Path) -> Iterator[Sandbox]:
    with _sandbox(tmp_path, _SMALL) as s:
        yield s


def test_output_limit_stops_the_guest(sb_small: Sandbox) -> None:
    t = time.monotonic()
    r = sb_small.bash(
        "python -c 'import sys\nfor _ in range(200): sys.stdout.write(\"x\" * 2**20)'"
    )
    assert time.monotonic() - t < 3
    assert r.exit_code == 1
    assert r.stderr.endswith("python: output limit reached\n")
    assert len(r.stdout) < 2 * _SMALL.max_output


def test_one_file_past_the_disk_cap(sb_small: Sandbox, tmp_path: Path) -> None:
    t = time.monotonic()
    r = sb_small.bash(
        'python -c \'f = open("/scratch/big", "wb")\n'
        'for _ in range(80): f.write(b"x" * 2**16)\''
    )
    assert time.monotonic() - t < 3
    assert r.exit_code == 1 and "python: disk cap exceeded" in r.stderr
    assert (tmp_path / "rw" / "big").stat().st_size <= _SMALL.max_disk


def test_many_files_past_the_disk_cap(sb_small: Sandbox, tmp_path: Path) -> None:
    t = time.monotonic()
    r = sb_small.bash(
        "python -c 'import time\n"
        "for i in range(2000):\n"
        '    open(f"/scratch/f{i}", "wb").write(b"x" * 10_000)\n'
        "    time.sleep(0.001)\n"
        'open("/scratch/done", "w")\''
    )
    assert time.monotonic() - t < 3
    assert r.exit_code == 1 and "python: disk cap exceeded" in r.stderr
    assert not (tmp_path / "rw" / "done").exists()


# --- The cache ---------------------------------------------------------------


def _link_or_copy(src: str, dst: str) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


@pytest.fixture
def linked_cache() -> Iterator[Path]:
    """A copy of the prepared cache, of hard links where it can be."""
    real = fetch.cache_dir()
    work = Path(tempfile.mkdtemp(prefix="test-cache.", dir=real.parent))
    try:
        cache = work / "cache"
        shutil.copytree(real, cache, copy_function=_link_or_copy)
        yield cache
    finally:
        shutil.rmtree(work)


@pytest.mark.parametrize("where", ["outer", "outer/cache/sub"])
def test_writable_mount_over_the_cache_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, where: str
) -> None:
    monkeypatch.setenv("SPELAION_CACHE", str(tmp_path / "outer" / "cache"))
    host = tmp_path / where
    host.mkdir(parents=True)
    with pytest.raises(ValueError, match="python cache"):
        Sandbox([Mount("/w", host)], python=True)


def test_readonly_mount_of_the_cache_allowed() -> None:
    mounts = [Mount("/c", fetch.cache_dir(), readonly=True)]
    with Sandbox(mounts, cwd="/c", python=True) as s:
        assert s.bash("python -c 'print(1)'").stdout == "1\n"


def test_child_never_builds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, linked_cache: Path
) -> None:
    cache = linked_cache
    monkeypatch.setenv("SPELAION_CACHE", str(cache))
    (tmp_path / "w").mkdir()
    with Sandbox([Mount("/w", tmp_path / "w")], cwd="/w", python=True) as s:
        assert s.bash("python -c 'print(1)'").stdout == "1\n"
        shutil.rmtree(cache / f"python-{fetch.PYTHON_WASI['version']}")
        r = s.bash("python -c 'print(1)'")
    assert r.exit_code == 127
    assert r.stderr == (
        "python: CPython for WASI is missing from the cache; "
        "run spelaion fetch-python\n"
    )
    assert list(cache.iterdir()) == []


def test_restarted_child_keeps_the_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, linked_cache: Path
) -> None:
    # A relative SPELAION_CACHE, then another cwd and environment: the
    # restarted child still uses the folder found at construction.
    monkeypatch.chdir(linked_cache.parent)
    monkeypatch.setenv("SPELAION_CACHE", linked_cache.name)
    (tmp_path / "w").mkdir()
    with Sandbox([Mount("/w", tmp_path / "w")], cwd="/w", python=True) as s:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SPELAION_CACHE", str(tmp_path / "elsewhere"))
        s._restart()  # pyright: ignore[reportPrivateUsage]
        assert s.bash("python -c 'print(1)'").stdout == "1\n"
    assert not (tmp_path / "elsewhere").exists()


def test_stale_work_folders_removed(
    monkeypatch: pytest.MonkeyPatch, linked_cache: Path
) -> None:
    cache = linked_cache
    monkeypatch.setenv("SPELAION_CACHE", str(cache))
    folder = cache / f"python-{fetch.PYTHON_WASI['version']}"
    old = [
        cache / f"{folder.name}.abc",
        folder / f"{fetch.site_name()}.abc",
        cache / "python-3.14.9-wasi_sdk-24.zip.abc",
    ]
    fresh = cache / f"{folder.name}.new"
    for p in [*old[:2], fresh]:
        p.mkdir()
    old[2].write_bytes(b"part")
    hour_ago = time.time() - 3600
    for p in old:
        os.utime(p, (hour_ago, hour_ago))
    assert fetch.ensure_python() == folder
    assert [p.exists() for p in old] == [False, False, False]
    assert fresh.is_dir() and (folder / fetch.site_name()).is_dir()


def test_download_deadline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "python.zip"
    fake.write_bytes(b"x" * 2**21)
    cache = tmp_path / "cache"
    monkeypatch.setenv("SPELAION_CACHE", str(cache))
    monkeypatch.setitem(fetch.PYTHON_WASI, "url", fake.as_uri())
    monkeypatch.setattr(fetch, "_DOWNLOAD_S", 0)
    with pytest.raises(TimeoutError, match="download"):
        fetch.ensure_python()
    assert list(cache.iterdir()) == []
