# Adding a command to the shell

An agent cleaning a table writes `join left.txt right.txt` to pair two sorted
files on their first field. spelaion answers `spelaion: join: command not
found` with status 127. The shell has 128 commands and `join` is not one of
them. The agent cannot install coreutils either: the shell starts no host
program. The command has to be written in Python and shipped with spelaion.

This chapter writes `join`, registers it, and shows where the file, the test
and the battery case go. `rev` and `nl` already exist, so the command it adds
is genuinely missing.

## The registry

Every virtual command is a Python function in `src/spelaion/commands/` that
matches the type in `src/spelaion/commands/_registry.py`:

```python
CommandFn = Callable[
    ["list[str]", "ShellState", "Filesystem", "IOContext"],
    "CommandResult",
]
```

The four arguments are everything the shell gives a command:

| argument | what it holds |
|---|---|
| `args` | the words after the command name, already expanded and dequoted |
| `state` | the shell's `ShellState`: `cwd`, variables, functions, `last_status` |
| `vfs` | the `Filesystem` the call runs over, either a `MountFs` or the in-memory tree |
| `io` | the `IOContext`: its `stdin`, `stdout` and `stderr` for this call |

`@command("name")` stores the function in `COMMANDS` under each name it is
given. The decorator runs when the module is imported. `src/spelaion/commands/__init__.py`
imports every command module for that side effect, and the shell reads the
dictionary when it dispatches a name.

The first step is to check what the installed shell has. The registry is the
authority, and it is one dictionary:

```{python}
from spelaion.commands import COMMANDS

print("commands:", len(COMMANDS))
for name in ("rev", "nl", "join", "unexpand"):
    print(f"{name:9} {'registered' if name in COMMANDS else 'missing'}")
```

`rev` and `nl` are registered; `join` and `unexpand` are missing. The chapter
builds `join` because it reads two inputs, combines them and returns a status,
which touches every part of the interface.

## The function

A command reads its inputs through the `Filesystem`, never with `open`. The
path the agent typed is relative to the shell's working directory, so it goes
through `vfs.resolve(name, state.cwd)` first. `vfs.read` returns bytes. A name
of `-` stands for standard input, which is `io.stdin`. Output goes to
`io.stdout` and a diagnostic to `io.stderr`, and the returned `CommandResult`
carries the exit status:

```{python export=examples/adding_a_command.py}
from __future__ import annotations

from io import StringIO

from spelaion.commands import COMMANDS
from spelaion.commands._io import split_flags
from spelaion.commands._registry import command
from spelaion.exec.redirs import IOContext
from spelaion.runtime.result import CommandResult
from spelaion.runtime.state import ShellState
from spelaion.vfs.base import Filesystem
from spelaion.vfs.filesystem import VirtualFilesystem


def _rows(
    name: str,
    field: int,
    sep: str | None,
    state: ShellState,
    vfs: Filesystem,
    io: IOContext,
) -> list[tuple[str, list[str]]] | None:
    """Read one input as (join key, fields) pairs, or None after an error."""
    if name == "-":
        text = io.stdin.read()
    else:
        path = vfs.resolve(name, state.cwd)
        try:
            text = vfs.read(path).decode("utf-8", errors="replace")
        except FileNotFoundError:
            io.stderr.write(f"join: {name}: No such file or directory\n")
            return None
        except IsADirectoryError:
            io.stderr.write(f"join: {name}: Is a directory\n")
            return None
        except OSError as error:
            io.stderr.write(f"join: {name}: {error.strerror or error}\n")
            return None
    rows: list[tuple[str, list[str]]] = []
    for line in text.splitlines():
        cols = line.split() if sep is None else line.split(sep)
        if not cols:
            continue
        key = cols[field - 1] if field <= len(cols) else ""
        rows.append((key, cols))
    return rows


def _options(
    args: list[str], io: IOContext
) -> tuple[str | None, list[int], set[str], list[str]] | None:
    """Parse the options, or write the error and return None."""
    args = split_flags(args, "a", "t12")
    sep: str | None = None
    keys = [1, 1]
    unpaired: set[str] = set()
    names: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-t", "-1", "-2", "-a") and i + 1 < len(args):
            i += 1
            value = args[i]
            if arg == "-t":
                sep = value
            elif arg == "-a":
                if value not in ("1", "2"):
                    io.stderr.write(f"join: invalid file number: {value}\n")
                    return None
                unpaired.add(value)
            else:
                try:
                    number = int(value)
                except ValueError:
                    number = 0
                if number < 1:
                    io.stderr.write(f"join: invalid field number: {value}\n")
                    return None
                keys[0 if arg == "-1" else 1] = number
        elif arg.startswith("-") and arg != "-":
            io.stderr.write(f"join: invalid option: {arg}\n")
            return None
        else:
            names.append(arg)
        i += 1
    return sep, keys, unpaired, names


@command("join")
def cmd_join(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    parsed = _options(args, io)
    if parsed is None:
        return CommandResult(exit_code=1)
    sep, keys, unpaired, names = parsed

    if len(names) != 2:
        io.stderr.write(
            "join: usage: join [-t SEP] [-1 N] [-2 N] [-a 1|2] FILE1 FILE2\n"
        )
        return CommandResult(exit_code=1)

    left = _rows(names[0], keys[0], sep, state, vfs, io)
    right = _rows(names[1], keys[1], sep, state, vfs, io)
    if left is None or right is None:
        return CommandResult(exit_code=1)

    separator = " " if sep is None else sep
    matched: set[str] = set()
    for key, left_fields in left:
        partners = [cols for other_key, cols in right if other_key == key]
        if partners:
            matched.add(key)
            for right_fields in partners:
                joined = (
                    left_fields + right_fields[: keys[1] - 1] + right_fields[keys[1] :]
                )
                io.stdout.write(separator.join(joined) + "\n")
        elif "1" in unpaired:
            io.stdout.write(separator.join(left_fields) + "\n")

    if "2" in unpaired:
        for key, right_fields in right:
            if key not in matched:
                io.stdout.write(separator.join(right_fields) + "\n")

    return CommandResult(exit_code=0)


```

