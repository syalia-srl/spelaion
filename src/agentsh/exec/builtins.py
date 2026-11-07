"""Builtin command implementations.

Each builtin: (args, state, vfs, io) -> CommandResult
All filesystem interactions go through VFS.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem

BuiltinFn = Callable[
    ["list[str]", "ShellState", "VirtualFilesystem", "IOContext"],
    CommandResult,
]


def builtin_echo(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement echo builtin.

    Flags:
      -n  Do not output trailing newline
      -e  Enable interpretation of backslash escapes
      -E  Disable interpretation of backslash escapes (default)
    Flags can be combined (e.g. ``-ne``).  Processing stops at the first
    argument that is not a recognised flag string.
    """
    no_newline = False
    enable_escapes = False
    i = 0

    # Parse leading flag arguments.  In bash, echo accepts combined flags
    # like ``-neE`` and stops at the first non-flag argument.
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and len(arg) > 1 and all(c in "neE" for c in arg[1:]):
            for ch in arg[1:]:
                if ch == "n":
                    no_newline = True
                elif ch == "e":
                    enable_escapes = True
                elif ch == "E":
                    enable_escapes = False
            i += 1
        else:
            break

    text = " ".join(args[i:])
    if enable_escapes:
        text = _echo_escape(text)
    if not no_newline:
        text += "\n"
    io.stdout.write(text)
    return CommandResult(exit_code=0)


_ECHO_ESCAPES: dict[str, str] = {
    "\\": "\\",
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}


def _echo_escape(text: str) -> str:
    """Interpret backslash escape sequences for ``echo -e``.

    Supported: ``\\\\``, ``\\a``, ``\\b``, ``\\c`` (stop output),
    ``\\e`` / ``\\E`` (ESC), ``\\f``, ``\\n``, ``\\r``, ``\\t``, ``\\v``,
    ``\\0NNN`` (octal), ``\\xHH`` (hex).
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "\\" or i + 1 >= n:
            out.append(text[i])
            i += 1
            continue
        nxt = text[i + 1]
        if nxt == "c":
            break  # \c — stop further output
        if nxt in _ECHO_ESCAPES:
            out.append(_ECHO_ESCAPES[nxt])
            i += 2
        elif nxt == "0":
            ch, i = _echo_parse_octal(text, i, n)
            out.append(ch)
        elif nxt == "x":
            ch, i = _echo_parse_hex(text, i, n)
            out.append(ch)
        else:
            out.append("\\" + nxt)
            i += 2
    return "".join(out)


def _echo_parse_octal(text: str, i: int, n: int) -> tuple[str, int]:
    """Parse ``\\0NNN`` octal escape for echo starting at backslash position *i*."""
    end = i + 2
    while end < min(i + 5, n) and text[end] in "01234567":
        end += 1
    octal_str = text[i + 2 : end]
    if octal_str:
        return chr(int(octal_str, 8) & 0xFF), end
    return "\0", end


def _echo_parse_hex(text: str, i: int, n: int) -> tuple[str, int]:
    """Parse ``\\xHH`` hex escape for echo starting at backslash position *i*."""
    end = i + 2
    while end < min(i + 4, n) and text[end] in "0123456789abcdefABCDEF":
        end += 1
    hex_str = text[i + 2 : end]
    if hex_str:
        return chr(int(hex_str, 16)), end
    return "\\x", end


def builtin_printf(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement printf builtin with full format string support.

    Supports format specifiers: ``%[-0 +]?[width|*]?[.precision|.*]?[sdixXofc%]``
    Escape sequences: ``\\n \\t \\\\ \\\" \\xNN \\0NNN``
    Cycles through format string when extra arguments remain.
    """
    if not args:
        return CommandResult(exit_code=0)

    fmt = args[0]
    fmt_args = args[1:]

    result = _printf_format(fmt, fmt_args)
    io.stdout.write(result)
    return CommandResult(exit_code=0)


# Regex matching a single printf format specifier:
#   %[flags][width][.precision]conversion
# where width/precision can be '*' (take from next arg).
_FMT_SPEC_RE = re.compile(
    r"%"
    r"(?P<flags>[-+ 0#]*)?"
    r"(?P<width>\*|\d+)?"
    r"(?:\.(?P<precision>\*|\d+))?"
    r"(?P<conv>[sdixXofceEgGc%])"
)


_SIMPLE_ESCAPES: dict[str, str] = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    '"': '"',
    "'": "'",
}


def _parse_hex_escape(text: str, i: int, n: int) -> tuple[str, int]:
    """Parse ``\\xNN`` hex escape starting at backslash position *i*."""
    if i + 3 < n:
        hex_str = text[i + 2 : i + 4]
        try:
            return chr(int(hex_str, 16)), i + 4
        except ValueError:
            pass
    return "\\x", i + 2


