"""Shared I/O helpers for virtual commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


def read_text(
    path: str,
    state: ShellState,
    vfs: VirtualFilesystem,
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


def read_text_inputs(
    files: list[str],
    state: ShellState,
    vfs: VirtualFilesystem,
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
    vfs: VirtualFilesystem,
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
