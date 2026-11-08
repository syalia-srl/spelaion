"""A prefix assignment is in the environment of its command, and only there."""

from __future__ import annotations

from spelaion import Bash


def test_prefix_assignment_reaches_env() -> None:
    assert Bash().run("FOO=bar env | grep FOO").stdout == "FOO=bar\n"


def test_prefix_assignment_is_gone_after() -> None:
    r = Bash().run("FOO=bar true; env | grep -c FOO; echo [$FOO]")
    assert r.stdout == "0\n[]\n"


def test_prefix_assignment_over_an_export_is_restored() -> None:
    r = Bash().run("export FOO=a; FOO=b env | grep FOO; env | grep FOO")
    assert r.stdout == "FOO=b\nFOO=a\n"


def test_assignment_without_a_command_is_not_exported() -> None:
    r = Bash().run("FOO=bar; env | grep -c FOO; echo $FOO")
    assert r.stdout == "0\nbar\n"
