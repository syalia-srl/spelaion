"""Sandbox.tools(): bash, edit and write for an in-process agent loop."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import HostContext, Limits, Mount, Result, Sandbox, Tool, ToolOutput

PNG_FIXTURE = Path(__file__).parent / "sandbox" / "data" / "pixel.png"


@pytest.fixture
def rw(tmp_path: Path) -> Path:
    d = tmp_path / "rw"
    d.mkdir()
    return d


@pytest.fixture
def ro(tmp_path: Path) -> Path:
    d = tmp_path / "ro"
    d.mkdir()
    return d


@pytest.fixture
def sb(ro: Path, rw: Path) -> Iterator[Sandbox]:
    mounts = [Mount("/project", ro, readonly=True), Mount("/scratch", rw)]
    with Sandbox(mounts, cwd="/scratch") as s:
        yield s


def by_name(sb: Sandbox) -> dict[str, Tool]:
    return {t.name: t for t in sb.tools()}


# --- From the brief ---------------------------------------------------------


def test_three_names_in_order(sb: Sandbox) -> None:
    assert [t.name for t in sb.tools()] == ["bash", "edit", "write"]


def test_bash_text_is_stdout(sb: Sandbox) -> None:
    assert by_name(sb)["bash"].fn(command="echo hi") == ToolOutput("hi\n", [])


def test_bash_text_adds_stderr_and_exit_code(sb: Sandbox) -> None:
    out = by_name(sb)["bash"].fn(command="echo out; echo err >&2; exit 3")
    assert out.text == "out\n[stderr]\nerr\n[exit code 3]"


def test_bash_text_without_stdout(sb: Sandbox) -> None:
    out = by_name(sb)["bash"].fn(command="echo err >&2")
    assert out.text == "[stderr]\nerr\n"
    assert by_name(sb)["bash"].fn(command="false").text == "[exit code 1]"


def test_bash_text_breaks_line_after_unterminated_stdout(sb: Sandbox) -> None:
    out = by_name(sb)["bash"].fn(command="printf x; printf y >&2; exit 2")
    assert out.text == "x\n[stderr]\ny\n[exit code 2]"


def test_description_lists_host_commands_at_call_time(sb: Sandbox) -> None:
    @sb.command
    def oikos_check(ctx: HostContext, args: list[str]) -> Result:
        return Result()

    description = by_name(sb)["bash"].description
    assert "Extra commands: show, oikos-check." in description

    @sb.command
    def later(ctx: HostContext, args: list[str]) -> Result:
        return Result()

    assert "later" not in description
    assert "show, oikos-check, later." in by_name(sb)["bash"].description


def test_description_text(sb: Sandbox) -> None:
    assert by_name(sb)["bash"].description == (
        "Run a command in an emulated bash shell. "
        "Folders: /project (read-only), /scratch (read-write). "
        "The working directory is /scratch. "
        "Each call starts a fresh shell: variables, functions and cd do not "
        "persist; files do. "
        "There is no network, no pip, no background processes; there is no python. "
        "A call times out after 30 seconds; long output is cut with a notice. "
        "Extra commands: show. "
        "show FILE... shows you PNG, JPEG or WebP images."
    )


@pytest.mark.wasi
def test_description_with_python(rw: Path) -> None:
    with Sandbox([Mount("/scratch", rw)], python=True) as s:
        description = by_name(s)["bash"].description
    assert (
        "no network, no pip, no background processes; python has the standard "
        "library and PyYAML." in description
    )
    assert "The working directory is /." in description


def test_description_names_no_host_path(sb: Sandbox, ro: Path, rw: Path) -> None:
    for tool in sb.tools():
        assert str(ro) not in tool.description
        assert str(rw) not in tool.description
        assert str(rw.parent) not in tool.description


# --- edit and write ---------------------------------------------------------


def test_edit_and_write_descriptions(sb: Sandbox) -> None:
    tools = by_name(sb)
    assert tools["edit"].description == (
        "Replace old with new in the file at path. old must match the file's "
        "text exactly and occur exactly once; otherwise the edit fails and the "
        "file is unchanged."
    )
    assert tools["write"].description == (
        "Create the file at path, or replace all of it, with content. "
        "Missing parent folders are created."
    )


def test_write_then_edit(sb: Sandbox, rw: Path) -> None:
    tools = by_name(sb)
    assert tools["write"].fn(path="a.txt", content="one two\n").text == "(no output)"
    assert (rw / "a.txt").read_text() == "one two\n"
    tools["edit"].fn(path="/scratch/a.txt", old="two", new="three")
    assert (rw / "a.txt").read_text() == "one three\n"


def test_edit_failure_is_text(sb: Sandbox, rw: Path) -> None:
    (rw / "a.txt").write_text("x x\n")
    out = by_name(sb)["edit"].fn(path="a.txt", old="x", new="y")
    assert out.text.startswith("[stderr]\nold text occurs 2 times in /scratch/a.txt")
    assert out.text.endswith("[exit code 1]")


def test_write_to_read_only_mount_is_text(sb: Sandbox) -> None:
    out = by_name(sb)["write"].fn(path="/project/a.txt", content="x")
    assert out.text.startswith("[stderr]\n")
    assert out.text.endswith("[exit code 1]")


def test_input_schemas(sb: Sandbox) -> None:
    tools = by_name(sb)
    for name, fields in [
        ("bash", ["command"]),
        ("edit", ["path", "old", "new"]),
        ("write", ["path", "content"]),
    ]:
        schema = tools[name].input_schema
        assert schema["type"] == "object"
        assert list(schema["properties"]) == fields
        assert schema["required"] == fields
        assert schema["additionalProperties"] is False
        assert all(p["type"] == "string" for p in schema["properties"].values())


def test_images_come_through(sb: Sandbox, rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")
    out = by_name(sb)["bash"].fn(command="show v.png")
    assert out.text == ""
    assert [(a.mime, a.data) for a in out.images] == [
        ("image/png", PNG_FIXTURE.read_bytes())
    ]


def test_write_creates_parent_folders(sb: Sandbox, rw: Path) -> None:
    out = by_name(sb)["write"].fn(path="a/b/c.txt", content="x")
    assert out.text == "(no output)"
    assert (rw / "a" / "b" / "c.txt").read_text() == "x"


def test_description_names_the_sandbox_timeout(rw: Path) -> None:
    with Sandbox([Mount("/scratch", rw)], limits=Limits(timeout_s=2.5)) as s:
        description = by_name(s)["bash"].description
    assert "A call times out after 2.5 seconds;" in description


def test_empty_success_reads_no_output(sb: Sandbox) -> None:
    assert by_name(sb)["bash"].fn(command="true").text == "(no output)"
    assert by_name(sb)["bash"].fn(command="false").text == "[exit code 1]"
