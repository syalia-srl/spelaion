"""Differential tests for redirections and control flow.

Compares agentsh output against real Bash.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from agentsh.api.engine import ShellEngine

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not found")


def _run_bash(script: str) -> tuple[str, int]:
    result = subprocess.run(
        [BASH, "-c", script],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout, result.returncode


def _run_agentsh(script: str) -> tuple[str, int]:
    engine = ShellEngine()
    result = engine.run(script)
    return result.stdout, result.result.exit_code


def _assert_match(script: str) -> None:
    agentsh_stdout, agentsh_exit = _run_agentsh(script)
    bash_stdout, bash_exit = _run_bash(script)
    assert agentsh_stdout == bash_stdout and agentsh_exit == bash_exit, (
        f"Mismatch for: {script!r}\n"
        f"  agentsh: {agentsh_stdout!r} (exit {agentsh_exit})\n"
        f"  bash:    {bash_stdout!r} (exit {bash_exit})"
    )


# ==================================================================
# Redirections
# ==================================================================

REDIRECT_FIXTURES = [
    "echo hello > /tmp/out; cat /tmp/out",
    "echo first > /tmp/out; echo second >> /tmp/out; cat /tmp/out",
    "echo stderr 2>/dev/null",
    "echo both > /tmp/out 2>&1; cat /tmp/out",
    "echo line1 > /tmp/f; echo line2 >> /tmp/f; cat /tmp/f",
]


@pytest.mark.parametrize("script", REDIRECT_FIXTURES)
def test_redirection_compat(script: str) -> None:
    _assert_match(script)


# ==================================================================
# While loops
# ==================================================================

WHILE_FIXTURES = [
    "i=0; while [ $i -lt 3 ]; do echo $i; i=$(( i + 1 )); done",
    "i=5; while [ $i -gt 0 ]; do echo $i; i=$(( i - 1 )); done",
]


@pytest.mark.parametrize("script", WHILE_FIXTURES)
def test_while_loop_compat(script: str) -> None:
    _assert_match(script)


# ==================================================================
# Until loops
# ==================================================================

UNTIL_FIXTURES = [
    "i=0; until [ $i -ge 3 ]; do echo $i; i=$(( i + 1 )); done",
    "i=0; until [ $i -eq 2 ]; do echo $i; i=$(( i + 1 )); done",
]


@pytest.mark.parametrize("script", UNTIL_FIXTURES)
def test_until_loop_compat(script: str) -> None:
    _assert_match(script)


# ==================================================================
# For loops
# ==================================================================

FOR_FIXTURES = [
    "for x in a b c; do echo $x; done",
    "for x in 1 2 3; do echo $(( x * 2 )); done",
    'for f in one two three; do echo "item: $f"; done',
]


@pytest.mark.parametrize("script", FOR_FIXTURES)
def test_for_loop_compat(script: str) -> None:
    _assert_match(script)


# ==================================================================
# Case statements
# ==================================================================

CASE_FIXTURES = [
    "x=hello; case $x in hi) echo 1;; hello) echo 2;; *) echo 3;; esac",
    "x=foo; case $x in bar|baz) echo match;; *) echo default;; esac",
    "x=yes; case $x in y*) echo starts_y;; *) echo other;; esac",
]


@pytest.mark.parametrize("script", CASE_FIXTURES)
def test_case_compat(script: str) -> None:
    _assert_match(script)


# ==================================================================
# Nested control flow
# ==================================================================

NESTED_FIXTURES = [
    "for i in 1 2; do for j in a b; do echo $i$j; done; done",
    (
        "i=0; while [ $i -lt 2 ]; do "
        "j=0; while [ $j -lt 2 ]; do "
        "echo $i$j; j=$(( j + 1 )); done; "
        "i=$(( i + 1 )); done"
    ),
    ("for i in 1 2 3; do if [ $i -eq 2 ]; then echo match; else echo $i; fi; done"),
]


@pytest.mark.parametrize("script", NESTED_FIXTURES)
def test_nested_control_flow_compat(script: str) -> None:
    _assert_match(script)
