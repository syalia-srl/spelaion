"""Modern search and archive commands: rg, fd, zip."""

from __future__ import annotations

import fnmatch as _fnmatch
import io as _io
import posixpath
import re
import zipfile
from typing import TYPE_CHECKING

from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem

# ---------------------------------------------------------------------------
# rg (ripgrep)
# ---------------------------------------------------------------------------

_RG_TYPE_MAP: dict[str, list[str]] = {
    "py": [".py"],
    "js": [".js", ".jsx"],
    "ts": [".ts", ".tsx"],
    "go": [".go"],
    "rs": [".rs"],
    "java": [".java"],
    "c": [".c", ".h"],
    "cpp": [".cpp", ".cc", ".cxx", ".hpp"],
    "rb": [".rb"],
    "php": [".php"],
    "sh": [".sh", ".bash"],
    "md": [".md"],
    "json": [".json"],
    "yaml": [".yaml", ".yml"],
    "toml": [".toml"],
    "html": [".html", ".htm"],
    "css": [".css"],
    "sql": [".sql"],
    "txt": [".txt"],
}


def _is_hidden(name: str) -> bool:
    """Return True if *name* starts with a dot (hidden file/dir)."""
    return name.startswith(".")


def _matches_type(filename: str, type_exts: list[str]) -> bool:
    """Check if *filename* has one of the given extensions."""
    return any(filename.endswith(ext) for ext in type_exts)


def _matches_glob(filename: str, globs: list[str]) -> bool:
    """Check if *filename* matches any of the given glob patterns."""
    return any(_fnmatch.fnmatch(filename, g) for g in globs)


def _walk_rg(
    vfs: VirtualFilesystem,
    root: str,
    include_hidden: bool,
    type_exts: list[str] | None,
    globs: list[str],
) -> list[str]:
    """Recursively collect files under *root*, applying filters."""
    results: list[str] = []
    for dirpath, dirnames, filenames in vfs.walk(root):
        # Filter hidden directories in-place
        if not include_hidden:
            dirnames[:] = [d for d in dirnames if not _is_hidden(d)]

        for fname in sorted(filenames):
            if not include_hidden and _is_hidden(fname):
                continue
            full_path = dirpath.rstrip("/") + "/" + fname
            if type_exts and not _matches_type(fname, type_exts):
                continue
            if globs and not _matches_glob(fname, globs):
                continue
            results.append(full_path)
    return results


