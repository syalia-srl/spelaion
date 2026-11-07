"""Stream processing commands: sed, awk."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agentsh.commands._io import read_text, read_text_inputs
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

if TYPE_CHECKING:
    from agentsh.exec.redirs import IOContext
    from agentsh.runtime.state import ShellState
    from agentsh.vfs.filesystem import VirtualFilesystem


# ---------------------------------------------------------------------------
# sed
# ---------------------------------------------------------------------------


@command("sed")
def cmd_sed(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    suppress = False
    in_place = False
    scripts: list[str] = []
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-n":
            suppress = True
        elif a == "-i":
            in_place = True
        elif a == "-e" and i + 1 < len(args):
            i += 1
            scripts.append(args[i])
        elif a == "--":
            files.extend(args[i + 1 :])
            break
        elif not a.startswith("-") or (not scripts and not files):
            if not scripts:
                scripts.append(a)
            else:
                files.append(a)
        else:
            files.append(a)
        i += 1

    if not scripts:
        io.stderr.write("sed: no script given\n")
        return CommandResult(exit_code=2)

    # Parse all sed commands
    sed_cmds: list[_SedCommand] = []
    for script in scripts:
        sed_cmds.extend(_parse_sed_script(script))

    # Read input
    if not files:
        files = ["-"]
    for f in files:
        content = read_text(f, state, vfs, io, "sed")
        if content is None:
            continue
        result = _sed_process(content, sed_cmds, suppress)
        if in_place and f != "-":
            abs_path = vfs.resolve(f, state.cwd)
            vfs.write(abs_path, result.encode("utf-8"))
        else:
            io.stdout.write(result)

    return CommandResult(exit_code=0)


class _SedCommand:
    """A parsed sed command."""

    def __init__(
        self,
        addr_start: str | int | None = None,
        addr_end: str | int | None = None,
        cmd: str = "",
        pattern: str = "",
        replacement: str = "",
        flags: str = "",
    ) -> None:
        self.addr_start = addr_start
        self.addr_end = addr_end
        self.cmd = cmd
        self.pattern = pattern
        self.replacement = replacement
        self.flags = flags


def _parse_sed_script(script: str) -> list[_SedCommand]:
    """Parse a sed script into commands."""
    commands: list[_SedCommand] = []
    # Split on ; but be careful with s/// which may contain ;
    for raw_part in _split_sed_commands(script):
        part = raw_part.strip()
        if not part:
            continue
        cmd = _parse_single_sed_command(part)
        if cmd:
            commands.append(cmd)
    return commands


def _split_sed_commands(script: str) -> list[str]:
    """Split sed script on semicolons, respecting s/// delimiters."""
    parts: list[str] = []
    current: list[str] = []
    in_sub = False
    delim_count = 0
    delim_char = "/"

    i = 0
    while i < len(script):
        ch = script[i]
        if in_sub:
            current.append(ch)
            if ch == "\\" and i + 1 < len(script):
                i += 1
                current.append(script[i])
            elif ch == delim_char:
                delim_count += 1
                if delim_count >= 3:
                    # Consume trailing flags
                    i += 1
                    while i < len(script) and script[i] in "gip0123456789":
                        current.append(script[i])
                        i += 1
                    in_sub = False
                    continue
        elif ch == "s" and i + 1 < len(script) and not script[i + 1].isalnum():
            in_sub = True
            delim_count = 0
            delim_char = script[i + 1]
            current.append(ch)
        elif ch == ";":
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1

    if current:
        parts.append("".join(current))
    return parts


def _parse_single_sed_command(text: str) -> _SedCommand | None:
    """Parse a single sed command with optional address."""
    text = text.strip()
    if not text:
        return None

    addr_start: str | int | None = None
    addr_end: str | int | None = None
    pos = 0

    # Parse address
    addr_start, pos = _parse_sed_address(text, pos)
    if pos < len(text) and text[pos] == ",":
        pos += 1
        addr_end, pos = _parse_sed_address(text, pos)

    rest = text[pos:].strip()
    if not rest:
        return None

    if rest[0] == "s" and len(rest) > 1 and not rest[1].isalnum():
        # Substitution command
        delim = rest[1]
        parts = _split_on_delim(rest[2:], delim)
        if len(parts) >= 2:
            pattern = parts[0]
            replacement = parts[1]
            flags = parts[2] if len(parts) > 2 else ""
            return _SedCommand(
                addr_start=addr_start,
                addr_end=addr_end,
                cmd="s",
                pattern=pattern,
                replacement=replacement,
                flags=flags,
            )
    elif rest[0] == "d":
        return _SedCommand(addr_start=addr_start, addr_end=addr_end, cmd="d")
    elif rest[0] == "p":
        return _SedCommand(addr_start=addr_start, addr_end=addr_end, cmd="p")
    elif rest[0] == "q":
        return _SedCommand(addr_start=addr_start, addr_end=addr_end, cmd="q")

    return None


