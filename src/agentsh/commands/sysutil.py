"""System utility commands.

seq, sleep, env, which, date, uname, whoami, id, yes, mktemp, comm.
"""

from __future__ import annotations

import datetime
import uuid
from typing import TYPE_CHECKING

from agentsh.commands._io import read_text
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("seq")
def cmd_seq(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    separator = "\n"
    pad_width = False
    positional: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-s" and i + 1 < len(args):
            i += 1
            separator = args[i]
        elif a == "-w":
            pad_width = True
        else:
            positional.append(a)
        i += 1

    if not positional:
        io.stderr.write("seq: missing operand\n")
        return CommandResult(exit_code=1)

    # Parse as float (superset of int) to avoid nested try/except
    try:
        if len(positional) == 1:
            first_f, inc_f, last_f = 1.0, 1.0, float(positional[0])
        elif len(positional) == 2:
            first_f = float(positional[0])
            inc_f = 1.0
            last_f = float(positional[1])
        else:
            first_f = float(positional[0])
            inc_f = float(positional[1])
            last_f = float(positional[2])
    except ValueError:
        io.stderr.write("seq: invalid argument\n")
        return CommandResult(exit_code=1)

    is_int = all(f == int(f) for f in (first_f, inc_f, last_f))
    if inc_f == 0:
        io.stderr.write("seq: zero increment\n")
        return CommandResult(exit_code=1)

    nums: list[str] = []
    val = first_f
    while (inc_f > 0 and val <= last_f) or (inc_f < 0 and val >= last_f):
        nums.append(str(int(val)) if is_int else str(val))
        val += inc_f

    if pad_width and nums:
        width = max(len(s) for s in nums)
        nums = [s.zfill(width) for s in nums]

    io.stdout.write(separator.join(nums) + "\n")
    return CommandResult(exit_code=0)


@command("sleep")
def cmd_sleep(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    # Virtual no-op — returns immediately
    return CommandResult(exit_code=0)


@command("env")
def cmd_env(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    unset_names: set[str] = set()
    i = 0
    while i < len(args):
        if args[i] == "-u" and i + 1 < len(args):
            i += 1
            unset_names.add(args[i])
        i += 1

    for name, value in sorted(state.exported_env.items()):
        if name not in unset_names:
            io.stdout.write(f"{name}={value}\n")

    return CommandResult(exit_code=0)


@command("which")
def cmd_which(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    from agentsh.commands._registry import COMMANDS
    from agentsh.exec.builtins import BUILTINS

    exit_code = 0
    for name in args:
        if name in state.functions:
            io.stdout.write(f"{name}: shell function\n")
        elif name in BUILTINS:
            io.stdout.write(f"{name}: shell builtin\n")
        elif name in COMMANDS:
            io.stdout.write(f"{name}: virtual command\n")
        else:
            io.stderr.write(f"which: no {name} in virtual shell\n")
            exit_code = 1

    return CommandResult(exit_code=exit_code)


@command("date")
def cmd_date(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    # Check for overridable date via $AGENTSH_DATE
    override = state.get_var("AGENTSH_DATE")
    if override:
        io.stdout.write(override + "\n")
        return CommandResult(exit_code=0)

    now = datetime.datetime.now()
    fmt: str | None = None
    for a in args:
        if a.startswith("+"):
            fmt = a[1:]

    if fmt:
        try:
            io.stdout.write(now.strftime(fmt) + "\n")
        except ValueError:
            io.stdout.write(now.isoformat() + "\n")
    else:
        io.stdout.write(now.strftime("%a %b %d %H:%M:%S %Z %Y").strip() + "\n")

    return CommandResult(exit_code=0)


@command("uname")
def cmd_uname(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    sysname = "VirtualOS"
    nodename = "agentsh"
    release = "1.0.0"
    machine = "virtual"

    if not args:
        io.stdout.write(sysname + "\n")
        return CommandResult(exit_code=0)

    parts: list[str] = []
    for a in args:
        if a == "-a":
            parts = [sysname, nodename, release, machine]
            break
        if a == "-s":
            parts.append(sysname)
        elif a == "-n":
            parts.append(nodename)
        elif a == "-r":
            parts.append(release)
        elif a == "-m":
            parts.append(machine)

    io.stdout.write(" ".join(parts) + "\n")
    return CommandResult(exit_code=0)


@command("whoami")
def cmd_whoami(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    io.stdout.write(user + "\n")
    return CommandResult(exit_code=0)


@command("id")
def cmd_id(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    uid = 0 if user == "root" else 1000
    gid = uid
    io.stdout.write(f"uid={uid}({user}) gid={gid}({user})\n")
    return CommandResult(exit_code=0)


@command("yes")
def cmd_yes(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    text = " ".join(args) if args else "y"
    # Policy iteration limit to prevent infinite output
    max_iter = 10000
    for _ in range(max_iter):
        io.stdout.write(text + "\n")
    return CommandResult(exit_code=0)


@command("mktemp")
def cmd_mktemp(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    make_dir = False
    parent_dir: str | None = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-d":
            make_dir = True
        elif a == "-p" and i + 1 < len(args):
            i += 1
            parent_dir = args[i]
        i += 1

    base = parent_dir or "/tmp"
    abs_base = vfs.resolve(base, state.cwd)
    suffix = uuid.uuid4().hex[:8]
    name = f"tmp.{suffix}"
    path = abs_base.rstrip("/") + "/" + name

    if make_dir:
        vfs.mkdir(path, parents=True)
    else:
        # Ensure parent exists
        if not vfs.exists(abs_base):
            vfs.mkdir(abs_base, parents=True)
        vfs.write(path, b"")

    io.stdout.write(path + "\n")
    return CommandResult(exit_code=0)


@command("comm")
def cmd_comm(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    suppress: set[int] = set()
    files: list[str] = []

    for a in args:
        if a.startswith("-") and len(a) > 1 and a[1:].isdigit():
            for ch in a[1:]:
                suppress.add(int(ch))
        else:
            files.append(a)

    if len(files) < 2:
        io.stderr.write("comm: missing operand\n")
        return CommandResult(exit_code=1)

    content1 = read_text(files[0], state, vfs, io, "comm")
    content2 = read_text(files[1], state, vfs, io, "comm")
    lines1 = content1.splitlines() if content1 else []
    lines2 = content2.splitlines() if content2 else []

    i, j = 0, 0
    while i < len(lines1) and j < len(lines2):
        if lines1[i] < lines2[j]:
            if 1 not in suppress:
                io.stdout.write(lines1[i] + "\n")
            i += 1
        elif lines1[i] > lines2[j]:
            if 2 not in suppress:
                prefix = "" if 1 in suppress else "\t"
                io.stdout.write(prefix + lines2[j] + "\n")
            j += 1
        else:
            if 3 not in suppress:
                prefix = ""
                if 1 not in suppress:
                    prefix += "\t"
                if 2 not in suppress:
                    prefix += "\t"
                io.stdout.write(prefix + lines1[i] + "\n")
            i += 1
            j += 1

    while i < len(lines1):
        if 1 not in suppress:
            io.stdout.write(lines1[i] + "\n")
        i += 1

    while j < len(lines2):
        if 2 not in suppress:
            prefix = "" if 1 in suppress else "\t"
            io.stdout.write(prefix + lines2[j] + "\n")
        j += 1

    return CommandResult(exit_code=0)
