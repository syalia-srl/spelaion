from __future__ import annotations

from io import StringIO

from spelaion.commands import COMMANDS
from spelaion.commands._io import split_flags
from spelaion.commands._registry import command
from spelaion.exec.redirs import IOContext
from spelaion.runtime.result import CommandResult
from spelaion.runtime.state import ShellState
from spelaion.vfs.base import Filesystem
from spelaion.vfs.filesystem import VirtualFilesystem


def _rows(
    name: str,
    field: int,
    sep: str | None,
    state: ShellState,
    vfs: Filesystem,
    io: IOContext,
) -> list[tuple[str, list[str]]] | None:
    """Read one input as (join key, fields) pairs, or None after an error."""
    if name == "-":
        text = io.stdin.read()
    else:
        path = vfs.resolve(name, state.cwd)
        try:
            text = vfs.read(path).decode("utf-8", errors="replace")
        except FileNotFoundError:
            io.stderr.write(f"join: {name}: No such file or directory\n")
            return None
        except IsADirectoryError:
            io.stderr.write(f"join: {name}: Is a directory\n")
            return None
        except OSError as error:
            io.stderr.write(f"join: {name}: {error.strerror or error}\n")
            return None
    rows: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        cols = line.split() if sep is None else line.split(sep)
        if not cols:
            continue
        key = cols[field - 1] if field <= len(cols) else ""
        rows.append((key, cols))
    return rows


def _options(
    args: list[str], io: IOContext
) -> tuple[str | None, list[int], set[str], list[str]] | None:
    """Parse the options, or write the error and return None."""
    args = split_flags(args, "a", "t12")
    sep: str | None = None
    keys = [1, 1]
    unpaired: set[str] = set()
    names: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-t", "-1", "-2", "-a") and i + 1 < len(args):
            i += 1
            value = args[i]
            if arg == "-t":
                sep = value
            elif arg == "-a":
                if value not in ("1", "2"):
                    io.stderr.write(f"join: invalid file number: {value}\n")
                    return None
                unpaired.add(value)
            else:
                try:
                    number = int(value)
                except ValueError:
                    number = 0
                if number < 1:
                    io.stderr.write(f"join: invalid field number: {value}\n")
                    return None
                keys[0 if arg == "-1" else 1] = number
        elif arg.startswith("-") and arg != "-":
            io.stderr.write(f"join: invalid option: {arg}\n")
            return None
        else:
            names.append(arg)
        i += 1
    return sep, keys, unpaired, names


@command("join")
def cmd_join(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    parsed = _options(args, io)
    if parsed is None:
        return CommandResult(exit_code=1)
    sep, keys, unpaired, names = parsed

    if len(names) != 2:
        io.stderr.write(
            "join: usage: join [-t SEP] [-1 N] [-2 N] [-a 1|2] FILE1 FILE2\n"
        )
        return CommandResult(exit_code=1)

    left = _rows(names[0], keys[0], sep, state, vfs, io)
    right = _rows(names[1], keys[1], sep, state, vfs, io)
    if left is None or right is None:
        return CommandResult(exit_code=1)

    separator = " " if sep is None else sep
    matched: set[str] = set()
    for key, left_fields in left:
        partners = [cols for other_key, cols in right if other_key == key]
        if partners:
            matched.add(key)
            for right_fields in partners:
                joined = (
                    left_fields + right_fields[: keys[1] - 1] + right_fields[keys[1] :]
                )
                io.stdout.write(separator.join(joined) + "\n")
        elif "1" in unpaired:
            io.stdout.write(separator.join(left_fields) + "\n")

    if "2" in unpaired:
        for key, right_fields in right:
            if key not in matched:
                io.stdout.write(separator.join(right_fields) + "\n")

    return CommandResult(exit_code=0)


print("registered:", COMMANDS["join"] is cmd_join)

state = ShellState()
state.cwd = "/"
vfs = VirtualFilesystem(
    initial_files={
        "/left.txt": "1 alpha\n2 beta\n3 gamma\n",
        "/right.txt": "1 one\n3 three\n4 four\n",
    }
)

ctx = IOContext()
result = cmd_join(["left.txt", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")
print("exit code:", result.exit_code)

ctx = IOContext()
cmd_join(["-a", "1", "-a", "2", "left.txt", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")

ctx = IOContext()
ctx.stdin = StringIO("1 uno\n")
cmd_join(["-", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")

ctx = IOContext()
result = cmd_join(["missing.txt", "right.txt"], state, vfs, ctx)
print(ctx.stderr.getvalue(), end="")
print("exit code:", result.exit_code)