The command supports the options that matter for the job: `-t SEP` for a field
separator other than blanks, `-1 N` and `-2 N` to choose the join field of
each input, and `-a 1` or `-a 2` to print the lines that had no partner.
`split_flags` rewrites the joined forms `-t,` and `-a1` into two words before
the loop, which is the same helper `sort` and `uniq` use.

Two details of the interface are easy to get wrong. `CommandResult` has
`stdout` and `stderr` fields of its own, but a command's output is the text it
wrote to `io`; the evaluator reads those streams and ignores the fields. Only
`exit_code` travels back. And the `io` streams are the ones a call bounds, so
a command that writes more than the call allows is truncated like any other
([Bounding every call](bounding-every-call.html)).

The rows keep the order of the files. GNU `join` requires sorted input and
writes in key order, which agrees with this code when the inputs are sorted,
as they are in the example below.

## Why the running shell does not see it

The block above imported the decorator and registered `join` in this process.
`Bash` is the in-memory shell from [Testing shell scripts with
Bash](testing-shell-scripts-with-bash.html), and it dispatches through the same resolver as
a `Sandbox`, so it should run the command:

```{python continue}
from spelaion import Bash

bash = Bash(
    files={
        "/left.txt": "1 alpha\n2 beta\n3 gamma\n",
        "/right.txt": "1 one\n3 three\n4 four\n",
    },
    cwd="/",
)
r = bash.run("join left.txt right.txt")
print(repr(r.stdout))
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

It is not found. The cause is a name set built once at import.
`src/spelaion/semantics/resolve.py` computes

```python
BUILTIN_NAMES: frozenset[str] = _SHELL_BUILTINS | frozenset(COMMANDS.keys())
```

when the module is first imported. spelaion imports that module while the
package loads, so by the time the block runs, `BUILTIN_NAMES` is a frozenset
that already exists. The decorator adds the name to `COMMANDS` and
`BUILTIN_NAMES` does not change. The evaluator asks `resolve_command`, gets
`not_found`, and never looks in `COMMANDS`.

Two other names read `COMMANDS` directly, so they disagree with execution:

```{python continue}
print(bash.run("type join").stdout, end="")
print(bash.run("command -v join").stdout, end="")
```

`type` says `join is a command` and `command -v` prints the name, while
running it fails. The two answers should agree; today they do not, which is a
bug to watch. Treat the decorator as a hook for import time only: a command
added after spelaion has loaded is registered but cannot run.

A `Sandbox` is further away. It runs its shell in a child Python process, and
that child imports `spelaion.commands` itself, so a dictionary changed in your
process is not the dictionary the child reads. Even `type` knows nothing about
the command there:

```{python continue}
import shutil
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