def _parse_sed_address(text: str, pos: int) -> tuple[str | int | None, int]:
    """Parse a sed address (line number or /regex/)."""
    if pos >= len(text):
        return None, pos

    if text[pos] == "$":
        return "$", pos + 1

    if text[pos].isdigit():
        end = pos
        while end < len(text) and text[end].isdigit():
            end += 1
        return int(text[pos:end]), end

    if text[pos] == "/":
        end = pos + 1
        while end < len(text) and text[end] != "/":
            if text[end] == "\\" and end + 1 < len(text):
                end += 1
            end += 1
        if end < len(text):
            return text[pos + 1 : end], end + 1
        return text[pos + 1 : end], end

    return None, pos


def _split_on_delim(text: str, delim: str) -> list[str]:
    """Split text on delimiter, handling backslash escapes."""
    parts: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            if text[i + 1] == delim:
                current.append(delim)
                i += 2
                continue
            current.append(text[i])
            current.append(text[i + 1])
            i += 2
        elif text[i] == delim:
            parts.append("".join(current))
            current = []
            i += 1
        else:
            current.append(text[i])
            i += 1
    parts.append("".join(current))
    return parts


def _address_matches(
    addr: str | int | None, lineno: int, line: str, total_lines: int
) -> bool:
    if addr is None:
        return True
    if isinstance(addr, int):
        return lineno == addr
    if addr == "$":
        return lineno == total_lines
    # Regex address
    try:
        return bool(re.search(addr, line))
    except re.error:
        return False


def _sed_process(content: str, commands: list[_SedCommand], suppress: bool) -> str:  # noqa: C901
    """Process content through sed commands."""
    lines = content.splitlines(keepends=True)
    total = len(lines)
    output: list[str] = []
    in_range: dict[int, bool] = {}  # Track range state per command index

    for lineno_0, raw_line in enumerate(lines):
        lineno = lineno_0 + 1
        line = raw_line
        deleted = False
        printed_extra = False
        quit_after = False

        for cmd_idx, cmd in enumerate(commands):
            # Check address match
            if cmd.addr_end is not None:
                # Range address
                if not in_range.get(cmd_idx, False):
                    if _address_matches(cmd.addr_start, lineno, line, total):
                        in_range[cmd_idx] = True
                    else:
                        continue
                elif _address_matches(cmd.addr_end, lineno, line, total):
                    in_range[cmd_idx] = False
            elif cmd.addr_start is not None and not _address_matches(
                cmd.addr_start, lineno, line, total
            ):
                continue

            if cmd.cmd == "s":
                count = 0 if "g" in cmd.flags else 1
                re_flags = re.IGNORECASE if "i" in cmd.flags else 0
                try:
                    new_line = re.sub(
                        cmd.pattern,
                        cmd.replacement,
                        line,
                        count=count,
                        flags=re_flags,
                    )
                except re.error:
                    new_line = line
                if new_line != line and "p" in cmd.flags and suppress:
                    output.append(new_line)
                    printed_extra = True
                line = new_line
            elif cmd.cmd == "d":
                deleted = True
                break
            elif cmd.cmd == "p":
                output.append(line)
                printed_extra = True
            elif cmd.cmd == "q":
                if not suppress or printed_extra:
                    output.append(line)
                quit_after = True
                break

        if quit_after:
            break

        if not deleted and not suppress:
            output.append(line)

    return "".join(output)


# ---------------------------------------------------------------------------
# awk
# ---------------------------------------------------------------------------


@command("awk")
def cmd_awk(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, io: IOContext
) -> CommandResult:
    field_sep: str | None = None
    variables: dict[str, str] = {}
    program: str | None = None
    files: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "-F" and i + 1 < len(args):
            i += 1
            field_sep = args[i]
        elif a.startswith("-F") and len(a) > 2:
            field_sep = a[2:]
        elif a == "-v" and i + 1 < len(args):
            i += 1
            if "=" in args[i]:
                k, v = args[i].split("=", 1)
                variables[k] = v
        elif program is None:
            program = a
        else:
            files.append(a)
        i += 1

    if program is None:
        io.stderr.write("awk: missing program\n")
        return CommandResult(exit_code=2)

    content, _ = read_text_inputs(files, state, vfs, io, "awk")

    interp = _AwkInterpreter(program, field_sep, variables)
    output = interp.run(content)
    io.stdout.write(output)
    return CommandResult(exit_code=0)


