"""File I/O commands: cat, head, tail, tee, touch, mkdir, cp, mv, rm, ln."""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING

from spelaion.commands._io import read_text, split_flags
from spelaion.commands._registry import command
from spelaion.runtime.result import CommandResult

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem


@command("cat")
def cmd_cat(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    number_lines = False
    files: list[str] = []
    for a in args:
        if a == "-n":
            number_lines = True
        elif a == "--":
            continue
        else:
            files.append(a)

    if not files:
        files = ["-"]

    exit_code = 0
    line_num = 1
    for f in files:
        content = read_text(f, state, vfs, io, "cat")
        if content is None:
            exit_code = 1
            continue
        if number_lines:
            for line in content.splitlines(keepends=True):
                io.stdout.write(f"     {line_num}\t{line}")
                line_num += 1
            if content and not content.endswith("\n"):
                io.stdout.write("\n")
        else:
            io.stdout.write(content)

    return CommandResult(exit_code=exit_code)


@command("head")
def cmd_head(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    n = 10
    files: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            try:
                n = int(args[i + 1])
            except ValueError:
                io.stderr.write(f"head: invalid number of lines: {args[i + 1]!r}\n")
                return CommandResult(exit_code=1)
            i += 2
        elif args[i].startswith("-") and args[i][1:].isdigit():
            n = int(args[i][1:])
            i += 1
        else:
            files.append(args[i])
            i += 1

    if not files:
        files = ["-"]

    exit_code = 0
    first = True
    for f in files:
        content = read_text(f, state, vfs, io, "head")
        if content is None:
            exit_code = 1
            continue
        if len(files) > 1:
            first = _header(f, first, io)
        lines = content.splitlines(keepends=True)
        io.stdout.write("".join(lines[:n]))

    return CommandResult(exit_code=exit_code)


@command("tail")
def cmd_tail(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    n = 10
    from_start = False
    files: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            val = args[i + 1]
            if val.startswith("+"):
                from_start = True
                n = int(val[1:])
            else:
                n = int(val)
            i += 2
        elif args[i].startswith("-") and args[i][1:].isdigit():
            n = int(args[i][1:])
            i += 1
        else:
            files.append(args[i])
            i += 1

    if not files:
        files = ["-"]

    exit_code = 0
    first = True
    for f in files:
        content = read_text(f, state, vfs, io, "tail")
        if content is None:
            exit_code = 1
            continue
        if len(files) > 1:
            first = _header(f, first, io)
        lines = content.splitlines(keepends=True)
        if from_start:
            # +N means starting from line N (1-indexed)
            io.stdout.write("".join(lines[max(n - 1, 0) :]))
        elif n > 0:
            io.stdout.write("".join(lines[-n:]))

    return CommandResult(exit_code=exit_code)


def _header(name: str, first: bool, io: IOContext) -> bool:
    """GNU's ``==> name <==`` line before each of several files."""
    shown = "standard input" if name == "-" else name
    io.stdout.write(("" if first else "\n") + f"==> {shown} <==\n")
    return False


@command("tee")
def cmd_tee(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    append = False
    files: list[str] = []
    for a in args:
        if a == "-a":
            append = True
        else:
            files.append(a)

    content = io.stdin.read()
    io.stdout.write(content)

    data = content.encode("utf-8")
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        vfs.write(abs_path, data, append=append)

    return CommandResult(exit_code=0)


@command("touch")
def cmd_touch(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    for f in args:
        abs_path = vfs.resolve(f, state.cwd)
        if not vfs.exists(abs_path):
            vfs.write(abs_path, b"")
    return CommandResult(exit_code=0)


@command("mkdir")
def cmd_mkdir(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    parents = False
    dirs: list[str] = []
    for a in args:
        if a == "-p":
            parents = True
        else:
            dirs.append(a)

    exit_code = 0
    for d in dirs:
        abs_path = vfs.resolve(d, state.cwd)
        try:
            vfs.mkdir(abs_path, parents=parents)
        except FileExistsError:
            if not parents:
                io.stderr.write(f"mkdir: cannot create directory '{d}': File exists\n")
                exit_code = 1
        except FileNotFoundError:
            io.stderr.write(
                f"mkdir: cannot create directory '{d}': No such file or directory\n"
            )
            exit_code = 1

    return CommandResult(exit_code=exit_code)


@command("cp")
def cmd_cp(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    recursive = False
    paths: list[str] = []
    for a in split_flags(args, "rRafpv"):
        if a in ("-r", "-R", "-a", "--recursive", "--archive"):
            recursive = True
        elif a in ("-f", "-p", "-v", "--force"):
            pass
        else:
            paths.append(a)

    if len(paths) < 2:
        io.stderr.write("cp: missing file operand\n")
        return CommandResult(exit_code=1)

    dst = vfs.resolve(paths[-1], state.cwd)
    sources = paths[:-1]
    into = vfs.is_dir(dst)
    if len(sources) > 1 and not into:
        io.stderr.write(f"cp: target '{paths[-1]}' is not a directory\n")
        return CommandResult(exit_code=1)

    exit_code = 0
    for src_arg in sources:
        src = vfs.resolve(src_arg, state.cwd)
        target = dst.rstrip("/") + "/" + posixpath.basename(src) if into else dst
        named = (
            paths[-1].rstrip("/") + "/" + posixpath.basename(src) if into else paths[-1]
        )
        if not vfs.exists(src):
            io.stderr.write(f"cp: cannot stat '{src_arg}': No such file or directory\n")
            exit_code = 1
        elif not vfs.is_dir(src):
            exit_code |= _cp_file(src_arg, src, target, vfs, io)
        elif not recursive:
            io.stderr.write(f"cp: -r not specified; omitting directory '{src_arg}'\n")
            exit_code = 1
        else:
            exit_code |= _cp_tree(src_arg, src, target, named, vfs, io)

    return CommandResult(exit_code=exit_code)


def _cp_file(shown: str, src: str, dst: str, vfs: Filesystem, io: IOContext) -> int:
    try:
        vfs.write(dst, vfs.read(src))
    except OSError as e:
        io.stderr.write(f"cp: cannot copy '{shown}': {e.strerror or e}\n")
        return 1
    return 0


def _cp_tree(
    shown: str, src: str, dst: str, dst_arg: str, vfs: Filesystem, io: IOContext
) -> int:
    """Copy folder *src* to *dst*, file by file, going on past a failed one.

    The tree is listed before anything is written, so a destination inside
    the source gets the source as it was and is not copied into itself.
    """
    inside = dst == src or dst.startswith(src.rstrip("/") + "/")
    folders: list[str] = []
    files: list[str] = []
    for dirpath, _dirnames, filenames in vfs.walk(src):
        rel = dirpath[len(src) :]
        if inside and (src.rstrip("/") + rel + "/").startswith(dst.rstrip("/") + "/"):
            continue
        folders.append(rel)
        files.extend(rel + "/" + f for f in filenames)
    rc = 0
    try:
        for rel in folders:
            if not vfs.is_dir(dst + rel):
                vfs.mkdir(dst + rel, parents=True)
    except OSError as e:
        io.stderr.write(f"cp: cannot create directory '{dst_arg}': {e.strerror or e}\n")
        return 1
    for rel in files:
        rc |= _cp_file(shown.rstrip("/") + rel, src + rel, dst + rel, vfs, io)
    if inside:
        io.stderr.write(
            f"cp: cannot copy a directory, '{shown}', into itself, '{dst_arg}'\n"
        )
        rc = 1
    return rc


@command("mv")
def cmd_mv(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    paths: list[str] = [a for a in args if not a.startswith("-")]

    if len(paths) < 2:
        io.stderr.write("mv: missing file operand\n")
        return CommandResult(exit_code=1)

    dst = vfs.resolve(paths[-1], state.cwd)
    sources = paths[:-1]

    exit_code = 0
    for src_arg in sources:
        src = vfs.resolve(src_arg, state.cwd)
        try:
            vfs.rename(src, dst)
        except FileNotFoundError:
            io.stderr.write(f"mv: cannot stat '{src_arg}': No such file or directory\n")
            exit_code = 1

    return CommandResult(exit_code=exit_code)


@command("rm")
def cmd_rm(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    recursive = False
    force = False
    files: list[str] = []
    for a in args:
        if a in ("-r", "-R", "--recursive"):
            recursive = True
        elif a in ("-f", "--force"):
            force = True
        elif a.startswith("-") and len(a) > 1 and not a.startswith("--"):
            # Handle combined flags like -rf, -fr, -rRf, etc.
            for ch in a[1:]:
                if ch in ("r", "R"):
                    recursive = True
                elif ch == "f":
                    force = True
        else:
            files.append(a)

    exit_code = 0
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        if not vfs.exists(abs_path):
            if not force:
                io.stderr.write(f"rm: cannot remove '{f}': No such file or directory\n")
                exit_code = 1
            continue
        try:
            if vfs.is_dir(abs_path):
                if not recursive:
                    io.stderr.write(f"rm: cannot remove '{f}': Is a directory\n")
                    exit_code = 1
                    continue
                vfs.rmtree(abs_path)
            else:
                vfs.unlink(abs_path)
        except (FileNotFoundError, OSError) as e:
            if not force:
                io.stderr.write(f"rm: cannot remove '{f}': {e}\n")
                exit_code = 1

    return CommandResult(exit_code=exit_code)


@command("ln")
def cmd_ln(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    io.stderr.write("ln: links are not supported in the sandbox\n")
    return CommandResult(exit_code=1)
