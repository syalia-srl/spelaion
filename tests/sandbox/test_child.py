"""Sandbox: the child process, its hard deadline and its memory cap."""

from __future__ import annotations

import os
import signal
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import Limits, Mount, Result, Sandbox

# The emulated awk has no loops and shell loops stop at an iteration limit;
# a catastrophic regex is what runs forever.
RUNAWAY = "printf '%s!\\n' " + "a" * 46 + " | grep -E '(a+)+$'"


def psutil_like_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


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


def test_memory_blowup_spares_parent(sb_small_mem: Sandbox) -> None:
    # The emulated yes stops at 10,000 lines, so double a string instead.
    r = sb_small_mem.bash("x=a; while true; do x=$x$x; done")
    assert r.exit_code != 0 and not r.timed_out
    assert sb_small_mem.bash("echo ok").stdout == "ok\n"


def test_child_killed_from_outside(sb: Sandbox) -> None:
    os.kill(sb._child_pid, signal.SIGKILL)  # pyright: ignore[reportPrivateUsage]
    assert sb.bash("echo back").stdout == "back\n"


def test_child_dies_mid_call(sb: Sandbox) -> None:
    r = sb.bash("kill_self_for_test")
    assert r.exit_code == 125 and "child exited (9); restarted" in r.stderr
    assert sb.bash("echo ok").exit_code == 0


def test_close_reaps_child(sb: Sandbox) -> None:
    pid = sb._child_pid  # pyright: ignore[reportPrivateUsage]
    sb.close()
    assert not psutil_like_alive(pid)


# --- Beyond the brief -------------------------------------------------------


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
    s.close()
    s.close()
    with pytest.raises(RuntimeError):
        s.bash("true")


def test_errors_still_raise_at_construction(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Sandbox([Mount("/x", tmp_path / "missing")])
    with pytest.raises(ValueError):
        Sandbox([Mount("/x", tmp_path)], cwd="/nope")
