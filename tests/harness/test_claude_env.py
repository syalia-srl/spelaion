"""examples/claude_code.py drops only what marks a nested Claude Code session."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_env_keeps_provider_and_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for name in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"):
        monkeypatch.setenv(name, "1")
    for name in (
        "CLAUDE_CODE_USE_BEDROCK",
        "CLAUDE_CODE_USE_VERTEX",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.setenv(name, "kept")
    monkeypatch.syspath_prepend(str(EXAMPLES))
    import claude_code

    try:
        env = claude_code._env(tmp_path)  # pyright: ignore[reportPrivateUsage]
    finally:
        sys.modules.pop("claude_code", None)
        sys.modules.pop("serve", None)
    assert not {"CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT"} & set(
        env
    )
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "kept"
    assert env["CLAUDE_CODE_USE_VERTEX"] == "kept"
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "kept"
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path)
