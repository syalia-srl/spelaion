"""Shared I/O helpers for virtual commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem


def read_text(
    path: str,
    state: ShellState,
    vfs: Filesystem,
    io: IOContext,
    cmd: str,
) -> str | None:
    """Read a single VFS file as text, or stdin if *path* is ``-``.

    Returns ``None`` on error (after writing to *io.stderr*).
    """
    if path == "-":
        return io.stdin.read()
    abs_path = vfs.resolve(path, state.cwd)
    try:
        return vfs.read(abs_path).decode("utf-8", errors="replace")
    except FileNotFoundError:
        io.stderr.write(f"{cmd}: {path}: No such file or directory\n")
        return None
    except IsADirectoryError:
        io.stderr.write(f"{cmd}: {path}: Is a directory\n")
        return None
    except OSError as e:
        # One unreadable file (a symlink out of its mount) never ends the
        # command: say so and go on with the rest, as GNU tools do.
        io.stderr.write(f"{cmd}: {path}: {e.strerror or e}\n")
        return None


def split_flags(args: list[str], letters: str, valued: str = "") -> list[str]:
    """Split ``-rn`` into ``-r -n`` and ``-k2`` into ``-k 2``.

    Only arguments made wholly of *letters*, or of *letters* ending in one
    of *valued* (which takes the rest as its value), are split; anything
    else, and everything after ``--``, is left as it is.
    """
    out: list[str] = []
    for i, a in enumerate(args):
        if a == "--":
            out.extend(args[i:])
            break
        if len(a) > 2 and a[0] == "-" and a[1] != "-":
            body = a[1:]
            split: list[str] = []
            for j, ch in enumerate(body):
                if ch in valued:
                    split += [f"-{ch}", body[j + 1 :]] if body[j + 1 :] else [f"-{ch}"]
                    break
                if ch not in letters:
                    split = []
                    break
                split.append(f"-{ch}")
            if split:
                out.extend(split)
                continue
        out.append(a)
    return out


def read_text_inputs(
    files: list[str],
    state: ShellState,
    vfs: Filesystem,
    io: IOContext,
    cmd: str,
) -> tuple[str, int]:
    """Read and concatenate multiple files (or stdin).

    Returns ``(text, exit_code)`` where *exit_code* is non-zero if any
    file could not be read.
    """
    if not files or files == ["-"]:
        return io.stdin.read(), 0
    chunks: list[str] = []
    exit_code = 0
    for f in files:
        content = read_text(f, state, vfs, io, cmd)
        if content is None:
            exit_code = 1
        else:
            chunks.append(content)
    return "".join(chunks), exit_code


def read_binary_inputs(
    files: list[str],
    state: ShellState,
    vfs: Filesystem,
    io: IOContext,
    cmd: str,
) -> list[tuple[str, bytes | None]]:
    """Read files as raw bytes (or stdin encoded as UTF-8).

    Returns a list of ``(filename, data)`` pairs; *data* is ``None``
    when the file could not be read.
    """
    if not files:
        return [("-", io.stdin.read().encode("utf-8"))]
    result: list[tuple[str, bytes | None]] = []
    for f in files:
        if f == "-":
            result.append(("-", io.stdin.read().encode("utf-8")))
            continue
        abs_path = vfs.resolve(f, state.cwd)
        try:
            result.append((f, vfs.read(abs_path)))
        except FileNotFoundError:
            io.stderr.write(f"{cmd}: {f}: No such file or directory\n")
            result.append((f, None))
        except IsADirectoryError:
            io.stderr.write(f"{cmd}: {f}: Is a directory\n")
            result.append((f, None))
    return result
