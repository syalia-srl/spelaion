"""File I/O commands: cat, head, tail, tee, touch, mkdir, cp, mv, rm, ln."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentsh.commands._io import read_text
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


@command("cat")
def cmd_cat(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    for f in files:
        content = read_text(f, state, vfs, io, "head")
        if content is None:
            exit_code = 1
            continue
        lines = content.splitlines(keepends=True)
        io.stdout.write("".join(lines[:n]))

    return CommandResult(exit_code=exit_code)


@command("tail")
def cmd_tail(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
        else:
            files.append(args[i])
            i += 1

    if not files:
        files = ["-"]

    exit_code = 0
    for f in files:
        content = read_text(f, state, vfs, io, "tail")
        if content is None:
            exit_code = 1
            continue
        lines = content.splitlines(keepends=True)
        if from_start:
            # +N means starting from line N (1-indexed)
            io.stdout.write("".join(lines[n - 1 :]))
        else:
            io.stdout.write("".join(lines[-n:]) if lines else "")

    return CommandResult(exit_code=exit_code)


@command("tee")
def cmd_tee(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    for f in args:
        abs_path = vfs.resolve(f, state.cwd)
        if not vfs.exists(abs_path):
            vfs.write(abs_path, b"")
    return CommandResult(exit_code=0)


@command("mkdir")
def cmd_mkdir(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    recursive = False
    paths: list[str] = []
    for a in args:
        if a in ("-r", "-R", "--recursive"):
            recursive = True
        else:
            paths.append(a)

    if len(paths) < 2:
        io.stderr.write("cp: missing file operand\n")
        return CommandResult(exit_code=1)

    dst = vfs.resolve(paths[-1], state.cwd)
    sources = paths[:-1]

    exit_code = 0
    for src_arg in sources:
        src = vfs.resolve(src_arg, state.cwd)
        try:
            if vfs.is_dir(src):
                if not recursive:
                    io.stderr.write(
                        f"cp: -r not specified; omitting directory '{src_arg}'\n"
                    )
                    exit_code = 1
                    continue
                vfs.copy_tree(src, dst)
            else:
                vfs.copy_file(src, dst)
        except FileNotFoundError:
            io.stderr.write(f"cp: cannot stat '{src_arg}': No such file or directory\n")
            exit_code = 1

    return CommandResult(exit_code=exit_code)


@command("mv")
def cmd_mv(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
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
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    # VFS has no real symlinks; -s creates a copy as a fallback.
    paths: list[str] = [a for a in args if not a.startswith("-")]

    if len(paths) < 2:
        io.stderr.write("ln: missing file operand\n")
        return CommandResult(exit_code=1)

    src = vfs.resolve(paths[0], state.cwd)
    dst = vfs.resolve(paths[1], state.cwd)
    try:
        vfs.copy_file(src, dst)
    except FileNotFoundError:
        io.stderr.write(
            f"ln: cannot create link '{paths[1]}': No such file or directory\n"
        )
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)
