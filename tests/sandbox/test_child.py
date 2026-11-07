"""Sandbox: the child process, its hard deadline and its memory cap."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import Limits, Mount, Result, Sandbox
from spelaion._child import GRACE, TEST_GRACE

# The emulated awk has no loops and shell loops stop at an iteration limit;
# a catastrophic regex is what runs forever.
RUNAWAY = "printf '%s!\\n' " + "a" * 46 + " | grep -E '(a+)+$'"


def psutil_like_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _gone(pid: int, within: float = 5) -> bool:
    """*pid* exits, or is a zombie, within *within* seconds."""
    end = time.monotonic() + within
    while time.monotonic() < end:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except FileNotFoundError:
            return not psutil_like_alive(pid)
        if state == "Z":
            return True
        time.sleep(0.05)
    return False


def _host_script(tmp_path: Path, body: str) -> Path:
    """A host script with no ``__main__`` guard, run by the test's Python."""
    (tmp_path / "rw").mkdir(exist_ok=True)
    script = tmp_path / "host.py"
    script.write_text(textwrap.dedent(body))
    return script


def _make(tmp_path: Path, limits: Limits | None = None) -> Sandbox:
    rw = tmp_path / "rw"
    rw.mkdir(exist_ok=True)
    return Sandbox([Mount("/scratch", rw)], cwd="/scratch", limits=limits or Limits())


@pytest.fixture(autouse=True)
def _test_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPELAION_TEST_HOOKS", "1")


@pytest.fixture
def sb(tmp_path: Path) -> Iterator[Sandbox]:
    with _make(tmp_path) as s:
        yield s


@pytest.fixture
def sb_1s(tmp_path: Path) -> Iterator[Sandbox]:
    with _make(tmp_path, Limits(timeout_s=1)) as s:
        yield s


@pytest.fixture
def sb_small_mem(tmp_path: Path) -> Iterator[Sandbox]:
    with _make(tmp_path, Limits(memory_mb=256)) as s:
        yield s


# --- From the brief ---------------------------------------------------------


def test_runaway_is_killed(sb_1s: Sandbox) -> None:
    t = time.monotonic()
    r = sb_1s.bash(RUNAWAY)
    assert r.timed_out and r.exit_code == 124 and time.monotonic() - t < 3
    assert "timed out after 1s" in r.stderr


def test_sandbox_works_after_kill(sb_1s: Sandbox) -> None:
    sb_1s.write("/scratch/keep", "k")
    assert sb_1s.bash(RUNAWAY).timed_out
    assert sb_1s.bash("cat /scratch/keep").stdout == "k"


def test_memory_blowup_spares_parent(
    sb_small_mem: Sandbox, capfd: pytest.CaptureFixture[str]
) -> None:
    # The emulated yes stops at 10,000 lines, so double a string instead:
    # 2**29 characters, 512 MB, bounded even if the cap were missing.
    r = sb_small_mem.bash("x=a; for i in $(seq 29); do x=$x$x; done; echo ${#x}")
    assert r.exit_code == 1 and not r.timed_out
    assert r.stderr == "spelaion: out of memory\n" and r.stdout == ""
    assert sb_small_mem.bash("echo ok").stdout == "ok\n"
    assert "Traceback" not in capfd.readouterr().err


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_memory_cap_is_set(sb_small_mem: Sandbox) -> None:
    assert sb_small_mem.bash("true").exit_code == 0
    pid = sb_small_mem._child_pid  # pyright: ignore[reportPrivateUsage]
    limits = Path(f"/proc/{pid}/limits").read_text().splitlines()
    data = next(line for line in limits if line.startswith("Max data size"))
    soft, hard = data.split()[3:5]
    assert int(soft) == int(hard) == 256 * 2**20


def test_child_killed_from_outside(sb: Sandbox) -> None:
    os.kill(sb._child_pid, signal.SIGKILL)  # pyright: ignore[reportPrivateUsage]
    assert sb.bash("echo back").stdout == "back\n"


def test_child_dies_mid_call(sb: Sandbox) -> None:
    r = sb.bash("kill_self_for_test")
    assert r.exit_code == 125 and "child exited (9); restarted" in r.stderr
    assert sb.bash("echo ok").exit_code == 0