folder = Path(tempfile.mkdtemp())
(folder / "left.txt").write_text("1 alpha\n")
(folder / "right.txt").write_text("1 one\n")
sb = Sandbox([Mount("/work", host=folder)], cwd="/work")
print(repr(sb.bash("join left.txt right.txt").stdout))
print(sb.bash("type join").stderr, end="")
sb.close()
shutil.rmtree(folder)
```

When one product needs a command at runtime, in its own process, the
supported route is a host command, which [Host
commands](giving-the-agent-powers-with-host-commands.html) covers. For a command every agent should have,
the change belongs in the package.

## Where the file goes

Put the function in a module under `src/spelaion/commands/` and make sure the
package imports it. `src/spelaion/commands/__init__.py` is the list that
triggers registration:

```python
"""Busybox-style virtual commands — pure in-memory, all VFS."""

# Import all command modules to trigger @command registration.
# pyright: reportUnusedImport=false
from spelaion.commands import (  # noqa: F401
    archive,
    diff_cmd,
    encoding,
    fileio,
    fileops,
    math_cmd,
    modern_search,
    pathutil,
    python_cmd,
    search,
    stream,
    structured,
    sysinfo,
    sysutil,
    textproc,
    textproc2,
    trivial,
)
from spelaion.commands._registry import COMMANDS

__all__ = ["COMMANDS"]
```

`join` fits `textproc2.py`, next to `fold`, `expand` and `tsort`, and that
module is already in the list. Add the name to the module's docstring as the
other entries do. A command that needs a module of its own is the same
procedure with one more name in the import list, and the import must be there
before `spelaion.semantics.resolve` is imported; the package order already
guarantees it.

From a fresh process, the registered dictionary and the resolver then agree:

```bash
uv run python -c "from spelaion.commands import COMMANDS; print('join' in COMMANDS)"
uv run python -c "from spelaion.semantics.resolve import BUILTIN_NAMES; print('join' in BUILTIN_NAMES)"
```

Both print `True`, and `Bash` and a `Sandbox` run the command.

A new import between packages is what `tach` tracks. `tach.toml` declares the
allowed edges and `exact = true` closes the list, so after such an import run

```bash
uv run tach sync
```

which rewrites `tach.toml` from the imports it finds. A new module inside
`spelaion.commands` that imports only `spelaion.runtime`, `spelaion.vfs` and
`spelaion.exec` adds no edge, and the sync leaves the file as it is; run it
anyway so the declaration and the code agree. [How spelaion is
built](how-spelaion-is-built.html) explains the edges.

## The test next to the other command tests

The tests in `tests/commands/` call the command function directly. Add
`tests/commands/test_join.py` beside `test_textproc.py`. They need no sandbox
and no host folder: a `VirtualFilesystem` provides the files, a `ShellState`
provides the working directory, and an `IOContext` collects the two streams.
The fixtures match the ones in `tests/commands/test_textproc.py`:

```python
"""Tests for join."""

from __future__ import annotations

from io import StringIO

import pytest

from spelaion.commands.textproc2 import cmd_join
from spelaion.exec.redirs import IOContext
from spelaion.runtime.state import ShellState
from spelaion.vfs.filesystem import VirtualFilesystem


@pytest.fixture
def vfs() -> VirtualFilesystem:
    return VirtualFilesystem(
        initial_files={
            "/left.txt": "1 alpha\n2 beta\n3 gamma\n",
            "/right.txt": "1 one\n3 three\n4 four\n",
        }
    )


@pytest.fixture
def state() -> ShellState:
    shell = ShellState()
    shell.cwd = "/"
    return shell


def run(
    args: list[str], state: ShellState, vfs: VirtualFilesystem, stdin: str = ""
) -> tuple[int, str, str]:
    ctx = IOContext()
    ctx.stdin = StringIO(stdin)
    result = cmd_join(args, state, vfs, ctx)
    return result.exit_code, ctx.stdout.getvalue(), ctx.stderr.getvalue()


def test_pairs_on_the_first_field(state: ShellState, vfs: VirtualFilesystem):
    assert run(["left.txt", "right.txt"], state, vfs) == (
        0,
        "1 alpha one\n3 gamma three\n",
        "",
    )


def test_a_prints_the_unpaired_left(state: ShellState, vfs: VirtualFilesystem):
    assert run(["-a", "1", "left.txt", "right.txt"], state, vfs) == (
        0,
        "1 alpha one\n2 beta\n3 gamma three\n",
        "",
    )


def test_missing_file_sets_the_status(state: ShellState, vfs: VirtualFilesystem):
    assert run(["missing.txt", "right.txt"], state, vfs) == (
        1,
        "",
        "join: missing.txt: No such file or directory\n",
    )


