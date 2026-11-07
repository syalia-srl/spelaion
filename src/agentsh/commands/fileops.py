"""File operations commands.

chmod, chown, chgrp, rmdir, stat, du, df, cksum,
link, shred, tree, mkfifo, dd.
"""

from __future__ import annotations

import binascii
import contextlib
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult
from agentsh.vfs.nodes import DirNode, FileNode

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_NodeT = FileNode | DirNode


def _resolve_paths(
    raw: list[str], state: ShellState, vfs: VirtualFilesystem
) -> list[str]:
    """Resolve a list of raw path arguments to absolute VFS paths."""
    return [vfs.resolve(p, state.cwd) for p in raw]


def _apply_recursive(
    path: str,
    vfs: VirtualFilesystem,
    fn: Callable[[_NodeT], None],
) -> None:
    """Walk *path* recursively, calling *fn(node)* on every node."""
    node = vfs.get_node(path)
    if node is None:
        return
    fn(node)
    if isinstance(node, DirNode):
        for dirpath, dirnames, filenames in vfs.walk(path):
            for name in dirnames + filenames:
                child_path = dirpath.rstrip("/") + "/" + name
                child = vfs.get_node(child_path)
                if child is not None:
                    fn(child)


def _perm_bits(who: str, perm: str) -> int:
    """Return the octal bitmask for a single perm char and who set."""
    mapping = {
        ("u", "r"): 0o400,
        ("u", "w"): 0o200,
        ("u", "x"): 0o100,
        ("g", "r"): 0o040,
        ("g", "w"): 0o020,
        ("g", "x"): 0o010,
        ("o", "r"): 0o004,
        ("o", "w"): 0o002,
        ("o", "x"): 0o001,
    }
    bits = 0
    for w in who:
        bits |= mapping.get((w, perm), 0)
    return bits


def _parse_symbolic_mode(spec: str, current_mode: int) -> int:
    """Parse a symbolic mode string like ``+x``, ``-w``, ``u+rw``."""
    m = re.fullmatch(r"([ugoa]*)([+\-=])([rwxXst]+)", spec)
    if m is None:
        raise ValueError(f"invalid mode: {spec!r}")
    who, op, perms = m.group(1), m.group(2), m.group(3)

    if not who or who == "a":
        who = "ugo"

    bits = 0
    for ch in perms:
        if ch in ("r", "w", "x"):
            bits |= _perm_bits(who, ch)
        elif ch in ("X", "s", "t"):
            bits |= _perm_bits(who, "x")

    if op == "+":
        return current_mode | bits
    if op == "-":
        return current_mode & ~bits
    # '=' — clear relevant bits and set
    mask = 0
    if "u" in who:
        mask |= 0o700
    if "g" in who:
        mask |= 0o070
    if "o" in who:
        mask |= 0o007
    return (current_mode & ~mask) | bits


def _human_size(n: int) -> str:
    """Format byte count in human-readable form."""
    if n < 1024:
        return str(n)
    val = float(n)
    for unit in ("K", "M", "G", "T", "P"):
        val /= 1024.0
        if val < 1024.0 or unit == "P":
            return f"{val:.1f}{unit}"
    return str(n)


def _is_octal(s: str) -> bool:
    """Return True if *s* looks like an octal mode string."""
    return len(s) <= 4 and all(c in "01234567" for c in s)


# ------------------------------------------------------------------
# chmod
# ------------------------------------------------------------------


