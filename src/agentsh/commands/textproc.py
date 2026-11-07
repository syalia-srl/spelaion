"""Text processing commands: sort, uniq, wc, cut, tr, rev, nl, paste."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from agentsh.commands._io import read_text_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("sort")
def cmd_sort(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    reverse = False
    numeric = False
    unique = False
    key_field: int | None = None
    separator: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-r":
            reverse = True
        elif a == "-n":
            numeric = True
        elif a == "-u":
            unique = True
        elif a == "-k" and i + 1 < len(args):
            i += 1
            # Parse key spec — use first field number
            with contextlib.suppress(ValueError):
                key_field = int(args[i].split(",")[0].split(".")[0])
        elif a == "-t" and i + 1 < len(args):
            i += 1
            separator = args[i]
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "sort")
    lines = text.splitlines()

    def sort_key(line: str) -> tuple[float, str]:
        val = line
        if key_field is not None:
            parts = line.split(separator) if separator else line.split()
            idx = key_field - 1
            val = parts[idx] if 0 <= idx < len(parts) else ""
        if numeric:
            try:
                return (float(val), val)
            except ValueError:
                return (0.0, val)
        return (0.0, val)

    lines.sort(key=sort_key, reverse=reverse)
    if unique:
        lines = list(dict.fromkeys(lines))

    for line in lines:
        io.stdout.write(line + "\n")
    return CommandResult(exit_code=exit_code)


@command("uniq")
def cmd_uniq(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    count = False
    only_dup = False
    only_uniq = False
    files: list[str] = []

    for a in args:
        if a == "-c":
            count = True
        elif a == "-d":
            only_dup = True
        elif a == "-u":
            only_uniq = True
        else:
            files.append(a)

    text, exit_code = read_text_inputs(files, state, vfs, io, "uniq")
    lines = text.splitlines()

    # Group adjacent identical lines
    groups: list[tuple[int, str]] = []
    for line in lines:
        if groups and groups[-1][1] == line:
            groups[-1] = (groups[-1][0] + 1, line)
        else:
            groups.append((1, line))

    for cnt, line in groups:
        if only_dup and cnt < 2:
            continue
        if only_uniq and cnt > 1:
            continue
        if count:
            io.stdout.write(f"      {cnt} {line}\n")
        else:
            io.stdout.write(line + "\n")

    return CommandResult(exit_code=exit_code)


@command("wc")
def cmd_wc(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    show_lines = False
    show_words = False
    show_bytes = False
    files: list[str] = []

    for a in args:
        if a == "-l":
            show_lines = True
        elif a == "-w":
            show_words = True
        elif a == "-c":
            show_bytes = True
        else:
            files.append(a)

    # Default: show all
    if not (show_lines or show_words or show_bytes):
        show_lines = show_words = show_bytes = True

    text, exit_code = read_text_inputs(files, state, vfs, io, "wc")
    lines = text.splitlines()
    nlines = len(lines)
    nwords = len(text.split())
    nbytes = len(text.encode("utf-8"))

    parts: list[str] = []
    if show_lines:
        parts.append(str(nlines))
    if show_words:
        parts.append(str(nwords))
    if show_bytes:
        parts.append(str(nbytes))

    io.stdout.write(" ".join(parts) + "\n")
    return CommandResult(exit_code=exit_code)


@command("cut")
def cmd_cut(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    delim = "\t"
    fields: list[int] = []
    chars: list[tuple[int, int]] = []
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-d" and i + 1 < len(args):
            i += 1
            delim = args[i]
        elif a == "-f" and i + 1 < len(args):
            i += 1
            fields = _parse_ranges(args[i])
        elif a == "-c" and i + 1 < len(args):
            i += 1
            chars = _parse_char_ranges(args[i])
        elif a.startswith("-d") and len(a) > 2:
            delim = a[2:]
        elif a.startswith("-f") and len(a) > 2:
            fields = _parse_ranges(a[2:])
        elif a.startswith("-c") and len(a) > 2:
            chars = _parse_char_ranges(a[2:])
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "cut")

    for line in text.splitlines():
        if chars:
            result: list[str] = []
            for start, end in chars:
                result.append(line[start:end])
            io.stdout.write("".join(result) + "\n")
        elif fields:
            parts = line.split(delim)
            selected: list[str] = []
            for f in fields:
                idx = f - 1
                if 0 <= idx < len(parts):
                    selected.append(parts[idx])
            io.stdout.write(delim.join(selected) + "\n")
        else:
            io.stdout.write(line + "\n")

    return CommandResult(exit_code=exit_code)


def _parse_ranges(spec: str) -> list[int]:
    """Parse field spec like '1,3' or '1-3' into field numbers."""
    result: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a else 1
            end = int(b) if b else start
            result.extend(range(start, end + 1))
        else:
            result.append(int(part))
    return result


def _parse_char_ranges(spec: str) -> list[tuple[int, int]]:
    """Parse char spec into (start, end) index tuples (0-based)."""
    result: list[tuple[int, int]] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) - 1 if a else 0
            end = int(b) if b else start + 1
            result.append((start, end))
        else:
            idx = int(part) - 1
            result.append((idx, idx + 1))
    return result


@command("tr")
def cmd_tr(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    delete = False
    squeeze = False
    positional: list[str] = []

    for a in args:
        if a == "-d":
            delete = True
        elif a == "-s":
            squeeze = True
        else:
            positional.append(a)

    if not positional:
        io.stderr.write("tr: missing operand\n")
        return CommandResult(exit_code=1)

    set1 = _expand_tr_set(positional[0])
    set2 = _expand_tr_set(positional[1]) if len(positional) > 1 else ""

    text = io.stdin.read()

    if delete:
        result = "".join(c for c in text if c not in set1)
    elif squeeze and not set2:
        result = _squeeze_chars(text, set1)
    else:
        # Translate
        if set2:
            if len(set2) < len(set1):
                set2 = set2 + set2[-1] * (len(set1) - len(set2))
            table = str.maketrans(set1, set2[: len(set1)])
            result = text.translate(table)
        else:
            result = text
        if squeeze and set2:
            result = _squeeze_chars(result, set2)

    io.stdout.write(result)
    return CommandResult(exit_code=0)


def _squeeze_chars(text: str, char_set: str) -> str:
    """Collapse consecutive duplicate characters in *char_set*."""
    out: list[str] = []
    for c in text:
        if c in char_set:
            if not out or out[-1] != c:
                out.append(c)
        else:
            out.append(c)
    return "".join(out)


def _expand_tr_set(spec: str) -> str:
    """Expand tr character set: ranges (a-z) and POSIX classes ([:upper:])."""
    result: list[str] = []
    i = 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-" and spec[i + 2] != "]":
            start, end = ord(spec[i]), ord(spec[i + 2])
            if start <= end:
                result.extend(chr(c) for c in range(start, end + 1))
            i += 3
        elif spec[i:].startswith("[:upper:]"):
            result.extend(chr(c) for c in range(ord("A"), ord("Z") + 1))
            i += 9
        elif spec[i:].startswith("[:lower:]"):
            result.extend(chr(c) for c in range(ord("a"), ord("z") + 1))
            i += 9
        elif spec[i:].startswith("[:digit:]"):
            result.extend(chr(c) for c in range(ord("0"), ord("9") + 1))
            i += 9
        elif spec[i:].startswith("[:alpha:]"):
            result.extend(chr(c) for c in range(ord("A"), ord("Z") + 1))
            result.extend(chr(c) for c in range(ord("a"), ord("z") + 1))
            i += 9
        elif spec[i:].startswith("[:alnum:]"):
            result.extend(chr(c) for c in range(ord("0"), ord("9") + 1))
            result.extend(chr(c) for c in range(ord("A"), ord("Z") + 1))
            result.extend(chr(c) for c in range(ord("a"), ord("z") + 1))
            i += 9
        elif spec[i:].startswith("[:space:]"):
            result.extend([" ", "\t", "\n", "\r", "\x0b", "\x0c"])
            i += 9
        elif spec[i] == "\\" and i + 1 < len(spec):
            esc = spec[i + 1]
            if esc == "n":
                result.append("\n")
            elif esc == "t":
                result.append("\t")
            elif esc == "\\":
                result.append("\\")
            else:
                result.append(esc)
            i += 2
        else:
            result.append(spec[i])
            i += 1
    return "".join(result)


@command("rev")
def cmd_rev(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    text, exit_code = read_text_inputs(args, state, vfs, io, "rev")
    for line in text.splitlines():
        io.stdout.write(line[::-1] + "\n")
    return CommandResult(exit_code=exit_code)


@command("nl")
def cmd_nl(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    body_numbering = "t"  # default: number non-empty lines
    files: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-b" and i + 1 < len(args):
            i += 1
            body_numbering = args[i]
        elif a.startswith("-b") and len(a) > 2:
            body_numbering = a[2:]
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "nl")
    line_num = 1
    for line in text.splitlines():
        if body_numbering == "a" or (body_numbering == "t" and line.strip()):
            io.stdout.write(f"     {line_num}\t{line}\n")
            line_num += 1
        else:
            io.stdout.write(f"       \t{line}\n")

    return CommandResult(exit_code=exit_code)


@command("paste")
def cmd_paste(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    delim = "\t"
    files: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-d" and i + 1 < len(args):
            i += 1
            delim = args[i]
        elif a.startswith("-d") and len(a) > 2:
            delim = a[2:]
        else:
            files.append(a)
        i += 1

    if not files:
        # Just pass through stdin
        io.stdout.write(io.stdin.read())
        return CommandResult(exit_code=0)

    # Read all files into lists of lines
    all_lines: list[list[str]] = []
    exit_code = 0
    for f in files:
        if f == "-":
            content = io.stdin.read()
        else:
            abs_path = vfs.resolve(f, state.cwd)
            try:
                content = vfs.read(abs_path).decode("utf-8", errors="replace")
            except FileNotFoundError:
                io.stderr.write(f"paste: {f}: No such file or directory\n")
                exit_code = 1
                content = ""
        all_lines.append(content.splitlines())

    max_len = max((len(lines) for lines in all_lines), default=0)
    for i in range(max_len):
        parts: list[str] = []
        for lines in all_lines:
            parts.append(lines[i] if i < len(lines) else "")
        io.stdout.write(delim.join(parts) + "\n")

    return CommandResult(exit_code=exit_code)