def test_died_kills_a_child_that_does_not_exit(
    sb: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("spelaion.sandbox._REAP_TIMEOUT_S", 0.1)
    real = sb._process
    stuck = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    sb._process = stuck
    try:
        r = sb._died()
        assert r.exit_code == 125 and "child exited (-9)" in r.stderr
        assert stuck.returncode == -signal.SIGKILL
        assert sb.bash("echo ok").stdout == "ok\n"
    finally:
        stuck.kill()
        stuck.wait()
        real.kill()
        real.wait()


def test_close_reaps_child(sb: Sandbox) -> None:
    pid = sb._child_pid  # pyright: ignore[reportPrivateUsage]
    sb.close()
    assert not psutil_like_alive(pid)


# --- Beyond the brief -------------------------------------------------------


def test_call_after_kill_gets_its_whole_deadline(tmp_path: Path) -> None:
    # The restarted child's start-up (~0.2 s) is not charged to the call:
    # 0.2 s fails without the ready message.
    with _make(tmp_path, Limits(timeout_s=0.2)) as s:
        assert s.bash("echo first").stdout == "first\n"
        assert s.bash(RUNAWAY).timed_out
        r = s.bash("echo ok")
        assert r.stdout == "ok\n" and not r.timed_out


def test_unguarded_host_script(tmp_path: Path) -> None:
    script = _host_script(
        tmp_path,
        f"""
        from spelaion import Mount, Sandbox
        with open({str(tmp_path / "runs")!r}, "a") as f:
            f.write("run\\n")
        sb = Sandbox([Mount("/scratch", {str(tmp_path / "rw")!r})])
        print(sb.bash("echo ok").stdout, end="")
        sb.close()
        """,
    )
    p = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert p.returncode == 0, p.stderr
    assert p.stdout == "ok\n"
    assert (tmp_path / "runs").read_text() == "run\n"


def test_child_exits_when_parent_dies(tmp_path: Path) -> None:
    script = _host_script(
        tmp_path,
        f"""
        import time
        from spelaion import Mount, Sandbox
        sb = Sandbox([Mount("/scratch", {str(tmp_path / "rw")!r})])
        sb.bash("true")
        print(sb._child_pid, flush=True)
        time.sleep(120)
        """,
    )
    parent = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert parent.stdout is not None
        child = int(parent.stdout.readline())
        assert psutil_like_alive(child)
    finally:
        parent.kill()
        parent.wait()
    assert _gone(child)


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM])
def test_child_stops_when_parent_dies_mid_call(tmp_path: Path, sig: int) -> None:
    script = _host_script(
        tmp_path,
        f"""
        import os, threading, time
        from spelaion import Limits, Mount, Sandbox
        sb = Sandbox(
            [Mount("/scratch", {str(tmp_path / "rw")!r})], limits=Limits(timeout_s=1)
        )
        threading.Thread(target=sb.bash, args=({RUNAWAY!r},), daemon=True).start()
        while not sb._ready:
            time.sleep(0.01)
        time.sleep(0.2)
        print(sb._child_pid, flush=True)
        os.kill(os.getpid(), {int(sig)})
        """,
    )
    parent = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, text=True
    )
    assert parent.stdout is not None
    child = int(parent.stdout.readline())
    try:
        assert parent.wait(timeout=10) == -sig
        assert _gone(child, within=1 + GRACE + 2)
    finally:
        if psutil_like_alive(child):
            os.kill(child, signal.SIGKILL)
        parent.kill()
        parent.wait()


def test_creation_time(tmp_path: Path) -> None:
    t = time.monotonic()
    s = _make(tmp_path)
    created = time.monotonic() - t
    s.bash("true")
    first = time.monotonic() - t
    s.close()
    ms = f"{created * 1e3:.0f} ms, first call {first * 1e3:.0f} ms"
    print(f"\nSandbox created in {ms}")


def test_test_hook_absent_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SPELAION_TEST_HOOKS")
    with _make(tmp_path) as s:
        r = s.bash("kill_self_for_test")
        assert r.exit_code == 127 and "command not found" in r.stderr


def test_host_request_is_served(sb: Sandbox) -> None:
    seen: list[tuple[str, list[str], str, str, dict[str, str]]] = []

    def serve(
        name: str, args: list[str], stdin: str, cwd: str, env: dict[str, str]
    ) -> Result:
        seen.append((name, args, stdin, cwd, env))
        return Result(stdout=f"hello {' '.join(args)}\n", exit_code=3)

    sb._serve_host = serve  # pyright: ignore[reportPrivateUsage]
    sb._host_names = {"greet"}  # pyright: ignore[reportPrivateUsage]
    sb._restart()  # pyright: ignore[reportPrivateUsage]
    r = sb.bash("echo in | greet a b; echo rc=$?")
    assert r.stdout == "hello a b\nrc=3\n"
    assert seen == [("greet", ["a", "b"], "in\n", "/scratch", {})]


def test_host_error_comes_back_as_result(sb: Sandbox) -> None:
    sb._host_names = {"greet"}  # pyright: ignore[reportPrivateUsage]
    sb._restart()  # pyright: ignore[reportPrivateUsage]
    r = sb.bash("greet")
    assert r.exit_code == 1 and "greet: internal error" in r.stderr
    assert sb.bash("echo ok").stdout == "ok\n"


def test_calls_after_close_raise(tmp_path: Path) -> None:
    s = _make(tmp_path)
    pid = s._child_pid  # pyright: ignore[reportPrivateUsage]
    s.close()
    s.close()
    with pytest.raises(RuntimeError, match="sandbox is closed"):
        s.bash("true")
    assert not psutil_like_alive(pid)


def test_no_restart_while_closing(tmp_path: Path) -> None:
    s = _make(tmp_path)
    s._finalizer()  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError, match="sandbox is closed"):
        s._restart()  # pyright: ignore[reportPrivateUsage]


def test_errors_still_raise_at_construction(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Sandbox([Mount("/x", tmp_path / "missing")])
    with pytest.raises(ValueError):
        Sandbox([Mount("/x", tmp_path)], cwd="/nope")


def test_slow_host_command_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The child's own timer ends it while the parent still serves the host
    # command; the parent's reply then hits a closed socket. That is still
    # this call's deadline, not a crash.
    grace = 0.2
    monkeypatch.setenv(TEST_GRACE, str(grace))
    with _make(tmp_path, Limits(timeout_s=0.5)) as s:

        def slow(
            name: str, args: list[str], stdin: str, cwd: str, env: dict[str, str]
        ) -> Result:
            time.sleep(0.5 + grace + 1)
            return Result(stdout="late\n")

        s._serve_host = slow  # pyright: ignore[reportPrivateUsage]
        s._host_names = {"slow"}  # pyright: ignore[reportPrivateUsage]
        s._restart()  # pyright: ignore[reportPrivateUsage]
        pid = s._child_pid  # pyright: ignore[reportPrivateUsage]
        r = s.bash("slow")
        assert (r.exit_code, r.timed_out) == (124, True)
        assert r.stderr == "spelaion: timed out after 0.5s\n"
        assert not psutil_like_alive(pid)
        assert s.bash("echo ok").stdout == "ok\n"