@command("chmod")
def cmd_chmod(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    recursive = False
    positional: list[str] = []
    for a in args:
        if a in ("-R", "-r", "--recursive"):
            recursive = True
        else:
            positional.append(a)

    if len(positional) < 2:
        io.stderr.write("chmod: missing operand\n")
        return CommandResult(exit_code=1)

    mode_str = positional[0]
    files = positional[1:]
    exit_code = 0

    for f_arg, f in zip(files, _resolve_paths(files, state, vfs), strict=True):
        node = vfs.get_node(f)
        if node is None:
            io.stderr.write(
                f"chmod: cannot access '{f_arg}': No such file or directory\n"
            )
            exit_code = 1
            continue

        try:
            if _is_octal(mode_str):
                new_mode = int(mode_str, 8)

                def _set_octal(n: _NodeT, m: int = new_mode) -> None:
                    n.mode = m

                if recursive and isinstance(node, DirNode):
                    _apply_recursive(f, vfs, _set_octal)
                else:
                    _set_octal(node)
            else:

                def _set_sym(n: _NodeT, spec: str = mode_str) -> None:
                    n.mode = _parse_symbolic_mode(spec, n.mode)

                if recursive and isinstance(node, DirNode):
                    _apply_recursive(f, vfs, _set_sym)
                else:
                    _set_sym(node)
        except ValueError as e:
            io.stderr.write(f"chmod: {e}\n")
            exit_code = 1

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# chown
# ------------------------------------------------------------------


@command("chown")
def cmd_chown(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    recursive = False
    positional: list[str] = []
    for a in args:
        if a in ("-R", "-r", "--recursive"):
            recursive = True
        else:
            positional.append(a)

    if len(positional) < 2:
        io.stderr.write("chown: missing operand\n")
        return CommandResult(exit_code=1)

    owner_spec = positional[0]
    files = positional[1:]

    # Parse OWNER[:GROUP]
    if ":" in owner_spec:
        owner_str, group_str = owner_spec.split(":", 1)
    else:
        owner_str = owner_spec
        group_str = ""

    # Virtual: store as numeric hash of the string
    new_uid = hash(owner_str) % 65536 if owner_str else None
    new_gid = hash(group_str) % 65536 if group_str else None

    exit_code = 0
    for f_arg, f in zip(files, _resolve_paths(files, state, vfs), strict=True):
        node = vfs.get_node(f)
        if node is None:
            io.stderr.write(
                f"chown: cannot access '{f_arg}': No such file or directory\n"
            )
            exit_code = 1
            continue

        def _apply_owner(
            n: _NodeT,
            uid: int | None = new_uid,
            gid: int | None = new_gid,
        ) -> None:
            if uid is not None:
                n.uid = uid
            if gid is not None:
                n.gid = gid

        if recursive and isinstance(node, DirNode):
            _apply_recursive(f, vfs, _apply_owner)
        else:
            _apply_owner(node)

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# chgrp
# ------------------------------------------------------------------


@command("chgrp")
def cmd_chgrp(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    recursive = False
    positional: list[str] = []
    for a in args:
        if a in ("-R", "-r", "--recursive"):
            recursive = True
        else:
            positional.append(a)

    if len(positional) < 2:
        io.stderr.write("chgrp: missing operand\n")
        return CommandResult(exit_code=1)

    group_str = positional[0]
    files = positional[1:]
    new_gid = hash(group_str) % 65536

    exit_code = 0
    for f_arg, f in zip(files, _resolve_paths(files, state, vfs), strict=True):
        node = vfs.get_node(f)
        if node is None:
            io.stderr.write(
                f"chgrp: cannot access '{f_arg}': No such file or directory\n"
            )
            exit_code = 1
            continue

        def _apply_grp(n: _NodeT, gid: int = new_gid) -> None:
            n.gid = gid

        if recursive and isinstance(node, DirNode):
            _apply_recursive(f, vfs, _apply_grp)
        else:
            _apply_grp(node)

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# rmdir
# ------------------------------------------------------------------


@command("rmdir")
def cmd_rmdir(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    dirs = [a for a in args if not a.startswith("-")]
    exit_code = 0
    for d in dirs:
        abs_path = vfs.resolve(d, state.cwd)
        try:
            vfs.rmdir(abs_path)
        except FileNotFoundError:
            io.stderr.write(
                f"rmdir: failed to remove '{d}': No such file or directory\n"
            )
            exit_code = 1
        except NotADirectoryError:
            io.stderr.write(f"rmdir: failed to remove '{d}': Not a directory\n")
            exit_code = 1
        except OSError:
            io.stderr.write(f"rmdir: failed to remove '{d}': Directory not empty\n")
            exit_code = 1

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# stat
# ------------------------------------------------------------------


@command("stat")
def cmd_stat(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    if not files:
        io.stderr.write("stat: missing operand\n")
        return CommandResult(exit_code=1)

    exit_code = 0
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        node = vfs.get_node(abs_path)
        if node is None:
            io.stderr.write(f"stat: cannot stat '{f}': No such file or directory\n")
            exit_code = 1
            continue

        if isinstance(node, DirNode):
            ftype = "directory"
            size = 0
        else:
            ftype = "regular file"
            size = len(node.content)

        io.stdout.write(f"  File: {f}\n")
        io.stdout.write(f"  Size: {size}\tType: {ftype}\n")
        mode_s = oct(node.mode)
        io.stdout.write(f"  Mode: {mode_s}\tUid: {node.uid}\tGid: {node.gid}\n")

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# du
# ------------------------------------------------------------------


def _du_size(path: str, vfs: VirtualFilesystem) -> int:
    """Compute the total size of all files under *path*."""
    node = vfs.get_node(path)
    if node is None:
        return 0
    if isinstance(node, FileNode):
        return len(node.content)
    total = 0
    for dirpath, _dirnames, filenames in vfs.walk(path):
        for fname in filenames:
            fpath = dirpath.rstrip("/") + "/" + fname
            fnode = vfs.get_node(fpath)
            if isinstance(fnode, FileNode):
                total += len(fnode.content)
    return total


@command("du")
def cmd_du(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    summary = False
    human = False
    paths: list[str] = []

    for a in args:
        if a == "-s":
            summary = True
        elif a == "-h":
            human = True
        elif a in ("-sh", "-hs"):
            summary = True
            human = True
        elif a.startswith("-"):
            for ch in a[1:]:
                if ch == "s":
                    summary = True
                elif ch == "h":
                    human = True
        else:
            paths.append(a)

    if not paths:
        paths = ["."]

    exit_code = 0
    for p in paths:
        abs_path = vfs.resolve(p, state.cwd)
        node = vfs.get_node(abs_path)
        if node is None:
            io.stderr.write(f"du: cannot access '{p}': No such file or directory\n")
            exit_code = 1
            continue

        if summary or isinstance(node, FileNode):
            total = _du_size(abs_path, vfs)
            sz = _human_size(total) if human else str(total)
            io.stdout.write(f"{sz}\t{p}\n")
        else:
            for dirpath, _dn, _fn in vfs.walk(abs_path):
                dir_total = _du_size(dirpath, vfs)
                if p.startswith("/"):
                    display = dirpath
                else:
                    suffix = dirpath[len(abs_path) :]
                    display = p if not suffix else "." + suffix
                sz = _human_size(dir_total) if human else str(dir_total)
                io.stdout.write(f"{sz}\t{display}\n")

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# df
# ------------------------------------------------------------------


@command("df")
def cmd_df(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    human = "-h" in args

    total_files = 0
    total_bytes = 0

    def _count(node: DirNode, prefix: str) -> None:
        nonlocal total_files, total_bytes
        for name, child in node.children.items():
            if isinstance(child, FileNode):
                total_files += 1
                total_bytes += len(child.content)
            else:
                _count(child, prefix.rstrip("/") + "/" + name)

    _count(vfs.root, "/")

    sz = _human_size(total_bytes) if human else str(total_bytes)
    io.stdout.write("Filesystem      Files  Size\n")
    io.stdout.write(f"vfs             {total_files}      {sz}\n")

    return CommandResult(exit_code=0)


# ------------------------------------------------------------------
# cksum
# ------------------------------------------------------------------


@command("cksum")
def cmd_cksum(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    files = [a for a in args if not a.startswith("-")]
    if not files:
        data = io.stdin.read().encode("utf-8")
        crc = binascii.crc32(data) & 0xFFFFFFFF
        io.stdout.write(f"{crc} {len(data)} -\n")
        return CommandResult(exit_code=0)

    exit_code = 0
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        try:
            data = vfs.read(abs_path)
        except FileNotFoundError:
            io.stderr.write(f"cksum: {f}: No such file or directory\n")
            exit_code = 1
            continue
        except IsADirectoryError:
            io.stderr.write(f"cksum: {f}: Is a directory\n")
            exit_code = 1
            continue
        crc = binascii.crc32(data) & 0xFFFFFFFF
        io.stdout.write(f"{crc} {len(data)} {f}\n")

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# link
# ------------------------------------------------------------------


@command("link")
def cmd_link(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    positional = [a for a in args if not a.startswith("-")]
    if len(positional) < 2:
        io.stderr.write("link: missing operand\n")
        return CommandResult(exit_code=1)

    target = vfs.resolve(positional[0], state.cwd)
    link_name = vfs.resolve(positional[1], state.cwd)

    try:
        vfs.copy_file(target, link_name)
    except FileNotFoundError:
        io.stderr.write(
            f"link: cannot create link '{positional[1]}': No such file or directory\n"
        )
        return CommandResult(exit_code=1)
    except IsADirectoryError:
        io.stderr.write(f"link: '{positional[0]}': Is a directory\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


# ------------------------------------------------------------------
# shred
# ------------------------------------------------------------------


@command("shred")
def cmd_shred(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    remove = False
    files: list[str] = []
    for a in args:
        if a in ("-u", "--remove"):
            remove = True
        elif a.startswith("-"):
            continue
        else:
            files.append(a)

    if not files:
        io.stderr.write("shred: missing operand\n")
        return CommandResult(exit_code=1)

    exit_code = 0
    for f in files:
        abs_path = vfs.resolve(f, state.cwd)
        node = vfs.get_node(abs_path)
        if node is None:
            io.stderr.write(f"shred: {f}: No such file or directory\n")
            exit_code = 1
            continue
        if isinstance(node, DirNode):
            io.stderr.write(f"shred: {f}: Is a directory\n")
            exit_code = 1
            continue

        # Overwrite with zeros
        node.content = b"\x00" * len(node.content)

        if remove:
            with contextlib.suppress(FileNotFoundError, IsADirectoryError):
                vfs.unlink(abs_path)

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# tree
# ------------------------------------------------------------------


def _tree_walk(
    vfs: VirtualFilesystem,
    path: str,
    io: IOContext,
    prefix: str,
    counts: list[int],
) -> None:
    """Recursively print a tree structure."""
    node = vfs.get_node(path)
    if not isinstance(node, DirNode):
        return
    entries = sorted(node.children.keys())
    for i, name in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        child_path = path.rstrip("/") + "/" + name
        child = node.children[name]
        if isinstance(child, DirNode):
            io.stdout.write(f"{prefix}{connector}{name}\n")
            counts[0] += 1
            ext = "    " if is_last else "\u2502   "
            _tree_walk(vfs, child_path, io, prefix + ext, counts)
        else:
            io.stdout.write(f"{prefix}{connector}{name}\n")
            counts[1] += 1


@command("tree")
def cmd_tree(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    dirs = [a for a in args if not a.startswith("-")]
    if not dirs:
        dirs = ["."]

    exit_code = 0
    for d in dirs:
        abs_path = vfs.resolve(d, state.cwd)
        node = vfs.get_node(abs_path)
        if node is None:
            io.stderr.write(f"tree: '{d}': No such file or directory\n")
            exit_code = 1
            continue
        if not isinstance(node, DirNode):
            io.stdout.write(f"{d}\n")
            continue

        io.stdout.write(f"{d}\n")
        counts: list[int] = [0, 0]
        _tree_walk(vfs, abs_path, io, "", counts)
        io.stdout.write(f"\n{counts[0]} directories, {counts[1]} files\n")

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# mkfifo
# ------------------------------------------------------------------


@command("mkfifo")
def cmd_mkfifo(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    names = [a for a in args if not a.startswith("-")]
    if not names:
        io.stderr.write("mkfifo: missing operand\n")
        return CommandResult(exit_code=1)

    exit_code = 0
    for n in names:
        abs_path = vfs.resolve(n, state.cwd)
        if vfs.exists(abs_path):
            io.stderr.write(f"mkfifo: cannot create fifo '{n}': File exists\n")
            exit_code = 1
            continue
        try:
            vfs.write(abs_path, b"")
        except (FileNotFoundError, NotADirectoryError):
            io.stderr.write(
                f"mkfifo: cannot create fifo '{n}': No such file or directory\n"
            )
            exit_code = 1

    return CommandResult(exit_code=exit_code)


# ------------------------------------------------------------------
# dd
# ------------------------------------------------------------------


@command("dd")
def cmd_dd(
    args: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
    io: IOContext,
) -> CommandResult:
    if_file: str | None = None
    of_file: str | None = None
    bs = 512
    count: int | None = None

    for a in args:
        if a.startswith("if="):
            if_file = a[3:]
        elif a.startswith("of="):
            of_file = a[3:]
        elif a.startswith("bs="):
            try:
                bs = int(a[3:])
            except ValueError:
                io.stderr.write(f"dd: invalid number '{a[3:]}'\n")
                return CommandResult(exit_code=1)
        elif a.startswith("count="):
            try:
                count = int(a[6:])
            except ValueError:
                io.stderr.write(f"dd: invalid number '{a[6:]}'\n")
                return CommandResult(exit_code=1)

    # Read input
    if if_file is not None:
        abs_in = vfs.resolve(if_file, state.cwd)
        try:
            data = vfs.read(abs_in)
        except FileNotFoundError:
            io.stderr.write(
                f"dd: failed to open '{if_file}': No such file or directory\n"
            )
            return CommandResult(exit_code=1)
        except IsADirectoryError:
            io.stderr.write(f"dd: failed to open '{if_file}': Is a directory\n")
            return CommandResult(exit_code=1)
    else:
        data = io.stdin.read().encode("utf-8")

    # Slice by bs and count
    if count is not None:
        data = data[: bs * count]

    # Write output
    if of_file is not None:
        abs_out = vfs.resolve(of_file, state.cwd)
        vfs.write(abs_out, data)
    else:
        io.stdout.write(data.decode("utf-8", errors="replace"))

    # Print summary to stderr (like real dd)
    blocks_full = len(data) // bs
    blocks_partial = 1 if len(data) % bs else 0
    io.stderr.write(f"{blocks_full}+{blocks_partial} records in\n")
    io.stderr.write(f"{blocks_full}+{blocks_partial} records out\n")
    io.stderr.write(f"{len(data)} bytes copied\n")

    return CommandResult(exit_code=0)
