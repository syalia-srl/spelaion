"""Differential tests comparing agentsh against real Bash.

Compares stdout + exit_code for the officially supported subset.
FS side effects are excluded from comparison.

These tests require /bin/bash to be available.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from agentsh.api.engine import ShellEngine

# Skip all if bash not available
BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="bash not found")


@dataclass
class DiffResult:
    script: str
    agentsh_stdout: str
    agentsh_exit: int
    bash_stdout: str
    bash_exit: int
    match: bool


def _run_bash(script: str) -> tuple[str, int]:
    """Run a script in real bash and return (stdout, exit_code)."""
    result = subprocess.run(
        [BASH, "-c", script],  # type: ignore[arg-type]
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    return result.stdout, result.returncode


def _run_agentsh(script: str) -> tuple[str, int]:
    """Run a script in agentsh and return (stdout, exit_code)."""
    engine = ShellEngine()
    result = engine.run(script)
    return result.stdout, result.result.exit_code


def _compare(script: str) -> DiffResult:
    agentsh_stdout, agentsh_exit = _run_agentsh(script)
    bash_stdout, bash_exit = _run_bash(script)
    match = agentsh_stdout == bash_stdout and agentsh_exit == bash_exit
    return DiffResult(
        script=script,
        agentsh_stdout=agentsh_stdout,
        agentsh_exit=agentsh_exit,
        bash_stdout=bash_stdout,
        bash_exit=bash_exit,
        match=match,
    )


def _assert_match(r: DiffResult) -> None:
    """Assert that agentsh and bash outputs match."""
    assert r.match, (
        f"Mismatch for: {r.script!r}\n"
        f"  agentsh: {r.agentsh_stdout!r} "
        f"(exit {r.agentsh_exit})\n"
        f"  bash:    {r.bash_stdout!r} "
        f"(exit {r.bash_exit})"
    )


# --- Fixtures: Echo / Basic Output ---

ECHO_FIXTURES = [
    "echo hello",
    "echo hello world",
    "echo -n hello",
    'echo ""',
    'echo "hello world"',
    "echo 'hello world'",
    "echo hello; echo world",
]


@pytest.mark.parametrize("script", ECHO_FIXTURES)
def test_echo_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Variables ---

VAR_FIXTURES = [
    "FOO=hello; echo $FOO",
    'FOO=hello; echo "$FOO"',
    'FOO=hello; echo "${FOO}"',
    'FOO=hello; BAR=world; echo "$FOO $BAR"',
    'unset FOO; echo "${FOO:-default}"',
    'FOO=val; echo "${FOO:-default}"',
    'unset FOO; echo "${FOO:+alt}"',
    'FOO=val; echo "${FOO:+alt}"',
]


@pytest.mark.parametrize("script", VAR_FIXTURES)
def test_variable_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Quoting ---

QUOTE_FIXTURES = [
    "echo 'single quotes'",
    'echo "double quotes"',
    "echo no quotes",
    "echo 'preserves $VAR'",
    'FOO=bar; echo "expands $FOO"',
]


@pytest.mark.parametrize("script", QUOTE_FIXTURES)
def test_quoting_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Exit Status ---

STATUS_FIXTURES = [
    "true; echo $?",
    "false; echo $?",
    "true && echo ok",
    "false && echo nope",
    "false || echo fallback",
    "true || echo nope",
]


@pytest.mark.parametrize("script", STATUS_FIXTURES)
def test_exit_status_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Subshells and Groups ---

COMPOUND_FIXTURES = [
    "FOO=outer; (FOO=inner; echo $FOO); echo $FOO",
    "{ FOO=inner; }; echo $FOO",
    "(echo hello)",
    "{ echo hello; }",
]


@pytest.mark.parametrize("script", COMPOUND_FIXTURES)
def test_compound_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Builtins ---

BUILTIN_FIXTURES = [
    # 'pwd' excluded — VFS cwd (/) differs from real cwd
    "echo hello",
    'printf "%s\\n" hello',
    "export FOO=bar; echo $FOO",
    'FOO=bar; unset FOO; echo "$FOO"',
    'test -z "" && echo empty',
    'test -n "x" && echo notempty',
    "[ 1 -eq 1 ] && echo eq",
    "[ 1 -ne 2 ] && echo ne",
    "[ 3 -gt 2 ] && echo gt",
    "[ 2 -lt 3 ] && echo lt",
]


@pytest.mark.parametrize("script", BUILTIN_FIXTURES)
def test_builtin_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Functions ---

FUNCTION_FIXTURES = [
    "greet() { echo hello; }; greet",
    "add() { echo $(( $1 + $2 )); }; add 3 4",
]


@pytest.mark.parametrize("script", FUNCTION_FIXTURES)
def test_function_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Arithmetic ---

ARITH_FIXTURES = [
    "echo $(( 1 + 2 ))",
    "echo $(( 10 - 3 ))",
    "echo $(( 4 * 5 ))",
    "echo $(( 10 / 3 ))",
    "echo $(( 10 % 3 ))",
    "X=5; echo $(( X + 3 ))",
]


@pytest.mark.parametrize("script", ARITH_FIXTURES)
def test_arithmetic_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Tilde ---

TILDE_FIXTURES = [
    "echo ~",
]


@pytest.mark.parametrize("script", TILDE_FIXTURES)
def test_tilde_compat(script: str) -> None:
    # Tilde expands differently per environment, just check exit code
    r = _compare(script)
    assert r.agentsh_exit == r.bash_exit


# --- Fixtures: Command Substitution ---

CMDSUB_FIXTURES = [
    "echo $(echo hello)",
    "FOO=$(echo bar); echo $FOO",
]


@pytest.mark.parametrize("script", CMDSUB_FIXTURES)
def test_cmdsub_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Assignment ---

ASSIGN_FIXTURES = [
    "FOO=bar; echo $FOO",
    "FOO=bar BAR=baz; echo $FOO $BAR",
    "A=1; B=2; echo $A $B",
]


@pytest.mark.parametrize("script", ASSIGN_FIXTURES)
def test_assignment_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Nested Variable Expansion ---

NESTED_VAR_FIXTURES = [
    'unset A; echo "${A:-hello}"',
    'A=val; echo "${A:-hello}"',
    'A=; echo "${A:-hello}"',
    'A=; echo "${A-hello}"',
    'unset A; echo "${A-hello}"',
    'unset A; echo "${A:=fallback}"; echo $A',
    'FOO=hello.world; echo "${FOO%.*}"',
    'FOO=hello.world.txt; echo "${FOO%%.*}"',
]


@pytest.mark.parametrize("script", NESTED_VAR_FIXTURES)
def test_nested_var_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Special Parameters ---

SPECIAL_PARAM_FIXTURES = [
    "echo $?",
    "echo $#",
    "set -- a b c; echo $#",
    "set -- a b c; echo $1 $2 $3",
    "set -- x y z; echo $1",
]


@pytest.mark.parametrize("script", SPECIAL_PARAM_FIXTURES)
def test_special_param_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Multiline Scripts ---

MULTILINE_FIXTURES = [
    "echo a\necho b",
    "A=1\necho $A",
    'A=hello\nB=world\necho "$A $B"',
    "f() { echo func; }\nf",
    "echo line1\necho line2\necho line3",
]


@pytest.mark.parametrize("script", MULTILINE_FIXTURES)
def test_multiline_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Complex Quoting ---

COMPLEX_QUOTING_FIXTURES = [
    """echo 'foo'"bar"'baz'""",
    'echo "hello world"',
    'X=val; echo "x is $X"',
    'echo "$UNDEFINED"',
    'echo ""',
    'echo "" foo',
    'echo foo "" bar',
    'FOO="hello world"; echo "$FOO"',
    "echo 'single'\"double\"'single'",
    'A=hello; echo "$A world"',
]


@pytest.mark.parametrize("script", COMPLEX_QUOTING_FIXTURES)
def test_complex_quoting_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Advanced Functions ---

FUNCTION_ADVANCED_FIXTURES = [
    "f() { echo $1 $2; }; f a b",
    "f() { return 0; }; f && echo yes",
    "f() { return 1; }; f || echo no",
    "f() { return 42; }; f; echo $?",
    "f() { echo before; return; echo after; }; f",
    "outer() { inner() { echo inside; }; inner; }; outer",
    "a() { echo a; }; b() { a; echo b; }; b",
    "a() { echo $1; }; b() { a hello; }; b",
    "f() { local x=42; echo $x; }; f",
    "f() { echo $1; shift; echo $1; }; f x y",
]


@pytest.mark.parametrize("script", FUNCTION_ADVANCED_FIXTURES)
def test_function_advanced_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Subshell and Group Advanced ---

SUBSHELL_GROUP_FIXTURES = [
    "(echo a); (echo b)",
    "{ echo a; }; { echo b; }",
    "{ { echo deep; }; }",
    "(A=sub); echo ${A:-empty}",
    "{ A=grp; }; echo $A",
    "{ (echo sub); echo grp; }",
    "(echo a; { echo b; }; echo c)",
    "(false); echo $?",
    "(true); echo $?",
    "{ false; }; echo $?",
]


@pytest.mark.parametrize("script", SUBSHELL_GROUP_FIXTURES)
def test_subshell_group_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Advanced Arithmetic ---

ARITHMETIC_ADVANCED_FIXTURES = [
    "echo $(( -5 + 3 ))",
    "echo $(( (2+3)*4 ))",
    "X=5; echo $(( X * 2 ))",
    "echo $(( 2 + 3 * 4 ))",
    "A=10; B=3; echo $(( A - B ))",
    "echo $(( 0 + 0 ))",
    "echo $(( 1 - 1 ))",
    "echo $(( 5 * 0 ))",
    "unset X; echo $(( X + 1 ))",
]


@pytest.mark.parametrize("script", ARITHMETIC_ADVANCED_FIXTURES)
def test_arithmetic_advanced_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Advanced Assignments ---

ASSIGNMENT_ADVANCED_FIXTURES = [
    "export FOO=bar; echo $FOO",
    "A=1; B=2; C=3; echo $A $B $C",
    "X=$(echo hello); echo $X",
    "declare X=hello; echo $X",
    "A=hello; export A; echo $A",
    "export A=1; export B=2; echo $A $B",
    "A=hello; B=$A; echo $B",
    "A=hello; unset A; echo ${A:-gone}",
]


@pytest.mark.parametrize("script", ASSIGNMENT_ADVANCED_FIXTURES)
def test_assignment_advanced_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Expansion Edge Cases ---

EXPANSION_EDGE_FIXTURES = [
    "A=hello; B=world; echo $A$B",
    'A=hello; echo "${A}world"',
    'A=hello; echo "before${A}after"',
    "FOO=hello.world; echo ${FOO#*.}",
    "FOO=hello.world.txt; echo ${FOO##*.}",
    'A="hello world"; echo ${A%% *}',
    'A="hello world"; echo ${A##* }',
    "A=abcabc; echo ${A#*b}",
    "A=abcabc; echo ${A##*b}",
    "echo $(echo $(echo deep))",
    "X=$(echo $(echo hello)); echo $X",
    'X=$(true); echo "[$X]"',
    "echo $(echo $(( 1 + 2 )))",
]


@pytest.mark.parametrize("script", EXPANSION_EDGE_FIXTURES)
def test_expansion_edge_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: And/Or Chains ---

ANDOR_CHAIN_FIXTURES = [
    "true && true && echo yes",
    "false || false || echo fallback",
    "true && false || echo recovered",
    "false || true && echo ok",
    "true && true && true && echo all",
    "false || false || false || echo fallback",
    "true && false && echo nope || echo recovered",
    "true && false; echo $?",
    "false || true; echo $?",
]


@pytest.mark.parametrize("script", ANDOR_CHAIN_FIXTURES)
def test_andor_chain_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Test Builtin Advanced ---

TEST_ADVANCED_FIXTURES = [
    "[ 3 -ge 3 ] && echo ge",
    "[ 3 -le 3 ] && echo le",
    '[ "hello" = "hello" ] && echo same',
    '[ "hello" != "world" ] && echo diff',
    'test -z "" && echo empty',
    'test -z "x" || echo notempty',
    'test -n "x" && echo notempty',
    'test -n "" || echo empty',
]


@pytest.mark.parametrize("script", TEST_ADVANCED_FIXTURES)
def test_test_advanced_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Recursive Functions ---

RECURSIVE_FIXTURES = [
    "count() { echo $1; test $1 -gt 1 && count $(( $1 - 1 )); }; count 3",
]


@pytest.mark.parametrize("script", RECURSIVE_FIXTURES)
def test_recursive_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Printf ---

PRINTF_FIXTURES = [
    "printf hello",
    'printf "%s" hello',
    'printf "%d" 42',
    'printf "%s %s" a b',
    'printf "%%"',
]


@pytest.mark.parametrize("script", PRINTF_FIXTURES)
def test_printf_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Echo Edge Cases ---

ECHO_EDGE_FIXTURES = [
    "echo; echo",
    "echo -n hello; echo world",
    "echo -n; echo ok",
    "echo foo; echo bar; echo baz",
    'FOO="hello world"; echo $FOO',
]


@pytest.mark.parametrize("script", ECHO_EDGE_FIXTURES)
def test_echo_edge_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Pipeline Builtins ---

PIPELINE_FIXTURES = [
    "echo hello | echo piped",
    "{ echo hello; echo world; } | echo piped",
    "echo hello | { echo piped; }",
]


@pytest.mark.parametrize("script", PIPELINE_FIXTURES)
def test_pipeline_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


# --- Fixtures: Complex realistic expressions ---

COMPLEX_REAL_FIXTURES = [
    "X=$(echo $(echo deep)); echo $X",
    'check() { if [ "$1" -gt 5 ]; then echo big; return 0; '
    "else echo small; return 1; fi; }; check 10",
    'R=""; for w in hello world foo; do R="$R $w"; done; echo "$R"',
    "S=0; I=1; while [ $I -le 5 ]; do S=$(( S + I )); I=$(( I + 1 )); done; echo $S",
    "X=banana; case $X in apple|orange) echo fruit1;; "
    "banana|grape) echo fruit2;; *) echo unknown;; esac",
    'classify() { if [ "$1" -lt 0 ]; then echo negative; '
    'elif [ "$1" -eq 0 ]; then echo zero; '
    "else echo positive; fi; }; "
    "classify -3; classify 0; classify 7",
    'unset A; unset B; echo "${A:-${B:-final}}"',
    "V=before; (V=inside; echo $V); echo $V",
    'unset EX; (export EX=leaked); echo "${EX:-unset}"',
    "X=10; if [ $(( X % 3 )) -eq 1 ]; then echo mod1; else echo other; fi",
    'for x in $(echo a b c); do echo "item:$x"; done',
    'for i in 1 2; do for j in a b; do echo "$i$j"; done; done',
    "double() { echo $(( $1 * 2 )); }; "
    "triple() { echo $(( $1 * 3 )); }; "
    "echo $(double 5) $(triple 5)",
    'A=hello; B=world; echo "${A} ${B}" \'!\' "done"',
    "N=4; I=0; while [ $I -lt $N ]; do I=$(( I + 1 )); echo $I; done",
    "X=$(( 7 * 8 + 1 )); echo $X",
    "{ true && echo a; } && echo b",
    'unset FOO; : "${FOO:=default_val}"; echo $FOO',
    "first_last() { F=$1; shift; "
    "while [ $# -gt 0 ]; do L=$1; shift; done; "
    'echo "$F $L"; }; first_last a b c d',
    'ext() { case "$1" in *.sh) echo shell;; '
    "*.py) echo python;; *) echo other;; esac; }; "
    "ext foo.py; ext bar.sh; ext baz.txt",
]


@pytest.mark.parametrize("script", COMPLEX_REAL_FIXTURES)
def test_complex_real_compat(script: str) -> None:
    r = _compare(script)
    _assert_match(r)


def test_compatibility_report(tmp_path: Path) -> None:
    """Generate a compatibility report as JSON."""
    all_fixtures = (
        ECHO_FIXTURES
        + VAR_FIXTURES
        + QUOTE_FIXTURES
        + STATUS_FIXTURES
        + COMPOUND_FIXTURES
        + BUILTIN_FIXTURES
        + FUNCTION_FIXTURES
        + ARITH_FIXTURES
        + CMDSUB_FIXTURES
        + ASSIGN_FIXTURES
        + NESTED_VAR_FIXTURES
        + SPECIAL_PARAM_FIXTURES
        + MULTILINE_FIXTURES
        + COMPLEX_QUOTING_FIXTURES
        + FUNCTION_ADVANCED_FIXTURES
        + SUBSHELL_GROUP_FIXTURES
        + ARITHMETIC_ADVANCED_FIXTURES
        + ASSIGNMENT_ADVANCED_FIXTURES
        + EXPANSION_EDGE_FIXTURES
        + ANDOR_CHAIN_FIXTURES
        + TEST_ADVANCED_FIXTURES
        + RECURSIVE_FIXTURES
        + PRINTF_FIXTURES
        + ECHO_EDGE_FIXTURES
        + PIPELINE_FIXTURES
        + COMPLEX_REAL_FIXTURES
    )

    results = []
    passed = 0
    failed = 0

    for script in all_fixtures:
        try:
            r = _compare(script)
            results.append(
                {
                    "script": r.script,
                    "match": r.match,
                    "agentsh_stdout": r.agentsh_stdout,
                    "bash_stdout": r.bash_stdout,
                    "agentsh_exit": r.agentsh_exit,
                    "bash_exit": r.bash_exit,
                }
            )
            if r.match:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            results.append(
                {
                    "script": script,
                    "match": False,
                    "error": str(e),
                }
            )
            failed += 1

    report = {
        "total": len(all_fixtures),
        "passed": passed,
        "failed": failed,
        "pass_rate": f"{passed / len(all_fixtures) * 100:.1f}%",
        "results": results,
    }

    report_path = tmp_path / "compatibility_report.json"
    report_path.write_text(json.dumps(report, indent=2))
