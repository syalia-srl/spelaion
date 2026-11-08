"""A loop past the iteration cap stops the whole script."""

from __future__ import annotations

from pathlib import Path

import pytest

from spelaion import Limits, Mount
from spelaion._shell import Shell


@pytest.mark.parametrize(
    ("loop", "kind"),
    [
        ("while :; do :; done", "loop"),
        ("until false; do :; done", "loop"),
        ("for ((;;)); do :; done", "C-style for loop"),
        ("x=$(while :; do :; done)", "loop"),
    ],
)
def test_loop_cap_stops_the_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, loop: str, kind: str
) -> None:
    monkeypatch.setattr("spelaion._shell._MAX_LOOP_ITERATIONS", 5)
    shell = Shell([Mount("/scratch", tmp_path)], "/scratch", {}, Limits())
    r = shell.call("bash", {"command": f"echo before; {loop}; echo after"})
    assert (r.stdout, r.exit_code) == ("before\n", 1)
    assert r.stderr == f"spelaion: {kind} iteration limit reached\n"
