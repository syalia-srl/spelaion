"""Command substitution: its errors, its status and the call's limits."""

from __future__ import annotations

from pathlib import Path

import pytest

from spelaion import Limits, Mount, Sandbox
from spelaion._shell import Shell
from spelaion.commands._registry import COMMANDS


def _shell(tmp_path: Path) -> Shell:
    return Shell([Mount("/scratch", tmp_path)], "/scratch", {}, Limits())


def test_inner_stderr_reaches_the_caller(tmp_path: Path) -> None:
    r = _shell(tmp_path).call("bash", {"command": "x=$(cat /nope); echo rc=$?"})
    assert r.stdout == "rc=1\n"
    assert "/nope" in r.stderr


def test_internal_error_is_one_line_without_the_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object) -> None:
        raise RuntimeError(f"{tmp_path}/secret")

    monkeypatch.setitem(COMMANDS, "cat", boom)
    r = _shell(tmp_path).call("bash", {"command": "x=$(cat f); echo rc=$?"})
    assert r.stdout == "rc=1\n"
    assert r.stderr == "spelaion: internal error: RuntimeError\n"


def test_memory_blowup_in_substitution_is_reported(tmp_path: Path) -> None:
    with Sandbox(
        [Mount("/scratch", tmp_path)], cwd="/scratch", limits=Limits(memory_mb=256)
    ) as sb:
        r = sb.bash("x=$(seq 1 20000000); echo done")
        assert (r.stdout, r.stderr, r.exit_code) == (
            "",
            "spelaion: out of memory\n",
            1,
        )
        assert sb.bash("echo ok").stdout == "ok\n"
