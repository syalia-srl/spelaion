"""Run Claude Code with spelaion's three tools and nothing else.

    CLAUDE_CONFIG_DIR=~/.claude-spelaion claude /login   # once
    SPELAION_CLAUDE_CONFIG_DIR=~/.claude-spelaion \\
        uv run python examples/claude_code.py "list /scratch"

It serves the sandbox of ``serve.py`` in this process, writes an MCP config
naming it ``spelaion``, and runs ``claude -p`` with no built-in tools, no
other MCP server, its own config folder and an empty working folder. It
prints the tools Claude Code reports at start and the model's answer.

The config folder is yours to choose and log into; this script never creates
it and never copies a login into it. Claude Code gets this process's
environment without ``CLAUDECODE`` and the ``CLAUDE_CODE_*`` variables, so a
run from inside another Claude Code session behaves as one from a shell.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from serve import serving

CONFIG_DIR_VAR = "SPELAION_CLAUDE_CONFIG_DIR"


@dataclass
class Run:
    tools: list[str]  # the system/init event's tool list
    answer: str  # the result event's text


def run(prompt: str, config_dir: Path, claude: str = "claude") -> Run:
    """Ask Claude Code *prompt* with only the sandbox's tools."""
    if not config_dir.is_dir():
        raise FileNotFoundError(
            f"{config_dir} is not a folder; log in once with "
            f"CLAUDE_CONFIG_DIR={config_dir} claude /login"
        )
    with serving() as (url, token), tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "mcp.json"
        config.touch(mode=0o600)
        servers = {
            "spelaion": {
                "type": "http",
                "url": url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
        config.write_text(json.dumps({"mcpServers": servers}))
        # Nothing here for Claude Code to discover: no CLAUDE.md, no skills.
        work = Path(tmp) / "work"
        work.mkdir()
        out = subprocess.run(
            [
                claude,
                "-p",
                prompt,
                "--output-format",
                "stream-json",
                "--verbose",
                "--allowedTools",
                "mcp__spelaion",
                "--tools",
                "",
                "--strict-mcp-config",
                "--mcp-config",
                str(config),
            ],
            cwd=work,
            env=_env(config_dir),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    failed = RuntimeError(
        f"claude exited {out.returncode}\n{out.stderr}\n{out.stdout[-2000:]}"
    )
    if out.returncode != 0:
        raise failed
    events = list(_events(out.stdout))
    init = _event(events, "system", "init")
    result = _event(events, "result")
    if init is None or result is None:
        raise failed
    return Run(tools=list(init["tools"]), answer=str(result.get("result", "")))


def _env(config_dir: Path) -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
    }
    return {**env, "CLAUDE_CONFIG_DIR": str(config_dir)}


def _events(stdout: str) -> Iterator[dict[str, Any]]:
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _event(
    events: list[dict[str, Any]], kind: str, subtype: str | None = None
) -> dict[str, Any] | None:
    for e in events:
        if e.get("type") == kind and subtype in (None, e.get("subtype")):
            return e
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Claude Code with only spelaion's three tools."
    )
    parser.add_argument("prompt")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=os.environ.get(CONFIG_DIR_VAR),
        help=f"Claude Code's config folder, logged in (default: ${CONFIG_DIR_VAR})",
    )
    args = parser.parse_args()
    if args.config_dir is None:
        parser.error(f"give --config-dir or set {CONFIG_DIR_VAR}")
    try:
        result = run(args.prompt, Path(args.config_dir).expanduser())
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(str(e))
    except subprocess.TimeoutExpired as e:
        sys.exit(f"claude did not finish in {e.timeout:g} s")
    print("tools:", ", ".join(result.tools))
    print(result.answer)


if __name__ == "__main__":
    main()
