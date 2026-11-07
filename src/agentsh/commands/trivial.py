"""Trivial utility commands.

tac, sha1sum, uuidgen, shuf, file, column, fmt, envsubst, install.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import textwrap
import uuid
from typing import TYPE_CHECKING

from agentsh.commands._io import read_binary_inputs, read_text_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ---------------------------------------------------------------------------
# tac
# ---------------------------------------------------------------------------


@command("tac")
def cmd_tac(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    text, exit_code = read_text_inputs(files, state, vfs, io, "tac")
    lines = text.splitlines(keepends=True)
    lines.reverse()
    io.stdout.write("".join(lines))
    return CommandResult(exit_code=exit_code)


# ---------------------------------------------------------------------------
# sha1sum
# ---------------------------------------------------------------------------


@command("sha1sum")
def cmd_sha1sum(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    for fname, data in read_binary_inputs(files, state, vfs, io, "sha1sum"):
        if data is None:
            continue
        digest = hashlib.sha1(data).hexdigest()
        io.stdout.write(f"{digest}  {fname}\n")
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# uuidgen
# ---------------------------------------------------------------------------


@command("uuidgen")
def cmd_uuidgen(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    # -r (random) is the default and only supported mode
    io.stdout.write(str(uuid.uuid4()) + "\n")
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# shuf
# ---------------------------------------------------------------------------


@command("shuf")
def cmd_shuf(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    count: int | None = None
    echo_words: list[str] | None = None
    input_range: tuple[int, int] | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-n" and i + 1 < len(args):
            i += 1
            try:
                count = int(args[i])
            except ValueError:
                io.stderr.write(f"shuf: invalid line count: {args[i]!r}\n")
                return CommandResult(exit_code=1)
        elif a == "-e":
            echo_words = list(args[i + 1 :])
            break
        elif a == "-i" and i + 1 < len(args):
            i += 1
            m = re.fullmatch(r"(\d+)-(\d+)", args[i])
            if m is None:
                io.stderr.write(f"shuf: invalid input range: {args[i]!r}\n")
                return CommandResult(exit_code=1)
            input_range = (int(m.group(1)), int(m.group(2)))
        else:
            files.append(a)
        i += 1

    # Build lines from the chosen source
    if echo_words is not None:
        lines = echo_words
    elif input_range is not None:
        lo, hi = input_range
        lines = [str(n) for n in range(lo, hi + 1)]
    else:
        text, exit_code = read_text_inputs(files, state, vfs, io, "shuf")
        if exit_code != 0:
            return CommandResult(exit_code=exit_code)
        lines = text.splitlines()

    random.shuffle(lines)

    if count is not None:
        lines = lines[:count]

    for line in lines:
        io.stdout.write(line + "\n")
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------

_EXTENSION_MAP: dict[str, str] = {
    ".py": "Python script",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".sh": "Bourne shell script",
    ".md": "Markdown",
    ".html": "HTML document",
    ".css": "CSS",
    ".json": "JSON data",
    ".yaml": "YAML data",
    ".yml": "YAML data",
    ".toml": "TOML data",
    ".txt": "ASCII text",
    ".csv": "CSV text",
    ".xml": "XML document",
    ".sql": "SQL",
    ".go": "Go source",
    ".rs": "Rust source",
    ".java": "Java source",
    ".c": "C source",
    ".h": "C header",
    ".cpp": "C++ source",
    ".cc": "C++ source",
    ".rb": "Ruby script",
    ".php": "PHP script",
    ".svg": "SVG image",
}


def _detect_file_type(content: bytes, filename: str) -> str:
    """Inspect content and filename to determine a file type string."""
    if len(content) == 0:
        return "empty"

    # Content-based detection
    if content[:2] == b"#!":
        first_line = content.split(b"\n", 1)[0].decode("utf-8", errors="replace")
        interp = first_line[2:].strip()
        return f"script, {interp}"

    text_prefix = content[:64].lstrip()
    if text_prefix[:1] in (b"{", b"["):
        try:
            json.loads(content.decode("utf-8", errors="replace"))
            return "JSON data"
        except (json.JSONDecodeError, ValueError):
            pass

    if text_prefix[:3] == b"---":
        return "YAML data"
    if text_prefix[:5] == b"<?xml":
        return "XML document"
    if content[:2] == b"PK":
        return "Zip archive"
    if content[:2] == b"\x1f\x8b":
        return "gzip compressed data"

    # Extension-based fallback
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()
        if ext in _EXTENSION_MAP:
            return _EXTENSION_MAP[ext]

    # Check if all bytes are printable ASCII
    if all(b in {9, 10, 13} or 32 <= b < 127 for b in content):
        return "ASCII text"

    return "data"


@command("file")
def cmd_file(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    if not files:
        io.stderr.write("file: missing operand\n")
        return CommandResult(exit_code=1)

    exit_code = 0
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        try:
            data = vfs.read(abs_path)
        except FileNotFoundError:
            io.stderr.write(f"file: {f}: No such file or directory\n")
            exit_code = 1
            continue
        except IsADirectoryError:
            io.stdout.write(f"{f}: directory\n")
            continue

        ftype = _detect_file_type(data, f)
        io.stdout.write(f"{f}: {ftype}\n")

    return CommandResult(exit_code=exit_code)


# ---------------------------------------------------------------------------
# column
# ---------------------------------------------------------------------------


@command("column")
def cmd_column(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    table_mode = False
    separator: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-t":
            table_mode = True
        elif a == "-s" and i + 1 < len(args):
            i += 1
            separator = args[i]
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "column")

    if not table_mode:
        io.stdout.write(text)
        return CommandResult(exit_code=exit_code)

    # Table mode: split lines into columns and align
    rows: list[list[str]] = []
    for line in text.splitlines():
        cols = line.split(separator) if separator is not None else line.split()
        rows.append(cols)

    if not rows:
        return CommandResult(exit_code=exit_code)

    # Compute max width per column
    max_cols = max(len(r) for r in rows)
    widths: list[int] = [0] * max_cols
    for row in rows:
        for ci, cell in enumerate(row):
            widths[ci] = max(widths[ci], len(cell))

    for row in rows:
        parts: list[str] = []
        for ci, cell in enumerate(row):
            if ci < len(row) - 1:
                parts.append(cell.ljust(widths[ci]))
            else:
                parts.append(cell)
        io.stdout.write("  ".join(parts) + "\n")

    return CommandResult(exit_code=exit_code)


# ---------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------


@command("fmt")
def cmd_fmt(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    width = 75
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-w" and i + 1 < len(args):
            i += 1
            try:
                width = int(args[i])
            except ValueError:
                io.stderr.write(f"fmt: invalid width: {args[i]!r}\n")
                return CommandResult(exit_code=1)
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "fmt")

    # Split into paragraphs (separated by blank lines)
    paragraphs = re.split(r"\n{2,}", text)
    output_parts: list[str] = []
    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            output_parts.append("")
            continue
        output_parts.append(textwrap.fill(stripped, width=width))

    io.stdout.write("\n\n".join(output_parts))
    if text.endswith("\n"):
        io.stdout.write("\n")
    return CommandResult(exit_code=exit_code)


# ---------------------------------------------------------------------------
# envsubst
# ---------------------------------------------------------------------------


@command("envsubst")
def cmd_envsubst(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    text = io.stdin.read()

    def _replace(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        val = state.get_var(name)
        return val if val is not None else ""

    result = re.sub(r"\$\{(\w+)\}|\$(\w+)", _replace, text)
    io.stdout.write(result)
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


@command("install")
def cmd_install(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    mode: int | None = None
    create_dir = False
    positional: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-d":
            create_dir = True
        elif a == "-m" and i + 1 < len(args):
            i += 1
            try:
                mode = int(args[i], 8)
            except ValueError:
                io.stderr.write(f"install: invalid mode: {args[i]!r}\n")
                return CommandResult(exit_code=1)
        else:
            positional.append(a)
        i += 1

    if create_dir:
        # mkdir -p each arg
        for d in positional:
            abs_path = vfs.resolve(d, state.cwd)
            vfs.mkdir(abs_path, parents=True)
            if mode is not None:
                node = vfs.get_node(abs_path)
                if node is not None:
                    node.mode = mode
        return CommandResult(exit_code=0)

    # Copy source(s) to dest
    if len(positional) < 2:
        io.stderr.write("install: missing file operand\n")
        return CommandResult(exit_code=1)

    dest = positional[-1]
    sources = positional[:-1]

    for src_arg in sources:
        src = vfs.resolve(src_arg, state.cwd)
        dst = vfs.resolve(dest, state.cwd)
        try:
            vfs.copy_file(src, dst)
        except FileNotFoundError:
            io.stderr.write(
                f"install: cannot stat '{src_arg}': No such file or directory\n"
            )
            return CommandResult(exit_code=1)
        except IsADirectoryError:
            io.stderr.write(f"install: '{src_arg}': Is a directory\n")
            return CommandResult(exit_code=1)

        if mode is not None:
            target_node = vfs.get_node(dst)
            if target_node is not None:
                target_node.mode = mode

    return CommandResult(exit_code=0)
