"""Encoding commands: base64, md5sum, sha256sum, hexdump/xxd, strings."""

from __future__ import annotations

import base64 as _base64
import hashlib
from typing import TYPE_CHECKING

from agentsh.commands._io import read_binary_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("base64")
def cmd_base64(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    decode = False
    wrap = 76
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-d", "--decode"):
            decode = True
        elif a == "-w" and i + 1 < len(args):
            i += 1
            wrap = int(args[i])
        else:
            files.append(a)
        i += 1

    for _fname, data in read_binary_inputs(files, state, vfs, io, "base64"):
        if data is None:
            continue
        if decode:
            try:
                decoded = _base64.b64decode(data)
                io.stdout.write(decoded.decode("utf-8", errors="replace"))
            except (ValueError, Exception):
                io.stderr.write("base64: invalid input\n")
                return CommandResult(exit_code=1)
        else:
            encoded = _base64.b64encode(data).decode("ascii")
            if wrap > 0:
                lines = [encoded[i : i + wrap] for i in range(0, len(encoded), wrap)]
                io.stdout.write("\n".join(lines) + "\n")
            else:
                io.stdout.write(encoded + "\n")

    return CommandResult(exit_code=0)


@command("md5sum")
def cmd_md5sum(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    for fname, data in read_binary_inputs(files, state, vfs, io, "md5sum"):
        if data is None:
            continue
        digest = hashlib.md5(data).hexdigest()
        io.stdout.write(f"{digest}  {fname}\n")
    return CommandResult(exit_code=0)


@command("sha256sum")
def cmd_sha256sum(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    for fname, data in read_binary_inputs(files, state, vfs, io, "sha256sum"):
        if data is None:
            continue
        digest = hashlib.sha256(data).hexdigest()
        io.stdout.write(f"{digest}  {fname}\n")
    return CommandResult(exit_code=0)


@command("hexdump", "xxd")
def cmd_hexdump(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    canonical = False
    files: list[str] = []
    for a in args:
        if a == "-C":
            canonical = True
        else:
            files.append(a)

    for _fname, data in read_binary_inputs(files, state, vfs, io, "hexdump"):
        if data is None:
            continue
        offset = 0
        while offset < len(data):
            chunk = data[offset : offset + 16]
            hex_parts = " ".join(f"{b:02x}" for b in chunk)
            if canonical:
                ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
                io.stdout.write(f"{offset:08x}  {hex_parts:<48s}  |{ascii_part}|\n")
            else:
                io.stdout.write(f"{offset:08x}  {hex_parts}\n")
            offset += 16

    return CommandResult(exit_code=0)


@command("strings")
def cmd_strings(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    min_len = 4
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-n" and i + 1 < len(args):
            i += 1
            min_len = int(args[i])
        else:
            files.append(a)
        i += 1

    for _fname, data in read_binary_inputs(files, state, vfs, io, "strings"):
        if data is None:
            continue
        current: list[str] = []
        for byte in data:
            if 32 <= byte < 127:
                current.append(chr(byte))
            else:
                if len(current) >= min_len:
                    io.stdout.write("".join(current) + "\n")
                current = []
        if len(current) >= min_len:
            io.stdout.write("".join(current) + "\n")

    return CommandResult(exit_code=0)
