"""Additional text processing commands.

fold, expand, cmp, split, od, tsort, factor, egrep, fgrep, hd.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.commands._io import read_binary_inputs, read_text_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ---------------------------------------------------------------------------
# fold
# ---------------------------------------------------------------------------


@command("fold")
def cmd_fold(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    width = 80
    break_spaces = False
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-s":
            break_spaces = True
        elif a == "-w" and i + 1 < len(args):
            i += 1
            width = int(args[i])
        elif a.startswith("-w") and len(a) > 2:
            width = int(a[2:])
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "fold")

    for line in text.splitlines():
        if len(line) <= width:
            io.stdout.write(line + "\n")
            continue
        if break_spaces:
            _fold_spaces(line, width, io)
        else:
            # Hard wrap at exactly width characters
            pos = 0
            while pos < len(line):
                io.stdout.write(line[pos : pos + width] + "\n")
                pos += width
    return CommandResult(exit_code=exit_code)


def _fold_spaces(line: str, width: int, io: IOContext) -> None:
    """Wrap *line* at spaces, breaking before *width* when possible."""
    pos = 0
    while pos < len(line):
        if len(line) - pos <= width:
            io.stdout.write(line[pos:] + "\n")
            break
        # Find the last space within the width window
        segment = line[pos : pos + width]
        last_space = segment.rfind(" ")
        if last_space == -1:
            # No space found — hard break
            io.stdout.write(segment + "\n")
            pos += width
        else:
            io.stdout.write(line[pos : pos + last_space + 1] + "\n")
            pos += last_space + 1


# ---------------------------------------------------------------------------
# expand
# ---------------------------------------------------------------------------


@command("expand")
def cmd_expand(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    tab_size = 8
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-t" and i + 1 < len(args):
            i += 1
            tab_size = int(args[i])
        elif a.startswith("-t") and len(a) > 2:
            tab_size = int(a[2:])
        else:
            files.append(a)
        i += 1

    text, exit_code = read_text_inputs(files, state, vfs, io, "expand")

    for line in text.splitlines():
        expanded = line.expandtabs(tab_size)
        io.stdout.write(expanded + "\n")

    return CommandResult(exit_code=exit_code)


# ---------------------------------------------------------------------------
# cmp
# ---------------------------------------------------------------------------


@command("cmp")
def cmd_cmp(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    verbose = False
    silent = False
    files: list[str] = []

    for a in args:
        if a == "-l":
            verbose = True
        elif a == "-s":
            silent = True
        else:
            files.append(a)

    if len(files) < 2:
        io.stderr.write("cmp: missing operand\n")
        return CommandResult(exit_code=2)

    pairs1 = read_binary_inputs([files[0]], state, vfs, io, "cmp")
    pairs2 = read_binary_inputs([files[1]], state, vfs, io, "cmp")

    data1 = pairs1[0][1]
    data2 = pairs2[0][1]

    if data1 is None or data2 is None:
        return CommandResult(exit_code=2)

    if data1 == data2:
        return CommandResult(exit_code=0)

    if silent:
        return CommandResult(exit_code=1)

    if verbose:
        # -l: print all differing bytes
        max_len = max(len(data1), len(data2))
        for offset in range(max_len):
            b1 = data1[offset] if offset < len(data1) else -1
            b2 = data2[offset] if offset < len(data2) else -1
            if b1 != b2:
                io.stdout.write(f"{offset + 1} {b1:3o} {b2:3o}\n")
    else:
        # Report first difference
        for offset in range(min(len(data1), len(data2))):
            if data1[offset] != data2[offset]:
                io.stdout.write(
                    f"{files[0]} {files[1]} differ: byte {offset + 1}, "
                    f"line {data1[: offset + 1].count(10) + 1}\n"
                )
                return CommandResult(exit_code=1)
        # One file is shorter
        shorter = files[0] if len(data1) < len(data2) else files[1]
        io.stderr.write(f"cmp: EOF on {shorter}\n")

    return CommandResult(exit_code=1)


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


@command("split")
def cmd_split(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    line_count: int | None = None
    byte_count: int | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-l" and i + 1 < len(args):
            i += 1
            line_count = int(args[i])
        elif a == "-b" and i + 1 < len(args):
            i += 1
            byte_count = int(args[i])
        else:
            files.append(a)
        i += 1

    # Default: split by lines
    if line_count is None and byte_count is None:
        line_count = 1000

    input_file = files[0] if files else "-"
    prefix = files[1] if len(files) > 1 else "x"

    if byte_count is not None:
        # Split by bytes
        pairs = read_binary_inputs([input_file], state, vfs, io, "split")
        data = pairs[0][1]
        if data is None:
            return CommandResult(exit_code=1)
        chunk_idx = 0
        pos = 0
        while pos < len(data):
            suffix = _split_suffix(chunk_idx)
            chunk = data[pos : pos + byte_count]
            out_path = vfs.resolve(prefix + suffix, state.cwd)
            vfs.write(out_path, chunk)
            pos += byte_count
            chunk_idx += 1
    else:
        assert line_count is not None
        text, exit_code = read_text_inputs([input_file], state, vfs, io, "split")
        if exit_code != 0:
            return CommandResult(exit_code=exit_code)
        lines = text.splitlines(keepends=True)
        chunk_idx = 0
        pos = 0
        while pos < len(lines):
            suffix = _split_suffix(chunk_idx)
            chunk_lines = lines[pos : pos + line_count]
            out_path = vfs.resolve(prefix + suffix, state.cwd)
            vfs.write(out_path, "".join(chunk_lines).encode("utf-8"))
            pos += line_count
            chunk_idx += 1

    return CommandResult(exit_code=0)


def _split_suffix(index: int) -> str:
    """Generate aa, ab, ac, ... az, ba, bb, ... style suffix."""
    first = index // 26
    second = index % 26
    return chr(ord("a") + first) + chr(ord("a") + second)


# ---------------------------------------------------------------------------
# od
# ---------------------------------------------------------------------------


@command("od")
def cmd_od(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    addr_radix = "o"  # default octal addresses
    type_spec = "oS"  # default octal short (words)
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-A" and i + 1 < len(args):
            i += 1
            addr_radix = args[i]
        elif a == "-t" and i + 1 < len(args):
            i += 1
            type_spec = args[i]
        else:
            files.append(a)
        i += 1

    for _fname, data in read_binary_inputs(files, state, vfs, io, "od"):
        if data is None:
            continue
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + 16]
            addr = _format_addr(offset, addr_radix)
            values = _format_od_values(chunk, type_spec)
            io.stdout.write(f"{addr} {values}\n")
            offset += 16
        # Final address line
        io.stdout.write(f"{_format_addr(len(data), addr_radix)}\n")

    return CommandResult(exit_code=0)


def _format_addr(offset: int, radix: str) -> str:
    """Format an address in the given radix."""
    if radix == "x":
        return f"{offset:07x}"
    if radix == "d":
        return f"{offset:07d}"
    if radix == "n":
        return ""
    # default octal
    return f"{offset:07o}"


def _format_od_values(chunk: bytes, type_spec: str) -> str:
    """Format a chunk of bytes according to *type_spec*."""
    if type_spec == "x1":
        # hex bytes
        return " ".join(f"{b:02x}" for b in chunk)
    if type_spec == "d1":
        # decimal bytes
        return " ".join(f"{b:3d}" for b in chunk)
    if type_spec == "c":
        # characters
        parts: list[str] = []
        for b in chunk:
            if b == ord("\n"):
                parts.append(" \\n")
            elif b == ord("\t"):
                parts.append(" \\t")
            elif b == ord("\0"):
                parts.append(" \\0")
            elif 32 <= b < 127:
                parts.append(f"  {chr(b)}")
            else:
                parts.append(f"{b:03o}")
            parts.append(" ")
        return "".join(parts).rstrip()
    # Default: octal words (2-byte groups, little-endian)
    parts_list: list[str] = []
    j = 0
    while j < len(chunk):
        if j + 1 < len(chunk):
            word = chunk[j] | (chunk[j + 1] << 8)
            parts_list.append(f"{word:06o}")
            j += 2
        else:
            parts_list.append(f"{chunk[j]:06o}")
            j += 1
    return " ".join(parts_list)


# ---------------------------------------------------------------------------
# tsort
# ---------------------------------------------------------------------------


@command("tsort")
def cmd_tsort(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    text, exit_code = read_text_inputs(files, state, vfs, io, "tsort")
    if exit_code != 0:
        return CommandResult(exit_code=exit_code)

    tokens = text.split()
    if len(tokens) % 2 != 0:
        io.stderr.write("tsort: odd number of tokens\n")
        return CommandResult(exit_code=1)

    # Build adjacency list
    graph: dict[str, set[str]] = {}
    in_degree: dict[str, int] = {}

    for j in range(0, len(tokens), 2):
        u, v = tokens[j], tokens[j + 1]
        for node in (u, v):
            if node not in graph:
                graph[node] = set()
                in_degree[node] = 0

    for j in range(0, len(tokens), 2):
        u, v = tokens[j], tokens[j + 1]
        if u == v:
            continue
        if v not in graph[u]:
            graph[u].add(v)
            in_degree[v] += 1

    # Kahn's algorithm
    queue = sorted([n for n in graph if in_degree[n] == 0])
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for neighbor in sorted(graph[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort()

    if len(result) != len(graph):
        io.stderr.write("tsort: input contains a loop\n")
        # Output what we have plus remaining
        remaining = sorted(set(graph) - set(result))
        result.extend(remaining)

    for item in result:
        io.stdout.write(item + "\n")

    return CommandResult(exit_code=0 if len(result) == len(graph) else 1)


# ---------------------------------------------------------------------------
# factor
# ---------------------------------------------------------------------------


@command("factor")
def cmd_factor(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    numbers: list[str] = [a for a in args if not a.startswith("-")]

    if not numbers:
        # Read from stdin
        text = io.stdin.read()
        numbers = text.split()

    exit_code = 0
    for num_str in numbers:
        try:
            n = int(num_str)
        except ValueError:
            io.stderr.write(f"factor: '{num_str}' is not a valid number\n")
            exit_code = 1
            continue
        if n < 2:
            io.stdout.write(f"{n}:\n")
            continue
        factors = _prime_factors(n)
        io.stdout.write(f"{n}: {' '.join(str(f) for f in factors)}\n")

    return CommandResult(exit_code=exit_code)


def _prime_factors(n: int) -> list[int]:
    """Return the prime factorisation of *n*."""
    factors: list[int] = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            factors.append(d)
            n //= d
        d += 1
    if n > 1:
        factors.append(n)
    return factors


# ---------------------------------------------------------------------------
# egrep / fgrep — aliases for grep with -E / -F
# ---------------------------------------------------------------------------


@command("egrep")
def cmd_egrep(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    from agentsh.commands.search import cmd_grep

    return cmd_grep(["-E", *args], state, vfs, io)


@command("fgrep")
def cmd_fgrep(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    from agentsh.commands.search import cmd_grep

    return cmd_grep(["-F", *args], state, vfs, io)


# ---------------------------------------------------------------------------
# hd — alias for hexdump -C
# ---------------------------------------------------------------------------


@command("hd")
def cmd_hd(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    from agentsh.commands.encoding import cmd_hexdump

    return cmd_hexdump(["-C", *args], state, vfs, io)
