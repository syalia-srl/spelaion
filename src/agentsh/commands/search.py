"""Search commands: grep, find, xargs."""

from __future__ import annotations

import fnmatch as _fnmatch
import posixpath
import re
from typing import TYPE_CHECKING

from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------


_GREP_BOOL_FLAGS: dict[str, str] = {
    "i": "ignore_case",
    "v": "invert",
    "c": "count_only",
    "l": "files_only",
    "n": "line_numbers",
    "r": "recursive",
    "R": "recursive",
    "E": "extended",
    "F": "fixed",
    "w": "word_match",
    "q": "quiet",
    "o": "only_match",
}


@command("grep")
def cmd_grep(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    patterns: list[str] = []
    files: list[str] = []
    opts: dict[str, bool] = {v: False for v in _GREP_BOOL_FLAGS.values()}
    after_ctx = 0
    before_ctx = 0

    def _set_flag(ch: str) -> bool:
        attr = _GREP_BOOL_FLAGS.get(ch)
        if attr:
            opts[attr] = True
            return True
        return False

    i = 0
    while i < len(args):
        a = args[i]
        if len(a) == 2 and a[0] == "-" and _set_flag(a[1]):
            pass
        elif a == "-e" and i + 1 < len(args):
            i += 1
            patterns.append(args[i])
        elif a == "-A" and i + 1 < len(args):
            i += 1
            after_ctx = int(args[i])
        elif a == "-B" and i + 1 < len(args):
            i += 1
            before_ctx = int(args[i])
        elif a == "-C" and i + 1 < len(args):
            i += 1
            after_ctx = before_ctx = int(args[i])
        elif a == "--":
            files.extend(args[i + 1 :])
            break
        elif (
            a.startswith("-")
            and len(a) > 2
            and all(c in _GREP_BOOL_FLAGS for c in a[1:])
        ):
            for c in a[1:]:
                _set_flag(c)
        elif not a.startswith("-"):
            if not patterns:
                patterns.append(a)
            else:
                files.append(a)
        elif not patterns:
            patterns.append(a)
        else:
            files.append(a)
        i += 1

    if not patterns:
        io.stderr.write("grep: missing pattern\n")
        return CommandResult(exit_code=2)

    # Build regex
    combined = (
        "|".join(patterns) if opts["extended"] or len(patterns) > 1 else patterns[0]
    )
    if opts["fixed"]:
        combined = re.escape(combined)
    if opts["word_match"]:
        combined = r"\b" + combined + r"\b"

    re_flags = re.IGNORECASE if opts["ignore_case"] else 0
    try:
        regex = re.compile(combined, re_flags)
    except re.error as e:
        io.stderr.write(f"grep: invalid regex: {e}\n")
        return CommandResult(exit_code=2)

    # Collect files to search
    if not files:
        files = ["-"]

    if opts["recursive"]:
        expanded_files: list[str] = []
        for f in files:
            if f == "-":
                expanded_files.append("-")
                continue
            abs_path = vfs.resolve(f, state.cwd)
            if vfs.is_dir(abs_path):
                for dirpath, _dirs, fnames in vfs.walk(abs_path):
                    for fn in fnames:
                        expanded_files.append(dirpath.rstrip("/") + "/" + fn)
            else:
                expanded_files.append(abs_path)
        files = expanded_files

    multi_file = len(files) > 1
    matched_any = False

    for f in files:
        if f == "-":
            content = io.stdin.read()
            fname = "(standard input)"
        else:
            abs_path = vfs.resolve(f, state.cwd)
            try:
                content = vfs.read(abs_path).decode("utf-8", errors="replace")
            except (FileNotFoundError, IsADirectoryError):
                io.stderr.write(f"grep: {f}: No such file or directory\n")
                continue
            fname = f

        lines = content.splitlines()
        match_count = 0
        # First pass: determine which lines match
        match_lines: set[int] = set()
        to_print: set[int] = set()

        for idx, line in enumerate(lines):
            is_match = bool(regex.search(line)) != opts["invert"]
            if is_match:
                match_count += 1
                matched_any = True
                match_lines.add(idx)
                ctx_start = max(0, idx - before_ctx)
                ctx_end = min(len(lines), idx + after_ctx + 1)
                for ctx in range(ctx_start, ctx_end):
                    to_print.add(ctx)

        if opts["quiet"] and matched_any:
            return CommandResult(exit_code=0)

        if opts["files_only"] and match_count > 0:
            io.stdout.write(fname + "\n")
            continue

        if opts["count_only"]:
            prefix = f"{fname}:" if multi_file else ""
            io.stdout.write(f"{prefix}{match_count}\n")
            continue

        # Second pass: print matching lines (reuse first-pass results)
        if before_ctx or after_ctx:
            prev_printed = -2
            for idx in sorted(to_print):
                if prev_printed >= 0 and idx > prev_printed + 1:
                    io.stdout.write("--\n")
                _grep_print_line(
                    fname,
                    idx + 1,
                    lines[idx],
                    multi_file,
                    opts["line_numbers"],
                    opts["only_match"],
                    regex,
                    idx in match_lines,
                    io,
                )
                prev_printed = idx
        else:
            for idx in sorted(match_lines):
                _grep_print_line(
                    fname,
                    idx + 1,
                    lines[idx],
                    multi_file,
                    opts["line_numbers"],
                    opts["only_match"],
                    regex,
                    True,
                    io,
                )

    return CommandResult(exit_code=0 if matched_any else 1)


def _grep_print_line(
    fname: str,
    lineno: int,
    line: str,
    multi_file: bool,
    show_lineno: bool,
    only_match: bool,
    regex: re.Pattern[str],
    is_match: bool,
    io: IOContext,
) -> None:
    prefix = ""
    if multi_file:
        prefix += fname + ":"
    if show_lineno:
        prefix += str(lineno) + ":"

    if only_match and is_match:
        for m in regex.finditer(line):
            io.stdout.write(prefix + m.group() + "\n")
    else:
        io.stdout.write(prefix + line + "\n")


# ---------------------------------------------------------------------------
# find
# ---------------------------------------------------------------------------


@command("find")
def cmd_find(  # noqa: C901
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    paths: list[str] = []
    predicates: list[tuple[str, str]] = []
    max_depth: int | None = None
    min_depth = 0
    run_cmd: list[str] | None = None

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-name" and i + 1 < len(args):
            i += 1
            predicates.append(("name", args[i]))
        elif a == "-type" and i + 1 < len(args):
            i += 1
            predicates.append(("type", args[i]))
        elif a == "-path" and i + 1 < len(args):
            i += 1
            predicates.append(("path", args[i]))
        elif a == "-maxdepth" and i + 1 < len(args):
            i += 1
            max_depth = int(args[i])
        elif a == "-mindepth" and i + 1 < len(args):
            i += 1
            min_depth = int(args[i])
        elif a == "-exec":
            run_cmd = []
            i += 1
            while i < len(args) and args[i] != ";":
                run_cmd.append(args[i])
                i += 1
        elif not a.startswith("-"):
            paths.append(a)
        i += 1

    if not paths:
        paths = ["."]

    for start in paths:
        abs_start = vfs.resolve(start, state.cwd)
        if not vfs.exists(abs_start):
            io.stderr.write(f"find: '{start}': No such file or directory\n")
            continue

        # Collect all candidates via walk
        candidates: list[tuple[str, int]] = [(abs_start, 0)]
        if not vfs.is_file(abs_start):
            base_depth = abs_start.rstrip("/").count("/")
            for dirpath, dirnames, filenames in vfs.walk(abs_start):
                depth = dirpath.rstrip("/").count("/") - base_depth
                for d in dirnames:
                    candidates.append((dirpath.rstrip("/") + "/" + d, depth + 1))
                for f in filenames:
                    candidates.append((dirpath.rstrip("/") + "/" + f, depth + 1))

        for cand_path, depth in candidates:
            if max_depth is not None and depth > max_depth:
                continue
            if depth < min_depth:
                continue

            # Apply predicates
            match = True
            basename = posixpath.basename(cand_path)
            for pred_type, pred_val in predicates:
                if pred_type == "name":
                    if not _fnmatch.fnmatch(basename, pred_val):
                        match = False
                        break
                elif pred_type == "type":
                    if pred_val == "f" and not vfs.is_file(cand_path):
                        match = False
                        break
                    if pred_val == "d" and not vfs.is_dir(cand_path):
                        match = False
                        break
                elif pred_type == "path" and not _fnmatch.fnmatch(cand_path, pred_val):
                    match = False
                    break

            if not match:
                continue

            # Compute display path
            if cand_path == abs_start:
                display = start
            else:
                rel = cand_path[len(abs_start) :]
                display = start.rstrip("/") + rel

            if run_cmd is not None and io.executor is not None:
                cmd_line = [display if t == "{}" else t for t in run_cmd]
                _run_sub(io.executor, cmd_line, io)
            else:
                io.stdout.write(display + "\n")

    return CommandResult(exit_code=0)


def _run_sub(executor: object, cmd_line: list[str], io: IOContext) -> None:
    """Run a sub-command via the executor's ``execute_argv``."""
    from agentsh.exec.redirs import IOContext as _IOCtx

    sub_io = _IOCtx()
    executor.execute_argv(cmd_line, sub_io)  # type: ignore[attr-defined]
    out = sub_io.stdout.getvalue()
    if out:
        io.stdout.write(out)
    err = sub_io.stderr.getvalue()
    if err:
        io.stderr.write(err)


# ---------------------------------------------------------------------------
# xargs
# ---------------------------------------------------------------------------


@command("xargs")
def cmd_xargs(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    replace_str: str | None = None
    max_args: int | None = None
    delimiter: str | None = None
    null_delim = False
    cmd_template: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-I" and i + 1 < len(args):
            i += 1
            replace_str = args[i]
        elif a == "-n" and i + 1 < len(args):
            i += 1
            max_args = int(args[i])
        elif a == "-d" and i + 1 < len(args):
            i += 1
            delimiter = args[i]
        elif a == "-0":
            null_delim = True
        else:
            cmd_template.append(a)
        i += 1

    if not cmd_template:
        cmd_template = ["echo"]

    stdin_text = io.stdin.read()

    if null_delim:
        items = stdin_text.split("\0")
    elif delimiter is not None:
        items = stdin_text.split(delimiter)
    else:
        items = stdin_text.split()

    items = [it for it in items if it]

    if io.executor is None:
        io.stderr.write("xargs: no executor available\n")
        return CommandResult(exit_code=1)

    if replace_str:
        for item in items:
            cmd_line = [t.replace(replace_str, item) for t in cmd_template]
            _run_sub(io.executor, cmd_line, io)
    elif max_args:
        for chunk_start in range(0, len(items), max_args):
            chunk = items[chunk_start : chunk_start + max_args]
            cmd_line = cmd_template + chunk
            _run_sub(io.executor, cmd_line, io)
    else:
        cmd_line = cmd_template + items
        _run_sub(io.executor, cmd_line, io)

    return CommandResult(exit_code=0)