def _awk_compare(lval: str, rval: str, op: str) -> bool:
    """Compare two awk values, trying numeric then string."""
    import operator

    ops = {
        "==": operator.eq,
        "!=": operator.ne,
        ">": operator.gt,
        "<": operator.lt,
        ">=": operator.ge,
        "<=": operator.le,
    }
    fn = ops[op]
    try:
        return fn(float(lval), float(rval))  # type: ignore[arg-type]
    except ValueError:
        return fn(lval, rval)  # type: ignore[arg-type]


class _AwkInterpreter:
    """Mini awk interpreter supporting common patterns."""

    def __init__(
        self,
        program: str,
        field_sep: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> None:
        self.field_sep = field_sep
        self.vars: dict[str, str] = dict(variables or {})
        self.rules = _parse_awk_program(program)
        self.output: list[str] = []

    def run(self, content: str) -> str:
        lines = content.splitlines()
        self.vars["NR"] = "0"
        self.vars["NF"] = "0"
        self.vars["FS"] = self.field_sep or " "
        self.vars["OFS"] = " "
        self.vars["ORS"] = "\n"

        # Execute BEGIN rules
        for rule in self.rules:
            if rule.pattern == "BEGIN":
                self._exec_action(rule.action, [], "")

        for nr, line in enumerate(lines, 1):
            self.vars["NR"] = str(nr)
            self.vars["$0"] = line
            fields = self._split_line(line)
            self.vars["NF"] = str(len(fields))
            for fi, fv in enumerate(fields, 1):
                self.vars[f"${fi}"] = fv

            for rule in self.rules:
                if rule.pattern in ("BEGIN", "END"):
                    continue
                if self._pattern_matches(rule.pattern, line, fields):
                    self._exec_action(rule.action, fields, line)

        # Execute END rules
        for rule in self.rules:
            if rule.pattern == "END":
                fields = self._split_line(self.vars.get("$0", ""))
                self._exec_action(rule.action, fields, self.vars.get("$0", ""))

        return "".join(self.output)

    def _split_line(self, line: str) -> list[str]:
        if self.field_sep and self.field_sep != " ":
            return line.split(self.field_sep)
        return line.split()

    def _pattern_matches(self, pattern: str, line: str, fields: list[str]) -> bool:
        if not pattern:
            return True
        # /regex/ pattern
        if pattern.startswith("/") and pattern.endswith("/"):
            try:
                return bool(re.search(pattern[1:-1], line))
            except re.error:
                return False
        # Simple condition: NR==N, $N=="val", $N~/regex/
        return self._eval_condition(pattern, fields, line)

    def _eval_condition(self, cond: str, fields: list[str], line: str) -> bool:
        cond = cond.strip()

        # $N ~ /regex/
        m = re.match(r"(\$\d+)\s*~\s*/(.*?)/", cond)
        if m:
            val = self._get_field(m.group(1), fields, line)
            try:
                return bool(re.search(m.group(2), val))
            except re.error:
                return False

        # $N !~ /regex/
        m = re.match(r"(\$\d+)\s*!~\s*/(.*?)/", cond)
        if m:
            val = self._get_field(m.group(1), fields, line)
            try:
                return not bool(re.search(m.group(2), val))
            except re.error:
                return False

        # Comparison: expr OP expr (order matters: >= before >)
        for op in ("==", "!=", ">=", "<=", ">", "<"):
            if op in cond:
                left, right = cond.split(op, 1)
                lval = self._eval_expr(left.strip(), fields, line)
                rval = self._eval_expr(right.strip(), fields, line)
                return _awk_compare(lval, rval, op)
        return False

    def _get_field(self, ref: str, fields: list[str], line: str) -> str:
        if ref == "$0":
            return line
        if ref.startswith("$"):
            try:
                idx = int(ref[1:])
                return fields[idx - 1] if 0 < idx <= len(fields) else ""
            except (ValueError, IndexError):
                return ""
        return self.vars.get(ref, ref)

    def _eval_expr(self, expr: str, fields: list[str], line: str) -> str:
        expr = expr.strip()
        # Remove surrounding quotes
        if (expr.startswith('"') and expr.endswith('"')) or (
            expr.startswith("'") and expr.endswith("'")
        ):
            return expr[1:-1]
        if expr.startswith("$"):
            return self._get_field(expr, fields, line)
        if expr in self.vars:
            return self.vars[expr]
        return expr

    def _exec_action(self, action: str, fields: list[str], line: str) -> None:
        """Execute an awk action block."""
        statements = _split_awk_statements(action)
        for raw_stmt in statements:
            stmt = raw_stmt.strip()
            if not stmt:
                continue
            self._exec_statement(stmt, fields, line)

    def _exec_statement(self, stmt: str, fields: list[str], line: str) -> None:
        stmt = stmt.strip()

        # Variable assignment: var = expr
        m = re.match(r"^([a-zA-Z_]\w*)\s*=\s*(.+)$", stmt)
        if m and m.group(1) not in ("print", "printf", "if", "for", "while"):
            name = m.group(1)
            val = self._eval_awk_expr(m.group(2), fields, line)
            self.vars[name] = val
            return

        # print statement
        if stmt in ("print", "print $0"):
            self.output.append(line + self.vars.get("ORS", "\n"))
            return

        m = re.match(r"^print\s+(.*)", stmt)
        if m:
            self._do_print(m.group(1), fields, line)
            return

        # printf statement
        m = re.match(r"^printf\s+(.*)", stmt)
        if m:
            self._do_printf(m.group(1), fields, line)
            return

        # $N++ or var++
        m = re.match(r"^(\$?\w+)\+\+$", stmt)
        if m:
            ref = m.group(1)
            val = self._eval_awk_expr(ref, fields, line)
            try:
                self.vars[ref] = str(int(val) + 1)
            except ValueError:
                self.vars[ref] = "1"
            return

        # $N = expr
        m = re.match(r"^(\$\d+)\s*=\s*(.+)$", stmt)
        if m:
            self.vars[m.group(1)] = self._eval_awk_expr(m.group(2), fields, line)
            return

    def _do_print(self, expr_str: str, fields: list[str], line: str) -> None:
        ofs = self.vars.get("OFS", " ")
        ors = self.vars.get("ORS", "\n")

        # Split on commas, respecting quotes
        parts = _split_awk_print_args(expr_str)
        vals: list[str] = []
        for part in parts:
            vals.append(self._eval_awk_expr(part.strip(), fields, line))

        self.output.append(ofs.join(vals) + ors)

    def _do_printf(self, expr_str: str, fields: list[str], line: str) -> None:
        parts = _split_awk_print_args(expr_str)
        if not parts:
            return
        fmt = self._eval_awk_expr(parts[0].strip(), fields, line)
        fmt_args = [self._eval_awk_expr(p.strip(), fields, line) for p in parts[1:]]
        result = _awk_sprintf(fmt, fmt_args)
        self.output.append(result)

    def _eval_awk_expr(self, expr: str, fields: list[str], line: str) -> str:
        expr = expr.strip()
        if not expr:
            return ""

        # String literal
        if expr.startswith('"') and expr.endswith('"'):
            return expr[1:-1].replace("\\n", "\n").replace("\\t", "\t")

        # Field reference $N
        if expr.startswith("$"):
            return self._get_field(expr, fields, line)

        # String concatenation: "str" var "str" ...
        if '"' in expr:
            return self._eval_concat(expr, fields, line)

        # Arithmetic: split by lowest precedence first (+/-), then (*/%),
        # scanning right-to-left for left-associativity.
        for ops in (("+", "-"), ("*", "/", "%")):
            for op in ops:
                idx = expr.rfind(op)
                if 0 < idx < len(expr) - 1:
                    left = expr[:idx].strip()
                    right = expr[idx + 1 :].strip()
                    try:
                        lv = float(self._eval_awk_expr(left, fields, line))
                        rv = float(self._eval_awk_expr(right, fields, line))
                    except (ValueError, ZeroDivisionError):
                        continue
                    if op == "+":
                        val = lv + rv
                    elif op == "-":
                        val = lv - rv
                    elif op == "*":
                        val = lv * rv
                    elif op == "/":
                        val = lv / rv if rv != 0 else 0.0
                    else:
                        val = lv % rv if rv != 0 else 0.0
                    if isinstance(val, float) and val.is_integer():
                        return str(int(val))
                    return str(val)
            # Only try higher-precedence ops if no lower ones found
            # (but we need to check all ops at each level)

        # Variable lookup
        if expr in self.vars:
            return self.vars[expr]

        return expr

    def _eval_concat(self, expr: str, fields: list[str], line: str) -> str:
        """Evaluate string concatenation."""
        result: list[str] = []
        i = 0
        while i < len(expr):
            if expr[i] == '"':
                end = expr.find('"', i + 1)
                if end == -1:
                    end = len(expr)
                s = expr[i + 1 : end]
                s = s.replace("\\n", "\n").replace("\\t", "\t")
                result.append(s)
                i = end + 1
            elif expr[i] in (" ", "\t"):
                i += 1
            else:
                end = i
                while end < len(expr) and expr[end] not in (" ", "\t", '"'):
                    end += 1
                token = expr[i:end].strip()
                if token:
                    result.append(self._eval_awk_expr(token, fields, line))
                i = end
        return "".join(result)


class _AwkRule:
    def __init__(self, pattern: str, action: str) -> None:
        self.pattern = pattern
        self.action = action


def _parse_awk_program(program: str) -> list[_AwkRule]:  # noqa: C901
    """Parse an awk program into rules."""
    rules: list[_AwkRule] = []
    program = program.strip()
    pos = 0

    while pos < len(program):
        # Skip whitespace and semicolons
        while pos < len(program) and program[pos] in (" ", "\t", "\n", ";"):
            pos += 1
        if pos >= len(program):
            break

        # Parse pattern
        pattern = ""
        if program[pos:].startswith("BEGIN"):
            pattern = "BEGIN"
            pos += 5
        elif program[pos:].startswith("END"):
            pattern = "END"
            pos += 3
        elif program[pos] == "/":
            end = (
                program.index("/", pos + 1)
                if "/" in program[pos + 1 :]
                else len(program)
            )
            pattern = program[pos : end + 1]
            pos = end + 1
        elif program[pos] != "{":
            # Condition pattern
            end = pos
            while end < len(program) and program[end] != "{":
                end += 1
            pattern = program[pos:end].strip()
            pos = end

        # Skip whitespace
        while pos < len(program) and program[pos] in (" ", "\t", "\n"):
            pos += 1

        # Parse action
        if pos < len(program) and program[pos] == "{":
            depth = 1
            start = pos + 1
            pos += 1
            while pos < len(program) and depth > 0:
                if program[pos] == "{":
                    depth += 1
                elif program[pos] == "}":
                    depth -= 1
                elif program[pos] == '"':
                    pos += 1
                    while pos < len(program) and program[pos] != '"':
                        if program[pos] == "\\":
                            pos += 1
                        pos += 1
                pos += 1
            action = program[start : pos - 1].strip()
        else:
            action = "print $0"

        rules.append(_AwkRule(pattern, action))

    return rules


def _split_awk_statements(action: str) -> list[str]:
    """Split awk action into statements on ; and newlines."""
    stmts: list[str] = []
    current: list[str] = []
    in_str = False
    i = 0
    while i < len(action):
        ch = action[i]
        if in_str:
            current.append(ch)
            if ch == "\\" and i + 1 < len(action):
                i += 1
                current.append(action[i])
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            current.append(ch)
        elif ch in (";", "\n"):
            stmts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        stmts.append("".join(current))
    return stmts


def _split_awk_print_args(expr: str) -> list[str]:
    """Split print arguments on commas, respecting quotes."""
    parts: list[str] = []
    current: list[str] = []
    in_str = False
    depth = 0
    i = 0
    while i < len(expr):
        ch = expr[i]
        if in_str:
            current.append(ch)
            if ch == "\\" and i + 1 < len(expr):
                # Consume the escaped character immediately
                i += 1
                current.append(expr[i])
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
        i += 1
    if current:
        parts.append("".join(current))
    return parts


def _awk_sprintf(fmt: str, args: list[str]) -> str:
    """Simple awk sprintf implementation."""
    result: list[str] = []
    arg_idx = 0
    i = 0
    while i < len(fmt):
        if fmt[i] == "\\" and i + 1 < len(fmt):
            esc = fmt[i + 1]
            if esc == "n":
                result.append("\n")
            elif esc == "t":
                result.append("\t")
            elif esc == "\\":
                result.append("\\")
            else:
                result.append("\\" + esc)
            i += 2
        elif fmt[i] == "%" and i + 1 < len(fmt):
            # Parse format spec
            i += 1
            spec = ""
            while i < len(fmt) and fmt[i] in "0123456789.-+":
                spec += fmt[i]
                i += 1
            if i < len(fmt):
                conv = fmt[i]
                arg = args[arg_idx] if arg_idx < len(args) else ""
                arg_idx += 1
                if conv == "s":
                    result.append(arg)
                elif conv == "d":
                    try:
                        result.append(str(int(float(arg))))
                    except ValueError:
                        result.append("0")
                elif conv == "f":
                    try:
                        result.append(f"{float(arg):.6f}")
                    except ValueError:
                        result.append("0.000000")
                elif conv == "%":
                    result.append("%")
                    arg_idx -= 1
                else:
                    result.append("%" + spec + conv)
                i += 1
        else:
            result.append(fmt[i])
            i += 1
    return "".join(result)