@command("rg")
def cmd_rg(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    patterns: list[str] = []
    paths: list[str] = []
    ignore_case = False
    word_regexp = False
    files_with_matches = False
    count_mode = False
    invert_match = False
    fixed_strings = False
    include_hidden = False
    quiet = False
    only_matching = False
    line_numbers = True  # rg default: on
    type_exts: list[str] | None = None
    globs: list[str] = []
    after_ctx = 0
    before_ctx = 0

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-i", "--ignore-case"):
            ignore_case = True
        elif a in ("-w", "--word-regexp"):
            word_regexp = True
        elif a in ("-l", "--files-with-matches"):
            files_with_matches = True
        elif a in ("-c", "--count"):
            count_mode = True
        elif a in ("-v", "--invert-match"):
            invert_match = True
        elif a in ("-F", "--fixed-strings"):
            fixed_strings = True
        elif a in ("-q", "--quiet"):
            quiet = True
        elif a in ("-o", "--only-matching"):
            only_matching = True
        elif a == "--hidden":
            include_hidden = True
        elif a == "--no-heading":
            pass  # already the default output mode
        elif a in ("-n", "--line-number"):
            line_numbers = True
        elif a == "--no-line-number":
            line_numbers = False
        elif a.startswith("--color"):
            pass  # always no color
        elif a == "-e" and i + 1 < len(args):
            i += 1
            patterns.append(args[i])
        elif a in ("-t", "--type") and i + 1 < len(args):
            i += 1
            t = args[i]
            exts = _RG_TYPE_MAP.get(t)
            if exts is None:
                io.stderr.write(f"rg: unknown file type: {t}\n")
                return CommandResult(exit_code=1)
            type_exts = exts
        elif a in ("-g", "--glob") and i + 1 < len(args):
            i += 1
            globs.append(args[i])
        elif a in ("-A", "--after-context") and i + 1 < len(args):
            i += 1
            after_ctx = int(args[i])
        elif a in ("-B", "--before-context") and i + 1 < len(args):
            i += 1
            before_ctx = int(args[i])
        elif a in ("-C", "--context") and i + 1 < len(args):
            i += 1
            after_ctx = before_ctx = int(args[i])
        elif not a.startswith("-"):
            if not patterns:
                patterns.append(a)
            else:
                paths.append(a)
        i += 1

    if not patterns:
        io.stderr.write("rg: missing pattern\n")
        return CommandResult(exit_code=2)

    # Build regex
    combined = "|".join(patterns) if len(patterns) > 1 else patterns[0]
    if fixed_strings:
        combined = re.escape(combined)
    if word_regexp:
        combined = r"\b" + combined + r"\b"
    re_flags = re.IGNORECASE if ignore_case else 0
    try:
        regex = re.compile(combined, re_flags)
    except re.error as e:
        io.stderr.write(f"rg: invalid regex: {e}\n")
        return CommandResult(exit_code=2)

    # Default path is cwd
    if not paths:
        paths = ["."]

    # Collect all files
    all_files: list[str] = []
    for p in paths:
        abs_path = vfs.resolve(p, state.cwd)
        if vfs.is_file(abs_path):
            all_files.append(abs_path)
        elif vfs.is_dir(abs_path):
            all_files.extend(_walk_rg(vfs, abs_path, include_hidden, type_exts, globs))
        else:
            io.stderr.write(f"rg: {p}: No such file or directory\n")

    matched_any = False

    for fpath in sorted(all_files):
        try:
            content = vfs.read(fpath).decode("utf-8", errors="replace")
        except (FileNotFoundError, IsADirectoryError):
            continue

        lines = content.splitlines()
        match_count = 0
        match_indices: set[int] = set()
        to_print: set[int] = set()

        for idx, line in enumerate(lines):
            is_match = bool(regex.search(line)) != invert_match
            if is_match:
                match_count += 1
                matched_any = True
                match_indices.add(idx)
                ctx_start = max(0, idx - before_ctx)
                ctx_end = min(len(lines), idx + after_ctx + 1)
                for ctx in range(ctx_start, ctx_end):
                    to_print.add(ctx)

        if quiet and matched_any:
            return CommandResult(exit_code=0)

        if files_with_matches and match_count > 0:
            io.stdout.write(fpath + "\n")
            continue

        if count_mode:
            io.stdout.write(f"{fpath}:{match_count}\n")
            continue

        # Print matching lines
        if before_ctx or after_ctx:
            prev_printed = -2
            for idx in sorted(to_print):
                if prev_printed >= 0 and idx > prev_printed + 1:
                    io.stdout.write("--\n")
                _rg_print_line(
                    fpath,
                    idx + 1,
                    lines[idx],
                    line_numbers,
                    only_matching,
                    regex,
                    idx in match_indices,
                    io,
                )
                prev_printed = idx
        else:
            for idx in sorted(match_indices):
                _rg_print_line(
                    fpath,
                    idx + 1,
                    lines[idx],
                    line_numbers,
                    only_matching,
                    regex,
                    True,
                    io,
                )

    return CommandResult(exit_code=0 if matched_any else 1)


def _rg_print_line(
    fname: str,
    lineno: int,
    line: str,
    show_lineno: bool,
    only_match: bool,
    regex: re.Pattern[str],
    is_match: bool,
    io: IOContext,
) -> None:
    prefix = fname + ":"
    if show_lineno:
        prefix += str(lineno) + ":"

    if only_match and is_match:
        for m in regex.finditer(line):
            io.stdout.write(prefix + m.group() + "\n")
    else:
        io.stdout.write(prefix + line + "\n")


# ---------------------------------------------------------------------------
# fd
# ---------------------------------------------------------------------------


@command("fd")
def cmd_fd(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    pattern: str | None = None
    paths: list[str] = []
    filter_type: str | None = None  # "f", "d", "l"
    extensions: list[str] = []
    include_hidden = False
    max_depth: int | None = None
    full_path = False
    exec_cmd: list[str] | None = None

    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-t", "--type") and i + 1 < len(args):
            i += 1
            filter_type = args[i]
        elif a in ("-e", "--extension") and i + 1 < len(args):
            i += 1
            ext = args[i]
            if not ext.startswith("."):
                ext = "." + ext
            extensions.append(ext)
        elif a in ("-H", "--hidden"):
            include_hidden = True
        elif a in ("-I", "--no-ignore"):
            pass  # no-op in VFS
        elif a in ("-d", "--max-depth") and i + 1 < len(args):
            i += 1
            max_depth = int(args[i])
        elif a == "--full-path":
            full_path = True
        elif a in ("-x", "--exec"):
            exec_cmd = []
            i += 1
            while i < len(args):
                exec_cmd.append(args[i])
                i += 1
            break
        elif not a.startswith("-"):
            if pattern is None:
                pattern = a
            else:
                paths.append(a)
        i += 1

    if pattern is None:
        pattern = ""  # match everything

    if not paths:
        paths = ["."]

    # Compile the regex pattern for matching
    try:
        regex = re.compile(pattern)
    except re.error as e:
        io.stderr.write(f"fd: invalid regex: {e}\n")
        return CommandResult(exit_code=1)

    for start_path in paths:
        abs_start = vfs.resolve(start_path, state.cwd)
        if not vfs.exists(abs_start):
            io.stderr.write(f"fd: '{start_path}': No such file or directory\n")
            continue

        base_depth = abs_start.rstrip("/").count("/")

        for dirpath, dirnames, filenames in vfs.walk(abs_start):
            # Filter hidden directories in-place
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not _is_hidden(d)]

            depth = dirpath.rstrip("/").count("/") - base_depth

            # Process directories
            for d in sorted(dirnames):
                d_depth = depth + 1
                if max_depth is not None and d_depth > max_depth:
                    continue
                if not include_hidden and _is_hidden(d):
                    continue
                if filter_type is not None and filter_type != "d":
                    continue

                d_path = dirpath.rstrip("/") + "/" + d
                match_target = d_path if full_path else d
                if not regex.search(match_target):
                    continue

                _fd_output(d_path, abs_start, start_path, exec_cmd, io)

            # Limit directory recursion
            if max_depth is not None:
                dirnames[:] = [d for d in dirnames if depth + 1 < max_depth]

            # Process files
            for fname in sorted(filenames):
                f_depth = depth + 1
                if max_depth is not None and f_depth > max_depth:
                    continue
                if not include_hidden and _is_hidden(fname):
                    continue
                if filter_type is not None and filter_type != "f":
                    continue
                if extensions and not any(fname.endswith(ext) for ext in extensions):
                    continue

                f_path = dirpath.rstrip("/") + "/" + fname
                match_target = f_path if full_path else fname
                if not regex.search(match_target):
                    continue

                _fd_output(f_path, abs_start, start_path, exec_cmd, io)

    return CommandResult(exit_code=0)


def _fd_output(
    abs_path: str,
    abs_start: str,
    start_path: str,
    exec_cmd: list[str] | None,
    io: IOContext,
) -> None:
    """Print or execute for a single fd match."""
    # Compute display path relative to start
    if abs_path == abs_start:
        display = start_path
    else:
        rel = abs_path[len(abs_start) :]
        if rel.startswith("/"):
            rel = rel[1:]
        display = rel

    if exec_cmd is not None and io.executor is not None:
        from agentsh.exec.redirs import IOContext as _IOCtx

        cmd_line = [display if t == "{}" else t for t in exec_cmd]
        sub_io = _IOCtx()
        io.executor.execute_argv(cmd_line, sub_io)  # type: ignore[attr-defined]
        out = sub_io.stdout.getvalue()
        if out:
            io.stdout.write(out)
        err = sub_io.stderr.getvalue()
        if err:
            io.stderr.write(err)
    else:
        io.stdout.write(display + "\n")


# ---------------------------------------------------------------------------
# zip
# ---------------------------------------------------------------------------


@command("zip")
def cmd_zip(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    recursive = False
    junk_paths = False
    archive_name: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-r":
            recursive = True
        elif a == "-j":
            junk_paths = True
        elif not a.startswith("-"):
            if archive_name is None:
                archive_name = a
            else:
                files.append(a)
        i += 1

    if archive_name is None:
        io.stderr.write("zip: missing archive name\n")
        return CommandResult(exit_code=1)

    if not files:
        io.stderr.write("zip: missing file arguments\n")
        return CommandResult(exit_code=1)

    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            abs_path = vfs.resolve(f, state.cwd)
            if vfs.is_dir(abs_path):
                if not recursive:
                    io.stderr.write(f"zip: {f}: is a directory (use -r to recurse)\n")
                    continue
                for dirpath, _dirs, fnames in vfs.walk(abs_path):
                    for fname in fnames:
                        full = dirpath.rstrip("/") + "/" + fname
                        data = vfs.read(full)
                        if junk_paths:
                            arcname = fname
                        else:
                            arcname = f.rstrip("/") + full[len(abs_path) :]
                        zf.writestr(arcname.lstrip("/"), data)
            elif vfs.is_file(abs_path):
                data = vfs.read(abs_path)
                arcname = posixpath.basename(f) if junk_paths else f
                zf.writestr(arcname.lstrip("/"), data)
            else:
                io.stderr.write(f"zip: {f}: No such file or directory\n")
                return CommandResult(exit_code=1)

    archive_path = vfs.resolve(archive_name, state.cwd)
    vfs.write(archive_path, buf.getvalue())
    return CommandResult(exit_code=0)