def _parse_octal_escape(text: str, i: int, n: int) -> tuple[str, int]:
    """Parse ``\\0NNN`` octal escape starting at backslash position *i*."""
    end = i + 2
    while end < min(i + 5, n) and text[end] in "01234567":
        end += 1
    octal_str = text[i + 2 : end]
    if octal_str:
        return chr(int(octal_str, 8) & 0xFF), end
    return "\0", end


def _process_escape_sequences(text: str) -> str:
    """Expand backslash escape sequences in a printf format string."""
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in _SIMPLE_ESCAPES:
                out.append(_SIMPLE_ESCAPES[nxt])
                i += 2
            elif nxt == "x":
                ch, i = _parse_hex_escape(text, i, n)
                out.append(ch)
            elif nxt == "0":
                ch, i = _parse_octal_escape(text, i, n)
                out.append(ch)
            else:
                out.append("\\" + nxt)
                i += 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _coerce_int(arg: str) -> int:
    """Coerce a string argument to int, bash-style.

    Handles decimal, 0x hex, 0 octal prefixes.  Returns 0 on failure.
    """
    if not arg:
        return 0
    try:
        # Handle 0x prefix for hex, 0 prefix for octal
        if arg.startswith("0x") or arg.startswith("0X"):
            return int(arg, 16)
        if arg.startswith("0") and len(arg) > 1 and arg[1:].isdigit():
            return int(arg, 8)
        return int(arg)
    except ValueError:
        return 0


def _coerce_float(arg: str) -> float:
    """Coerce a string argument to float.  Returns 0.0 on failure."""
    if not arg:
        return 0.0
    try:
        return float(arg)
    except ValueError:
        return 0.0


def _printf_format(fmt: str, args: list[str]) -> str:
    """Full printf-style formatting with arg cycling.

    Processes escape sequences, then iterates over format specifiers.
    When there are more ``args`` than specifiers consume in one pass,
    the format string is reused (cycling) until all args are consumed.
    """
    expanded = _process_escape_sequences(fmt)

    # If there are no format specifiers at all, just return the expanded text
    if not _FMT_SPEC_RE.search(expanded):
        return expanded

    result: list[str] = []
    arg_idx = 0
    # Track whether at least one pass has been done
    first_pass = True

    while first_pass or arg_idx < len(args):
        first_pass = False
        pos = 0
        while pos < len(expanded):
            m = _FMT_SPEC_RE.search(expanded, pos)
            if m is None:
                # Append the rest of the literal text
                result.append(expanded[pos:])
                break

            # Append literal text before this specifier
            result.append(expanded[pos : m.start()])

            conv = m.group("conv")

            # %% is literal '%' and doesn't consume an arg
            if conv == "%":
                result.append("%")
                pos = m.end()
                continue

            # --- Resolve width ---
            width_str = m.group("width") or ""
            if width_str == "*":
                width_val = str(
                    _coerce_int(args[arg_idx] if arg_idx < len(args) else "")
                )
                arg_idx += 1
            else:
                width_val = width_str

            # --- Resolve precision ---
            precision_str = m.group("precision")
            if precision_str == "*":
                precision_val: str | None = str(
                    _coerce_int(args[arg_idx] if arg_idx < len(args) else "")
                )
                arg_idx += 1
            else:
                precision_val = precision_str  # may be None

            flags_str = m.group("flags") or ""

            # Consume the next argument for the value
            arg = args[arg_idx] if arg_idx < len(args) else ""
            arg_idx += 1

            # Build a Python %-style format spec and apply it
            result.append(
                _apply_format_spec(flags_str, width_val, precision_val, conv, arg)
            )

            pos = m.end()

    return "".join(result)


def _apply_format_spec(
    flags: str,
    width: str,
    precision: str | None,
    conv: str,
    arg: str,
) -> str:
    """Build a Python ``%``-format string and apply it to *arg*.

    Returns the formatted string.
    """
    # Build the %-spec: %[flags][width][.precision]conv
    spec = "%"
    spec += flags
    spec += width

    if precision is not None:
        spec += "." + precision

    # Map bash conversion letters to Python %-format
    if conv in ("d", "i"):
        spec += "d"
        try:
            return spec % _coerce_int(arg)
        except (ValueError, OverflowError):
            return spec % 0
    elif conv == "s":
        spec += "s"
        return spec % arg
    elif conv in ("f", "e", "E", "g", "G"):
        spec += conv
        try:
            return spec % _coerce_float(arg)
        except (ValueError, OverflowError):
            return spec % 0.0
    elif conv in ("x", "X"):
        spec += conv
        try:
            return spec % _coerce_int(arg)
        except (ValueError, OverflowError):
            return spec % 0
    elif conv == "o":
        spec += "o"
        try:
            return spec % _coerce_int(arg)
        except (ValueError, OverflowError):
            return spec % 0
    elif conv == "c":
        # %c prints the first character (or empty if arg is empty)
        char = arg[0] if arg else "\0"
        spec += "c"
        return spec % char
    else:
        # Unknown — return the literal spec + arg
        return "%" + conv


