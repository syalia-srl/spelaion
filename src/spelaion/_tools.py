"""The three agent tools as plain data, for an in-process loop or MCP."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from spelaion._types import Attachment, Result
from spelaion.vfs.mounts import Mount

EDIT_DESCRIPTION = (
    "Replace old with new in the file at path. old must match the file's text "
    "exactly and occur exactly once; otherwise the edit fails and the file is "
    "unchanged."
)

WRITE_DESCRIPTION = (
    "Create the file at path, or replace all of it, with content. "
    "Missing parent folders are created."
)


@dataclass
class ToolOutput:
    """What a tool hands the model: text, then images."""

    text: str
    images: list[Attachment]


@dataclass
class Tool:
    """One tool: its name, what the model reads about it, and how to call it."""

    name: str  # "bash" | "edit" | "write"
    description: str
    input_schema: dict[str, Any]  # JSON Schema
    fn: Callable[..., ToolOutput]  # called with the schema's fields as keywords


def make_tools(
    bash: Callable[[str], Result],
    edit: Callable[[str, str, str], Result],
    write: Callable[[str, str], Result],
    bash_description: str,
) -> list[Tool]:
    """``bash``, ``edit`` and ``write`` over the sandbox calls given."""

    def run_bash(command: str) -> ToolOutput:
        return output(bash(command))

    def run_edit(path: str, old: str, new: str) -> ToolOutput:
        return output(edit(path, old, new))

    def run_write(path: str, content: str) -> ToolOutput:
        return output(write(path, content))

    path = ("path", "The file, absolute or relative to the working directory.")
    return [
        Tool(
            "bash",
            bash_description,
            schema(("command", "The bash command to run.")),
            run_bash,
        ),
        Tool(
            "edit",
            EDIT_DESCRIPTION,
            schema(path, ("old", "The text to replace."), ("new", "Its replacement.")),
            run_edit,
        ),
        Tool(
            "write",
            WRITE_DESCRIPTION,
            schema(path, ("content", "The file's whole new text.")),
            run_write,
        ),
    ]


def describe_bash(
    mounts: list[Mount], cwd: str, python: bool, commands: list[str], timeout_s: float
) -> str:
    """What the model reads about ``bash``; it names no host path."""
    folders = ", ".join(
        f"{m.path} ({'read-only' if m.readonly else 'read-write'})" for m in mounts
    )
    python_text = (
        "python has the standard library and PyYAML" if python else "there is no python"
    )
    others = [c for c in commands if c != "show"]
    extra = f" Extra commands: {', '.join(others)}." if others else ""
    return (
        "Run a command in an emulated bash shell. "
        f"Folders: {folders}. "
        f"The working directory is {cwd}. "
        "Each call starts a fresh shell: variables, functions and cd do not "
        "persist; files do. "
        f"There is no network, no pip, no background processes; {python_text}. "
        f"A call times out after {timeout_s:g} seconds; long output is cut with "
        "a notice. "
        "show FILE... shows you PNG, JPEG or WebP images." + extra
    )


def output(result: Result) -> ToolOutput:
    """stdout, then ``[stderr]`` and its text, then ``[exit code N]`` if not 0.

    A call that succeeds, prints nothing and shows no image reads ``(no output)``.
    """
    text = result.stdout
    blocks: list[str] = []
    if result.stderr:
        blocks.append("[stderr]\n" + result.stderr)
    if result.exit_code:
        blocks.append(f"[exit code {result.exit_code}]")
    for block in blocks:
        if text and not text.endswith("\n"):
            text += "\n"
        text += block
    if not text and not result.attachments:
        text = "(no output)"
    return ToolOutput(text, list(result.attachments))


def schema(*fields: tuple[str, str]) -> dict[str, Any]:
    """A JSON Schema for an object of string *fields*, (name, text), all required."""
    return {
        "type": "object",
        "properties": {f: {"type": "string", "description": d} for f, d in fields},
        "required": [f for f, _ in fields],
        "additionalProperties": False,
    }
