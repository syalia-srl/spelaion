"""The agent battery: each case through a ``Sandbox``, against real bash."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from spelaion import Mount, Sandbox
from tests.battery.cases import CASES, Case

HERE = Path(__file__).parent
EXPECTED = json.loads((HERE / "expected.json").read_text())


def _param(case: Case) -> object:
    marks: list[pytest.MarkDecorator] = []
    if case.python:
        marks.append(pytest.mark.wasi)
    if case.gap:
        marks.append(pytest.mark.xfail(reason=case.gap, strict=True))
    return pytest.param(case, id=case.name, marks=marks)


def _sandbox(root: Path, python: bool) -> Sandbox:
    shutil.copytree(HERE / "fixtures" / "project", root / "project")
    (root / "scratch").mkdir()
    return Sandbox(
        [
            Mount("/project", root / "project", readonly=True),
            Mount("/scratch", root / "scratch"),
        ],
        cwd="/scratch",
        python=python,
    )


def test_every_case_is_recorded() -> None:
    assert sorted(EXPECTED) == sorted(c.name for c in CASES)


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
def test_case(case: Case, tmp_path: Path) -> None:
    with _sandbox(tmp_path, case.python) as sb:
        r = sb.bash(case.command)
    want = EXPECTED[case.name]
    assert (r.stdout, r.exit_code) == (want["stdout"], want["exit_code"]), r.stderr