def builtin_cd(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement cd builtin. Changes cwd if target is a VFS directory."""
    if not args:
        target = state.get_var("HOME") or "/"
    elif args[0] == "-":
        target = state.get_var("OLDPWD") or state.cwd
    else:
        target = args[0]

    abs_path = vfs.resolve(target, state.cwd)

    if not vfs.exists(abs_path):
        io.stderr.write(f"cd: {target}: No such file or directory\n")
        return CommandResult(exit_code=1)

    if not vfs.is_dir(abs_path):
        io.stderr.write(f"cd: {target}: Not a directory\n")
        return CommandResult(exit_code=1)

    old_cwd = state.cwd
    state.cwd = abs_path
    state.set_var("OLDPWD", old_cwd)
    state.set_var("PWD", abs_path)
    return CommandResult(exit_code=0)


def builtin_pwd(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement pwd builtin."""
    io.stdout.write(state.cwd + "\n")
    return CommandResult(exit_code=0)


def builtin_export(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement export builtin."""
    if not args:
        # Print all exported variables
        for name, value in sorted(state.exported_env.items()):
            io.stdout.write(f'declare -x {name}="{value}"\n')
        return CommandResult(exit_code=0)

    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            state.export_var(name, value)
        else:
            state.export_var(arg)

    return CommandResult(exit_code=0)


def builtin_unset(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement unset builtin."""
    for name in args:
        if name in ("-v", "-f"):
            continue
        state.scope.unset(name)
        state.exported_env.pop(name, None)

    return CommandResult(exit_code=0)


def builtin_true(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


def builtin_false(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=1)


def builtin_exit(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement exit builtin."""
    code = 0
    if args:
        try:
            code = int(args[0])
        except ValueError:
            io.stderr.write(f"exit: {args[0]}: numeric argument required\n")
            code = 2
    raise SystemExit(code)


def builtin_test(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement test/[ builtin.

    Delegates to :class:`BoolEvaluator` for the actual evaluation logic.
    """
    from agentsh.exec.bool_eval import BoolEvaluator

    if args and args[-1] == "]":
        args = args[:-1]

    if not args:
        return CommandResult(exit_code=1)

    evaluator = BoolEvaluator(state, vfs)
    result = evaluator.eval_test(args)
    return CommandResult(exit_code=0 if result else 1)


class _ReadOpts:
    """Parsed options for the read builtin."""

    __slots__ = ("array_name", "delimiter", "max_chars", "raw_mode", "var_names")

    def __init__(self) -> None:
        self.raw_mode: bool = False
        self.array_name: str | None = None
        self.delimiter: str = "\n"
        self.max_chars: int | None = None
        self.var_names: list[str] = []


def _parse_read_opts(args: list[str]) -> _ReadOpts:  # noqa: C901
    """Parse read builtin flags and variable names from *args*."""
    opts = _ReadOpts()
    i = 0
    while i < len(args):
        arg = args[i]
        if not arg.startswith("-") or arg in {"-", "--"}:
            if arg == "--":
                i += 1
            opts.var_names.extend(args[i:])
            break

        # Walk flag characters (handles combined flags like -ra)
        j = 1
        while j < len(arg):
            ch = arg[j]
            if ch in {"r", "s"}:
                if ch == "r":
                    opts.raw_mode = True
                j += 1
            elif ch == "a":
                rest = arg[j + 1 :]
                if rest:
                    opts.array_name = rest
                else:
                    i += 1
                    if i < len(args):
                        opts.array_name = args[i]
                j = len(arg)
            elif ch == "d":
                rest = arg[j + 1 :]
                if rest:
                    opts.delimiter = rest[0]
                else:
                    i += 1
                    if i < len(args) and args[i]:
                        opts.delimiter = args[i][0]
                j = len(arg)
            elif ch == "n":
                rest = arg[j + 1 :]
                opts.max_chars = _try_int(
                    rest if rest else (args[i + 1] if i + 1 < len(args) else "")
                )
                if not rest:
                    i += 1
                j = len(arg)
            elif ch in {"p", "t"}:
                # -p PROMPT / -t TIMEOUT: consume argument, no-op
                if not arg[j + 1 :]:
                    i += 1
                j = len(arg)
            else:
                j += 1
        i += 1
    return opts


def _try_int(s: str) -> int | None:
    """Parse *s* as int, returning ``None`` on failure."""
    try:
        return int(s)
    except ValueError:
        return None


def builtin_read(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement read builtin with flag support.

    Supported flags:
      -r          Do not interpret backslash escapes
      -a ARRAY    Read into an array variable (split on IFS)
      -d DELIM    Use DELIM as the line delimiter instead of newline
      -p PROMPT   Display prompt (ignored in virtual shell)
      -n COUNT    Read at most COUNT characters
      -t TIMEOUT  Timeout (no-op in virtual shell)
      -s          Silent (no-op in virtual shell)
    """
    opts = _parse_read_opts(args)
    line = _read_input(io, opts.delimiter, opts.max_chars)

    if not line:
        return CommandResult(exit_code=1)

    # Strip the line terminator
    if opts.delimiter == "\n":
        line = line.rstrip("\n")

    # Backslash handling
    if not opts.raw_mode:
        line = _read_process_backslashes(line)

    # Determine IFS
    ifs = state.get_var("IFS")
    if ifs is None:
        ifs = " \t\n"

    # Assign to variables
    _read_assign(state, opts, line, ifs)
    return CommandResult(exit_code=0)


def _read_input(io: IOContext, delimiter: str, max_chars: int | None) -> str:
    """Read input from *io.stdin* respecting delimiter and char limit."""
    if max_chars is not None:
        return io.stdin.read(max_chars)
    if delimiter == "\n":
        return io.stdin.readline()
    # Read until delimiter character
    chars: list[str] = []
    while True:
        ch = io.stdin.read(1)
        if not ch or ch == delimiter:
            break
        chars.append(ch)
    return "".join(chars)


def _read_assign(state: ShellState, opts: _ReadOpts, line: str, ifs: str) -> None:
    """Assign the read line to the appropriate variables."""
    if opts.array_name is not None:
        parts = _ifs_split(line, ifs)
        state.set_array(opts.array_name, parts)
    elif not opts.var_names:
        state.set_var("REPLY", line)
    elif len(opts.var_names) == 1:
        state.set_var(opts.var_names[0], line)
    else:
        parts = _ifs_split_n(line, ifs, len(opts.var_names))
        for idx, name in enumerate(opts.var_names):
            state.set_var(name, parts[idx] if idx < len(parts) else "")


def _read_process_backslashes(line: str) -> str:
    """Process backslash escapes for read (without -r).

    A trailing backslash removes the newline (line continuation).
    Other backslashes escape the next character.
    """
    result: list[str] = []
    i = 0
    while i < len(line):
        if line[i] == "\\":
            if i + 1 < len(line):
                result.append(line[i + 1])
                i += 2
            else:
                # Trailing backslash — remove it (line continuation)
                i += 1
        else:
            result.append(line[i])
            i += 1
    return "".join(result)


def _ifs_split(line: str, ifs: str) -> list[str]:
    """Split a line on IFS characters, returning all fields.

    IFS whitespace characters (space, tab, newline) are treated specially:
    leading/trailing whitespace is trimmed, and runs of whitespace collapse.
    Non-whitespace IFS characters delimit exactly.
    """
    if not ifs:
        return [line] if line else []

    ifs_white = "".join(c for c in ifs if c in " \t\n")
    ifs_non_white = "".join(c for c in ifs if c not in " \t\n")

    if not ifs_non_white:
        return line.split()

    if not ifs_white:
        # IFS is only non-whitespace — split on those characters exactly
        parts = [line]
        for delim in ifs_non_white:
            new_parts: list[str] = []
            for part in parts:
                new_parts.extend(part.split(delim))
            parts = new_parts
        return parts

    # Mixed: strip IFS whitespace, then split on non-whitespace delimiters
    stripped = line.strip(ifs_white)
    if not stripped:
        return []
    parts = [stripped]
    for delim in ifs_non_white:
        new_parts: list[str] = []
        for part in parts:
            new_parts.extend(part.split(delim))
        parts = new_parts
    return [p.strip(ifs_white) for p in parts]


def _ifs_split_n(line: str, ifs: str, n: int) -> list[str]:
    """Split a line on IFS into at most *n* fields.

    The last field gets the remainder of the line (unsplit).
    """
    if n <= 1 or not ifs:
        return [line]

    ifs_white = "".join(c for c in ifs if c in " \t\n")

    parts: list[str] = []
    remaining = line

    # Strip leading IFS whitespace
    if ifs_white:
        remaining = remaining.lstrip(ifs_white)

    for _ in range(n - 1):
        if not remaining:
            break

        best_pos = _find_ifs_char(remaining, ifs)
        if best_pos == -1:
            break

        parts.append(remaining[:best_pos])
        remaining = remaining[best_pos + 1 :]
        if ifs_white:
            remaining = remaining.lstrip(ifs_white)

    # Strip trailing IFS whitespace from the remainder for the last field
    if ifs_white:
        remaining = remaining.rstrip(ifs_white)
    parts.append(remaining)

    return parts


def _find_ifs_char(s: str, ifs: str) -> int:
    """Return the index of the first IFS character in *s*, or -1."""
    for pos, c in enumerate(s):
        if c in ifs:
            return pos
    return -1


def builtin_shift(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement shift builtin."""
    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            io.stderr.write(f"shift: {args[0]}: numeric argument required\n")
            return CommandResult(exit_code=1)

    if n > len(state.positional_params):
        io.stderr.write("shift: shift count out of range\n")
        return CommandResult(exit_code=1)

    state.positional_params = state.positional_params[n:]
    return CommandResult(exit_code=0)


def builtin_return(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement return builtin."""
    code = 0
    if args:
        try:
            code = int(args[0])
        except ValueError:
            code = 1
    raise ReturnSignal(code)


class ReturnSignal(Exception):
    """Signal to return from a function or sourced script."""

    def __init__(self, exit_code: int) -> None:
        self.exit_code = exit_code
        super().__init__()


class BreakSignal(Exception):
    """Signal to break out of a loop.

    *levels* indicates how many enclosing loops to break out of (default 1).
    """

    def __init__(self, levels: int = 1) -> None:
        self.levels = levels
        super().__init__()


class ContinueSignal(Exception):
    """Signal to continue to the next iteration of a loop.

    *levels* indicates how many enclosing loops to skip to (default 1).
    """

    def __init__(self, levels: int = 1) -> None:
        self.levels = levels
        super().__init__()


def builtin_break(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement break builtin."""
    levels = 1
    if args:
        try:
            levels = int(args[0])
        except ValueError:
            io.stderr.write(f"break: {args[0]}: numeric argument required\n")
            return CommandResult(exit_code=1)
    levels = max(levels, 1)
    raise BreakSignal(levels)


def builtin_continue(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement continue builtin."""
    levels = 1
    if args:
        try:
            levels = int(args[0])
        except ValueError:
            io.stderr.write(f"continue: {args[0]}: numeric argument required\n")
            return CommandResult(exit_code=1)
    levels = max(levels, 1)
    raise ContinueSignal(levels)


def builtin_set(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement set builtin (basic option handling)."""
    if not args:
        for name, value in sorted(state.scope.flatten().items()):
            io.stdout.write(f"{name}={value}\n")
        return CommandResult(exit_code=0)

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            state.positional_params = list(args[i + 1 :])
            break
        elif arg.startswith("-") or arg.startswith("+"):
            enable = arg[0] == "-"
            for ch in arg[1:]:
                if ch == "o" and i + 1 < len(args):
                    i += 1
                    _apply_set_o(state, args[i], enable)
                else:
                    _apply_set_flag(state, ch, enable)
        i += 1

    return CommandResult(exit_code=0)


def _apply_set_flag(state: ShellState, ch: str, enable: bool) -> None:
    """Apply a single set flag character."""
    if ch == "e":
        state.options.errexit = enable
    elif ch == "u":
        state.options.nounset = enable
    elif ch == "x":
        state.options.xtrace = enable
    elif ch == "f":
        state.options.noglob = enable


def _apply_set_o(state: ShellState, opt: str, enable: bool) -> None:
    """Apply a set -o / +o option."""
    if opt == "pipefail":
        state.options.pipefail = enable


def builtin_local(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement local builtin — creates variables in the current scope frame."""
    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            state.scope.set_local(name, value)
        else:
            # Declare without value — create in current frame
            state.scope.set_local(arg, state.get_var(arg) or "")
    return CommandResult(exit_code=0)


def builtin_declare(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement declare builtin with -A support for associative arrays."""
    # Detect -A flag
    has_assoc = False
    remaining: list[str] = []
    for arg in args:
        if arg == "-A":
            has_assoc = True
        elif arg.startswith("-"):
            # Ignore other flags like -a, -i, -r, -x, etc.
            pass
        else:
            remaining.append(arg)

    if has_assoc:
        for arg in remaining:
            if "=" in arg:
                name, value_part = arg.split("=", 1)
                assoc = _parse_assoc_initializer(value_part)
                state.set_assoc(name, assoc)
            else:
                state.set_assoc(arg, {})
        return CommandResult(exit_code=0)

    return builtin_local(remaining, state, vfs, io)


def _parse_assoc_initializer(value: str) -> dict[str, str]:
    """Parse an associative array initializer like ``([key1]=val1 [key2]=val2)``.

    The value string may or may not be wrapped in parentheses.
    """
    result: dict[str, str] = {}
    text = value.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()

    # Parse [key]=value pairs
    i = 0
    while i < len(text):
        # Skip whitespace
        while i < len(text) and text[i] in (" ", "\t"):
            i += 1
        if i >= len(text):
            break
        if text[i] == "[":
            # Find closing ]
            j = text.index("]", i + 1)
            key = text[i + 1 : j]
            # Skip ]=
            i = j + 1
            if i < len(text) and text[i] == "=":
                i += 1
            # Read value until next space or [
            val_start = i
            while i < len(text) and text[i] not in (" ", "\t", "["):
                i += 1
            result[key] = text[val_start:i]
        else:
            # Skip non-bracket tokens
            while i < len(text) and text[i] not in (" ", "\t"):
                i += 1

    return result


# ---------------------------------------------------------------------------
# Module-level state for builtins that need persistent storage
# ---------------------------------------------------------------------------

_ALIASES: dict[str, str] = {}
_READONLY: set[str] = set()
_TRAPS: dict[str, str] = {}
_umask_value: int = 0o022


# ---------------------------------------------------------------------------
# alias / unalias
# ---------------------------------------------------------------------------


def builtin_alias(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement alias builtin.

    With no arguments, print all defined aliases.
    With NAME=VALUE arguments, define aliases.
    """
    if not args:
        for name, value in sorted(_ALIASES.items()):
            io.stdout.write(f"alias {name}='{value}'\n")
        return CommandResult(exit_code=0)

    rc = 0
    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            _ALIASES[name] = value
        elif arg in _ALIASES:
            io.stdout.write(f"alias {arg}='{_ALIASES[arg]}'\n")
        else:
            io.stderr.write(f"alias: {arg}: not found\n")
            rc = 1
    return CommandResult(exit_code=rc)


def builtin_unalias(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement unalias builtin.

    -a removes all aliases.  Otherwise remove named aliases.
    """
    if not args:
        io.stderr.write("unalias: usage: unalias [-a] name [name ...]\n")
        return CommandResult(exit_code=2)

    if "-a" in args:
        _ALIASES.clear()
        return CommandResult(exit_code=0)

    rc = 0
    for name in args:
        if name in _ALIASES:
            del _ALIASES[name]
        else:
            io.stderr.write(f"unalias: {name}: not found\n")
            rc = 1
    return CommandResult(exit_code=rc)


# ---------------------------------------------------------------------------
# type
# ---------------------------------------------------------------------------


def builtin_type(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement type builtin.

    Print what each NAME resolves to: alias, function, builtin, or not found.
    """
    if not args:
        return CommandResult(exit_code=0)

    rc = 0
    for name in args:
        if name in _ALIASES:
            io.stdout.write(f"{name} is aliased to '{_ALIASES[name]}'\n")
        elif name in state.functions:
            io.stdout.write(f"{name} is a function\n")
        elif name in BUILTINS:
            io.stdout.write(f"{name} is a shell builtin\n")
        else:
            io.stderr.write(f"type: {name}: not found\n")
            rc = 1
    return CommandResult(exit_code=rc)


# ---------------------------------------------------------------------------
# readonly
# ---------------------------------------------------------------------------


def builtin_readonly(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement readonly builtin.

    Mark variables as readonly.  With NAME=VALUE, set and mark.
    With no args, print all readonly variables.
    """
    if not args:
        for name in sorted(_READONLY):
            val = state.get_var(name) or ""
            io.stdout.write(f'declare -r {name}="{val}"\n')
        return CommandResult(exit_code=0)

    for arg in args:
        if "=" in arg:
            name, value = arg.split("=", 1)
            if name in _READONLY:
                io.stderr.write(f"readonly: {name}: readonly variable\n")
                return CommandResult(exit_code=1)
            state.set_var(name, value)
            _READONLY.add(name)
        else:
            _READONLY.add(arg)

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# let
# ---------------------------------------------------------------------------


def builtin_let(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement let builtin.

    Evaluate arithmetic expressions.  Return 0 if last result != 0, else 1.
    """
    if not args:
        io.stderr.write("let: expression expected\n")
        return CommandResult(exit_code=2)

    from agentsh.exec.arith_eval import ArithEvaluator

    arith = io.executor.arith_ev if io.executor is not None else ArithEvaluator(state)

    last_result = 0
    for expr in args:
        last_result = arith.eval_statement(expr)

    # let returns 0 if last result is non-zero, 1 if zero
    return CommandResult(exit_code=0 if last_result != 0 else 1)


# ---------------------------------------------------------------------------
# getopts
# ---------------------------------------------------------------------------


def builtin_getopts(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement getopts builtin (basic).

    Usage: getopts OPTSTRING NAME [ARGS...]
    Sets NAME to current option, OPTARG to argument, OPTIND to index.
    """
    if len(args) < 2:
        io.stderr.write("getopts: usage: getopts optstring name [arg ...]\n")
        return CommandResult(exit_code=2)

    optstring = args[0]
    varname = args[1]
    opt_args = args[2:] if len(args) > 2 else list(state.positional_params)

    optind_str = state.get_var("OPTIND") or "1"
    try:
        optind = int(optind_str)
    except ValueError:
        optind = 1

    # Convert to 0-based index (OPTIND is 1-based)
    idx = optind - 1

    if idx >= len(opt_args):
        state.set_var(varname, "?")
        return CommandResult(exit_code=1)

    current = opt_args[idx]
    if not current.startswith("-") or current in {"-", "--"}:
        state.set_var(varname, "?")
        return CommandResult(exit_code=1)

    opt_char = current[1] if len(current) > 1 else "?"

    if opt_char in optstring:
        state.set_var(varname, opt_char)
        # Check if this option expects an argument
        opt_pos = optstring.index(opt_char)
        if opt_pos + 1 < len(optstring) and optstring[opt_pos + 1] == ":":
            # Argument expected
            if len(current) > 2:
                # Argument is part of same string: -fVALUE
                state.set_var("OPTARG", current[2:])
            elif idx + 1 < len(opt_args):
                state.set_var("OPTARG", opt_args[idx + 1])
                optind += 1
            else:
                io.stderr.write(f"getopts: option requires an argument -- {opt_char}\n")
                state.set_var(varname, "?")
                state.set_var("OPTIND", str(optind + 1))
                return CommandResult(exit_code=0)
        else:
            state.set_var("OPTARG", "")
    else:
        io.stderr.write(f"getopts: illegal option -- {opt_char}\n")
        state.set_var(varname, "?")

    state.set_var("OPTIND", str(optind + 1))
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# hash
# ---------------------------------------------------------------------------


def builtin_hash(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement hash builtin (virtual no-op).

    -r clears the (virtual) hash table.  Named commands print 'not found'.
    """
    if not args or args == ["-r"]:
        return CommandResult(exit_code=0)

    rc = 0
    for name in args:
        if name == "-r":
            continue
        io.stderr.write(f"hash: {name}: not found\n")
        rc = 1
    return CommandResult(exit_code=rc)


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------

_BUILTIN_HELP: dict[str, str] = {
    "echo": "echo [-n] [arg ...] — write arguments to standard output",
    "printf": "printf FORMAT [ARG ...] — formatted output",
    "cd": "cd [dir] — change working directory",
    "pwd": "pwd — print working directory",
    "export": "export [NAME=VALUE ...] — set export attribute for variables",
    "unset": "unset [NAME ...] — unset variables",
    "true": "true — return success",
    "false": "false — return failure",
    "exit": "exit [N] — exit the shell",
    "test": "test EXPR — evaluate conditional expression",
    "[": "[ EXPR ] — evaluate conditional expression",
    "read": "read [NAME ...] — read a line from stdin",
    "shift": "shift [N] — shift positional parameters",
    "return": "return [N] — return from a function",
    "break": "break [N] — exit from a for, while, or until loop",
    "continue": "continue [N] — resume next iteration of a for, while, or until loop",
    "set": "set [option ...] [-- arg ...] — set shell options and positional params",
    "local": "local [NAME=VALUE ...] — define local variables",
    "declare": "declare [NAME=VALUE ...] — declare variables",
    "alias": "alias [NAME=VALUE ...] — define or display aliases",
    "unalias": "unalias [-a] NAME ... — remove aliases",
    "type": "type NAME ... — display information about command type",
    "readonly": "readonly [NAME=VALUE ...] — mark variables as readonly",
    "let": "let EXPR ... — evaluate arithmetic expressions",
    "getopts": "getopts OPTSTRING NAME [ARGS ...] — parse option arguments",
    "hash": "hash [-r] [NAME ...] — remember command locations (virtual no-op)",
    "help": "help [COMMAND] — display help for builtins",
    "eval": "eval [ARG ...] — execute arguments as a shell command",
    "exec": "exec COMMAND [ARG ...] — replace shell with command",
    "trap": "trap [ACTION] [SIGNAL ...] — trap signals (virtual)",
    "ulimit": "ulimit [-a] [-n N] — display or set resource limits (virtual)",
    "umask": "umask [MODE] — display or set file creation mask",
    "wait": "wait [PID ...] — wait for background jobs (no-op)",
    "jobs": "jobs — list background jobs (none in virtual shell)",
    "bg": "bg [JOB] — resume job in background (no-op)",
    "fg": "fg [JOB] — resume job in foreground (no-op)",
    "times": "times — display process times (virtual)",
    "source": "source FILE — execute commands from file",
    ".": ". FILE — execute commands from file",
}


def builtin_help(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement help builtin.

    With no args, list all builtins.  With a command name, show its help.
    """
    if not args:
        io.stdout.write("Shell builtins:\n")
        for name in sorted(BUILTINS):
            io.stdout.write(f"  {name}\n")
        return CommandResult(exit_code=0)

    rc = 0
    for name in args:
        if name in _BUILTIN_HELP:
            io.stdout.write(f"{_BUILTIN_HELP[name]}\n")
        elif name in BUILTINS:
            io.stdout.write(f"{name}: no help available\n")
        else:
            io.stderr.write(f"help: no help topics match '{name}'\n")
            rc = 1
    return CommandResult(exit_code=rc)


# ---------------------------------------------------------------------------
# eval
# ---------------------------------------------------------------------------


def builtin_eval(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement eval builtin.

    Join args with spaces, parse and execute as a script.
    """
    if not args:
        return CommandResult(exit_code=0)

    script = " ".join(args)

    if io.executor is None:
        io.stderr.write("eval: no executor available\n")
        return CommandResult(exit_code=1)

    from agentsh.parser.frontend import parse_script
    from agentsh.parser.normalize import normalize

    parse_result = parse_script(script)
    if parse_result.has_errors:
        io.stderr.write("eval: syntax error\n")
        return CommandResult(exit_code=2)

    program, _ = normalize(parse_result.root_node, script)
    return io.executor.execute_node(program, io)


# ---------------------------------------------------------------------------
# exec — run command in virtual shell (no real process replacement)
# ---------------------------------------------------------------------------


def builtin_exec(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement the exec builtin.

    In the virtual shell, just run the command (no process replacement).
    """
    if not args:
        return CommandResult(exit_code=0)

    if io.executor is None:
        io.stderr.write("exec: no executor available\n")
        return CommandResult(exit_code=1)

    return io.executor.execute_argv(args, io)


# ---------------------------------------------------------------------------
# trap
# ---------------------------------------------------------------------------


def builtin_trap(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement trap builtin (virtual).

    Store trap handlers but do not actually handle signals.
    With no args, print current traps.
    """
    if not args:
        for signal, action in sorted(_TRAPS.items()):
            io.stdout.write(f"trap -- '{action}' {signal}\n")
        return CommandResult(exit_code=0)

    if len(args) == 1:
        # Single arg — treat as signal name to reset
        _TRAPS.pop(args[0], None)
        return CommandResult(exit_code=0)

    action = args[0]
    for signal in args[1:]:
        if action == "-":
            _TRAPS.pop(signal, None)
        else:
            _TRAPS[signal] = action

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# ulimit
# ---------------------------------------------------------------------------


def builtin_ulimit(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement ulimit builtin (virtual).

    Print virtual resource limits.
    """
    if not args or "-a" in args:
        io.stdout.write("core file size          (blocks, -c) unlimited\n")
        io.stdout.write("data seg size           (kbytes, -d) unlimited\n")
        io.stdout.write("file size               (blocks, -f) unlimited\n")
        io.stdout.write("max locked memory       (kbytes, -l) unlimited\n")
        io.stdout.write("max memory size         (kbytes, -m) unlimited\n")
        io.stdout.write("open files                      (-n) 1024\n")
        io.stdout.write("pipe size            (512 bytes, -p) 8\n")
        io.stdout.write("stack size              (kbytes, -s) 8192\n")
        io.stdout.write("cpu time               (seconds, -t) unlimited\n")
        io.stdout.write("max user processes              (-u) unlimited\n")
        io.stdout.write("virtual memory          (kbytes, -v) unlimited\n")
        return CommandResult(exit_code=0)

    i = 0
    while i < len(args):
        if args[i] == "-n":
            if i + 1 < len(args):
                # Setting open files limit (virtual no-op)
                i += 2
            else:
                io.stdout.write("1024\n")
                i += 1
        else:
            i += 1

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# umask
# ---------------------------------------------------------------------------


def builtin_umask(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement umask builtin.

    Get or set the file creation mask.
    """
    global _umask_value  # noqa: PLW0603

    if not args:
        io.stdout.write(f"{_umask_value:04o}\n")
        return CommandResult(exit_code=0)

    try:
        _umask_value = int(args[0], 8)
    except ValueError:
        io.stderr.write(f"umask: {args[0]}: invalid octal number\n")
        return CommandResult(exit_code=1)

    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# wait / jobs / bg / fg
# ---------------------------------------------------------------------------


def builtin_wait(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement wait builtin (no-op — no background processes)."""
    return CommandResult(exit_code=0)


def builtin_jobs(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement jobs builtin (no background jobs in virtual shell)."""
    return CommandResult(exit_code=0)


def builtin_bg(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement bg builtin (no-op)."""
    return CommandResult(exit_code=0)


def builtin_fg(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement fg builtin (no-op)."""
    return CommandResult(exit_code=0)


# ---------------------------------------------------------------------------
# times
# ---------------------------------------------------------------------------


def builtin_times(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    """Implement times builtin (virtual — always zero)."""
    io.stdout.write("0m0.000s 0m0.000s\n")
    io.stdout.write("0m0.000s 0m0.000s\n")
    return CommandResult(exit_code=0)


# Registry of all builtins
BUILTINS: dict[str, BuiltinFn] = {
    "echo": builtin_echo,
    "printf": builtin_printf,
    "cd": builtin_cd,
    "pwd": builtin_pwd,
    "export": builtin_export,
    "unset": builtin_unset,
    "true": builtin_true,
    "false": builtin_false,
    "exit": builtin_exit,
    "test": builtin_test,
    "[": builtin_test,
    "read": builtin_read,
    "shift": builtin_shift,
    "return": builtin_return,
    "break": builtin_break,
    "continue": builtin_continue,
    "set": builtin_set,
    "local": builtin_local,
    "declare": builtin_declare,
    "alias": builtin_alias,
    "unalias": builtin_unalias,
    "type": builtin_type,
    "readonly": builtin_readonly,
    "let": builtin_let,
    "getopts": builtin_getopts,
    "hash": builtin_hash,
    "help": builtin_help,
    "eval": builtin_eval,
    "exec": builtin_exec,
    "trap": builtin_trap,
    "ulimit": builtin_ulimit,
    "umask": builtin_umask,
    "wait": builtin_wait,
    "jobs": builtin_jobs,
    "bg": builtin_bg,
    "fg": builtin_fg,
    "times": builtin_times,
}
