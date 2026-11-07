"""Path utility commands: ls, basename, dirname, readlink, realpath."""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING

from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("ls")
def cmd_ls(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    long_fmt = False
    show_all = False
    one_per_line = False
    recursive = False
    paths: list[str] = []

    for a in args:
        if a.startswith("-") and len(a) > 1 and not a.startswith("--"):
            for ch in a[1:]:
                if ch == "l":
                    long_fmt = True
                elif ch == "a":
                    show_all = True
                elif ch == "1":
                    one_per_line = True
                elif ch == "R":
                    recursive = True
        else:
            paths.append(a)

    if not paths:
        paths = ["."]

    exit_code = 0
    show_header = len(paths) > 1 or recursive

    for idx, p in enumerate(paths):
        abs_path = vfs.resolve(p, state.cwd)
        if not vfs.exists(abs_path):
            io.stderr.write(f"ls: cannot access '{p}': No such file or directory\n")
            exit_code = 2
            continue

        if vfs.is_file(abs_path):
            _ls_print_entry(abs_path, posixpath.basename(abs_path), long_fmt, vfs, io)
            continue

        if show_header:
            if idx > 0:
                io.stdout.write("\n")
            io.stdout.write(f"{p}:\n")

        _ls_list_dir(abs_path, long_fmt, show_all, one_per_line, vfs, io)

        if recursive:
            for dirpath, _dirnames, _filenames in vfs.walk(abs_path):
                if dirpath == abs_path:
                    continue
                rel = dirpath[len(abs_path) :].lstrip("/")
                io.stdout.write(f"\n{p}/{rel}:\n")
                _ls_list_dir(dirpath, long_fmt, show_all, one_per_line, vfs, io)

    return CommandResult(exit_code=exit_code)


def _ls_list_dir(
    abs_path: str,
    long_fmt: bool,
    show_all: bool,
    one_per_line: bool,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> None:
    try:
        entries = vfs.listdir(abs_path)
    except (FileNotFoundError, NotADirectoryError):
        return

    if not show_all:
        entries = [e for e in entries if not e.startswith(".")]

    if long_fmt:
        for name in entries:
            child_path = abs_path.rstrip("/") + "/" + name
            _ls_print_entry(child_path, name, True, vfs, io)
    elif one_per_line:
        for name in entries:
            io.stdout.write(name + "\n")
    elif entries:
        io.stdout.write("  ".join(entries) + "\n")


def _ls_print_entry(
    abs_path: str,
    name: str,
    long_fmt: bool,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> None:
    if not long_fmt:
        io.stdout.write(name + "\n")
        return

    if vfs.is_dir(abs_path):
        io.stdout.write(f"drwxr-xr-x  -  {name}\n")
    else:
        try:
            size = len(vfs.read(abs_path))
        except (FileNotFoundError, IsADirectoryError):
            size = 0
        io.stdout.write(f"-rw-r--r--  {size}  {name}\n")


@command("basename")
def cmd_basename(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("basename: missing operand\n")
        return CommandResult(exit_code=1)

    name = posixpath.basename(args[0].rstrip("/"))
    if len(args) > 1:
        suffix = args[1]
        if name.endswith(suffix) and name != suffix:
            name = name[: -len(suffix)]

    io.stdout.write(name + "\n")
    return CommandResult(exit_code=0)


@command("dirname")
def cmd_dirname(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("dirname: missing operand\n")
        return CommandResult(exit_code=1)

    io.stdout.write(posixpath.dirname(args[0]) + "\n")
    return CommandResult(exit_code=0)


@command("readlink", "realpath")
def cmd_realpath(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    paths: list[str] = [a for a in args if not a.startswith("-")]
    if not paths:
        io.stderr.write("realpath: missing operand\n")
        return CommandResult(exit_code=1)

    for p in paths:
        abs_path = vfs.resolve(p, state.cwd)
        io.stdout.write(abs_path + "\n")

    return CommandResult(exit_code=0)
