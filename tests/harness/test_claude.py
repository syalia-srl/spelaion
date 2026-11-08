"""Claude Code, run by examples/claude_code.py, sees the three tools only.

Runs only with SPELAION_HARNESS=1, ``claude`` on PATH and
SPELAION_CLAUDE_CONFIG_DIR naming a config folder logged in once with
``CLAUDE_CONFIG_DIR=<folder> claude /login``.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[2] / "examples"

pytestmark = [
    pytest.mark.harness,
    pytest.mark.skipif(
        os.environ.get("SPELAION_HARNESS") != "1" or shutil.which("claude") is None,
        reason="needs SPELAION_HARNESS=1 and claude on PATH",
    ),
]


def test_claude_code_sees_only_the_three_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = os.environ.get("SPELAION_CLAUDE_CONFIG_DIR")
    if not config_dir:
        pytest.fail("set SPELAION_CLAUDE_CONFIG_DIR to a logged-in config folder")
    monkeypatch.syspath_prepend(str(EXAMPLES))
    import claude_code

    try:
        run = claude_code.run("say ok", Path(config_dir).expanduser())
    finally:
        sys.modules.pop("claude_code", None)
        sys.modules.pop("serve", None)
    assert sorted(run.tools) == [
        "mcp__spelaion__bash",
        "mcp__spelaion__edit",
        "mcp__spelaion__write",
    ]