def test_standard_input(state: ShellState, vfs: VirtualFilesystem):
    assert run(["-", "right.txt"], state, vfs, stdin="1 uno\n") == (
        0,
        "1 uno one\n",
        "",
    )
```

`run` returns the three things a command produces, so each test is one
comparison. The assertions check the exit status as well as the text, because
a command that prints the right line and returns 0 after a failed read is
still wrong.

## The battery case

`tests/battery` runs commands through a `Sandbox` and compares stdout and the
exit code with what real bash 5 printed. Add a case to `CASES` in
`tests/battery/cases.py`:

```python
Case(
    "join two files",
    "printf '1 alpha\\n2 beta\\n' > a.txt"
    " && printf '1 one\\n3 three\\n' > b.txt"
    " && join a.txt b.txt",
),
```

The fields of `Case` are `name`, `command`, `python` and `gap`.
`python=True` marks a case that needs the `python` command, so the test
builds the sandbox with the WASI interpreter; leave it off unless the command
calls `python`. `gap` is a sentence for a case spelaion does not match yet:
`test_battery.py` marks such a case `xfail(strict=True)`, so the suite fails
once the gap closes and the case has to be updated. A case without a `gap`
must match bash exactly.

Every case runs with `/project` read-only from `fixtures/project` and an empty
writable `/scratch` as the working directory, so this case writes its two
files into `/scratch`. Record the expected output with real bash:

```bash
uv run python tests/battery/record.py
uv run pytest tests/battery
```

`record.py` refuses a bash whose major version is not 5, because the recorded
text is tied to that version. It writes the stdout and exit code of every case
to `expected.json`, including the new one, and `test_battery.py` reruns them
all through a `Sandbox`.

## A builtin is a different thing

A builtin is a function in `src/spelaion/exec/builtins.py`, listed in the
`BUILTINS` dictionary and in `_SHELL_BUILTINS` in `src/spelaion/semantics/resolve.py`,
and the evaluator dispatches it itself instead of looking in `COMMANDS`. That
is what lets `cd` change the working directory for the rest of the call,
`export` write a variable, and `source` run a file in the current shell. Use a
builtin only when the command must act on the evaluator's own state that way;
a text filter such as `join` is a command.

## The gates

All five gates pass before a commit, and CI runs the same five:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run tach check
uv run pytest -q
```

`ruff format` is the formatter, so run it on the new file before the check.
`pyright` checks the annotations in `src`, so the signature of the command is
part of the gate. `tach check` reads the same edges `tach sync` writes, and
`pytest` runs the unit test and the battery case.

## The finished program

The file `docs/examples/adding_a_command.py` is the command with its
decorator, plus a check that calls it the way the unit test does. The check
confirms that the decorator stored the function, builds the same three objects
the test builds, and prints what the command wrote:

```{python continue export=examples/adding_a_command.py}
print("registered:", COMMANDS["join"] is cmd_join)

state = ShellState()
state.cwd = "/"
vfs = VirtualFilesystem(
    initial_files={
        "/left.txt": "1 alpha\n2 beta\n3 gamma\n",
        "/right.txt": "1 one\n3 three\n4 four\n",
    }
)

ctx = IOContext()
result = cmd_join(["left.txt", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")
print("exit code:", result.exit_code)

ctx = IOContext()
cmd_join(["-a", "1", "-a", "2", "left.txt", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")

ctx = IOContext()
ctx.stdin = StringIO("1 uno\n")
cmd_join(["-", "right.txt"], state, vfs, ctx)
print(ctx.stdout.getvalue(), end="")

ctx = IOContext()
result = cmd_join(["missing.txt", "right.txt"], state, vfs, ctx)
print(ctx.stderr.getvalue(), end="")
print("exit code:", result.exit_code)
```

The check prints `True` for the registry entry. The first call pairs the two
shared keys and drops the unpaired lines. The second adds `-a 1 -a 2` and
prints every line of both files. The third reads one input from standard
input. The fourth reports the missing file on stderr and returns 1, which is
the exit status the shell shows to the agent.

The same steps apply to any missing command: write the function against
`ShellState`, `Filesystem` and `IOContext`, put it in a module the package
imports, and add the unit test and the battery case. [What the shell can
do](what-the-shell-can-do.html) has the list of names already covered, and [How spelaion
is built](how-spelaion-is-built.html) explains which package the file belongs to.
