# Testing shell scripts with Bash

You keep a shell snippet that your product runs: the steps that publish a
draft, or the commands behind a button in your product's interface. Before
shipping a change you want a test that runs the snippet through spelaion's
shell, checks what it printed, and checks the files it left behind, in the
same process as the rest of your test suite and without a temporary folder or
a container. `Bash` is that test shell: the same parser, evaluator and
commands a `Sandbox` gives an agent, over a filesystem that exists only in
memory.

## A shell with files and no host

`Bash(files=..., env=..., cwd=...)` takes the starting files, the environment
and the working directory. `run(script, env=..., cwd=..., stdin=..., args=...)`
executes one script and returns a `RunResult` with `stdout`, `stderr` and
`exit_code`:

```{python}
from spelaion import Bash

bash = Bash(
    files={"/repo/README.md": "# Shop\n\n- bread\n- milk\n"},
    env={"LANG": "C"},
    cwd="/repo",
)
print(bash.run("grep -c '^- ' README.md"))
print(bash.run("cat missing.txt"))
```

`files` maps an absolute path to a `str` or `bytes`; parent directories are
created as needed. Nothing here touches the host: no folder is mounted, no
child process starts, and the tree disappears with the object. The streams
and the exit code come from the same shell implementation a `Sandbox` runs,
so a test against `Bash` exercises the syntax, expansion and commands your
snippet will meet there.

## What survives a call

One `Bash` object is one shell. Variables, functions and the working directory
belong to that shell, and `run` does not reset them:

```{python}
from spelaion import Bash

bash = Bash(cwd="/repo")
bash.run("X=1")
bash.run("greet() { echo hello $X; }")
bash.run("mkdir -p sub && cd sub")
print(bash.run("greet").stdout.strip())
print(bash.run("pwd").stdout.strip())
```

`greet` was defined in one call and still sees `X` in the next, and the third
call leaves the shell in `/repo/sub`.

`run`'s per-call arguments are worth a closer look. The positional
parameters in `args` are restored when the call returns. The environment and
working directory you pass are written into the shell and stay, which is worth
knowing before you write a test that reuses one object:

```{python}
from spelaion import Bash

bash = Bash(cwd="/repo")
bash.run("X=1")
bash.run("mkdir -p /tmp")
print(bash.run("pwd", cwd="/tmp").stdout.strip())
print(bash.run("pwd").stdout.strip())
print(bash.run("echo $X", env={"X": "run"}).stdout.strip())
print(bash.run("echo $X").stdout.strip())
print(bash.run("echo $1 and $2", args=["alpha", "beta"]).stdout.strip())
print(repr(bash.run("echo $1").stdout))
```

The first `pwd` shows the override in effect and the second shows that it
lasted; `X` behaves the same way. Only `args` goes back to what it was. If a
test needs a clean shell, construct a new `Bash`; that is cheap because
nothing leaves the process.

`stdin` supplies standard input for the call, so `bash.run("cat", stdin="text\n")`
prints `text`. A script that does not parse returns exit code 2 with
`spelaion: syntax error` on stderr instead of raising.

## The same test against a Sandbox

For an agent, the unit of execution is not a long-lived shell. Files persist
between calls, but each `Sandbox.bash` call starts a fresh shell at the
sandbox's working directory, so a variable, a function or a `cd` from one call
is gone in the next:

```{python}
import shutil
import tempfile
from pathlib import Path

from spelaion import Bash, Mount, Sandbox

bash = Bash(cwd="/repo")
bash.run("X=1")
bash.run("greet() { echo hello; }")
bash.run("mkdir -p sub && cd sub")
print("Bash:", bash.run("greet").stdout.strip(), bash.run("pwd").stdout.strip())

folder = Path(tempfile.mkdtemp())
sb = Sandbox([Mount("/repo", host=folder)], cwd="/repo")
sb.bash("X=1")
sb.bash("greet() { echo hello; }")
print("Sandbox greet:", sb.bash("greet").exit_code, repr(sb.bash("greet").stderr))
print("Sandbox pwd:", repr(sb.bash("cd / && pwd").stdout), repr(sb.bash("pwd").stdout))
sb.close()
shutil.rmtree(folder)
```

Inside the sandbox, `cd /` moves that one call; the next call starts in
`/repo` again.

A snippet that sets a variable in one call and reads it in the next works
under `Bash` and fails for an agent. That difference is part of what a test
has to cover: if the agent runs each command as its own call, keep what the
snippet needs inside one `run`, or test it with a `Sandbox` and a real folder,
as [Giving the agent folders](02-mounts.md) shows.

## Files from Python

`read_file`, `write_file`, `write_files` and `file_exists` are the Python side
of the same filesystem. Relative paths resolve against the shell's current
directory, wherever `cd` left it:

```{python}
from spelaion import Bash

bash = Bash(files={"/repo/a.txt": "alpha\n"}, cwd="/repo")
bash.write_file("b.txt", "beta\n")
bash.write_files({"notes/today.md": "# Today\n", "notes/tomorrow.md": "# Tomorrow\n"})
print(repr(bash.read_file("b.txt")))
print(repr(bash.read_file("/repo/notes/today.md")))
print(bash.file_exists("notes/today.md"), bash.file_exists("nope.md"))
bash.run("mkdir -p sub && cd sub")
print(repr(bash.read_file("../a.txt")))
```

`write_file` takes `str` or `bytes` and creates missing parent directories.
`file_exists` answers for a file or a directory. There is no way to hand
`Bash` a host folder: fixtures go in through `files=`, `write_file` or
`write_files`, so a test carries its own input and leaves nothing on disk.

## Commands your snippet calls

Products often give the shell a command written in Python: `notify` sends a
message, `render` builds a page. `define_command` names a handler and returns
a `CustomCommand`, which `Bash(..., custom_commands=[...])` registers. The
handler receives the arguments and a `CommandContext`:

```{python}
from spelaion import Bash, CommandContext, CustomCommand, RunResult, define_command

calls = []


def record(args: list[str], ctx: CommandContext) -> RunResult:
    calls.append((args, ctx.cwd, ctx.stdin, ctx.env.get("PAGER"), ctx.fs.exists("/repo")))
    return RunResult(stdout=f"notified {args[0] if args else 'nobody'}\n")


notify = define_command("notify", record)
print(isinstance(notify, CustomCommand))
bash = Bash(
    files={"/repo/x.txt": "x\n"},
    env={"PAGER": "less"},
    cwd="/repo",
    custom_commands=[notify],
)
print(repr(bash.run("echo deploy done | notify release").stdout))
print(calls)
print(repr(bash.run("notify", stdin="typed text\n").stdout))
print(calls[-1])
```

`CommandContext` carries `args`, the same list the handler received; `stdin`,
from a pipe, a redirect or `run(stdin=)`; `cwd`; `env`, which holds the
exported variables only; and `fs`, the `VirtualFilesystem` itself. The
filesystem methods take absolute paths, so a handler that receives a relative
name resolves it first with `ctx.fs.resolve(name, ctx.cwd)`.

The handler returns a `RunResult`, and its streams and exit code become the
command's. An exception in the handler is not caught: it comes out of `run()`,
which makes a failing test double easy to spot. `CustomCommand(name, handler)`
builds the same object as `define_command(name, handler)`; the function is the
shorter form for the common case.

A custom command exists only in the `Bash` that registered it, and it runs in
your process. That is the point for a test double, and it is not the same
mechanism as the host commands a `Sandbox` gets, which
[Host commands](05-host-commands.md) covers.

A test replaces the product's command with a recorder like this one. The test
stays offline, and it can assert on the exact message the snippet tried to
send, which is usually the interesting part.

## The limits it has

`Bash` takes its own `Limits`, from `spelaion.api.bash`. The `Limits`
exported at the package root configures a `Sandbox`, and passing it to `Bash`
raises `AttributeError` because it has no `max_call_depth`.

| field | default | what it does |
| --- | --- | --- |
| `max_call_depth` | 100 | the shell's recursion limit; stops command substitution that nests deeper, and caps a loop at ten times its value |
| `max_loop_iterations` | 10 000 | nothing reads it today |

The loop cap is the one a test can hit:

```{python}
from spelaion import Bash
from spelaion.api.bash import Limits

bash = Bash(limits=Limits(max_call_depth=5))
print(bash.run("i=0; while [ $i -lt 60 ]; do i=$((i + 1)); done; echo $i"))
```

The counter stops at 51 because the executor allows `max_call_depth * 10`
iterations, prints `spelaion: loop iteration limit reached` on stderr, and
still exits 0. `max_loop_iterations` is never read, so setting it changes
nothing.

There is no deadline on a `Bash` shell. Its `ShellState.deadline` stays
`None`, so `sleep` sleeps for the whole interval it was given:

```{python}
import time

from spelaion import Bash

bash = Bash()
start = time.monotonic()
bash.run("sleep 0.3")
print(f"slept {time.monotonic() - start:.1f}s")
try:
    Bash().run("f() { f; }; f")
except RecursionError:
    print("RecursionError escaped run()")
```

`sleep 100000` would block `run` for that long. `max_call_depth` does not
bound a function that calls itself either: the Python stack ends it with a
`RecursionError`, which comes out of `run()`. Nothing caps the captured output
either: stdout and stderr are two `StringIO` objects that grow with whatever
the script prints.

## Never give an agent a Bash

A `Bash` is a test tool, not a sandbox. It has no timeout, as the sleep above
shows; no output or disk cap, because the streams and the files are objects in
your process; no child process, so an exception or a crash is yours; and no
mounts, so it sees only what you passed in `files=`. A model given one would
hold your process for as long as it liked and could still not read the user's
project.

Give the agent a `Sandbox`: it runs a child process over the folders you
mount and enforces a deadline, a memory cap and caps on output and disk, as
[Bounding every call](03-limits.md) describes. Expose it with `sb.tools()` in
[Your own agent loop](07-own-loop.md). Keep `Bash` for the tests that check
what those tools will run.

## The finished program

The snippet under test is `publish`. It copies a body into `drafts/`, prints a
line, and calls the product command `notify`. A test builds a shell with the
script and its fixtures, replaces `notify` with a recorder, and asserts on the
printed line, the file and the message:

```{python export=examples/testing_with_bash.py}
from spelaion import Bash, CommandContext, CustomCommand, RunResult, define_command

PUBLISH = """\
publish() {
  local slug="$1"
  local body="$2"
  if [ ! -s "$body" ]; then
    echo "publish: empty body" >&2
    return 2
  fi
  mkdir -p drafts
  cp "$body" "drafts/$slug.md"
  echo "published $slug"
  notify "published $slug"
}
"""


```

The recorder keeps one entry per call and answers with an empty `RunResult`.
`new_shell` puts the script and the fixtures in a fresh shell for each test,
so no test can see another's files:

```{python continue export=examples/testing_with_bash.py}
def recorder() -> tuple[list[CustomCommand], list[dict[str, object]]]:
    calls: list[dict[str, object]] = []

    def record(args: list[str], ctx: CommandContext) -> RunResult:
        calls.append({"args": args, "cwd": ctx.cwd, "stdin": ctx.stdin})
        return RunResult()

    return [define_command("notify", record)], calls


def new_shell(commands: list[CustomCommand] | None = None) -> Bash:
    bash = Bash(env={"PAGER": "cat"}, cwd="/repo", custom_commands=commands)
    bash.write_files(
        {
            "/repo/bin/publish.sh": PUBLISH,
            "/repo/draft.md": "hello world\n",
            "/repo/empty.md": "",
        }
    )
    return bash


```

The tests are plain functions with `assert` statements, named `test_` so a
pytest run would collect them too. The last three lines call them, which is
what makes the file run as a script:

```{python continue export=examples/testing_with_bash.py}
def test_publish():
    commands, calls = recorder()
    bash = new_shell(commands)
    result = bash.run("source bin/publish.sh && publish hello draft.md")
    assert result.exit_code == 0, result.stderr
    assert result.stdout == "published hello\n"
    assert bash.file_exists("drafts/hello.md")
    assert bash.read_file("drafts/hello.md") == "hello world\n"
    assert calls == [{"args": ["published hello"], "cwd": "/repo", "stdin": ""}]


def test_empty_body():
    commands, calls = recorder()
    bash = new_shell(commands)
    result = bash.run("source bin/publish.sh && publish empty empty.md")
    assert result.exit_code == 2
    assert result.stderr == "publish: empty body\n"
    assert not bash.file_exists("drafts/empty.md")
    assert calls == []


def test_state_between_calls():
    bash = Bash(cwd="/repo")
    bash.run("LIMIT=3")
    bash.run("show() { echo $LIMIT; }")
    bash.run("mkdir -p drafts && cd drafts")
    assert isinstance(bash.run("show"), RunResult)
    assert bash.run("show").stdout == "3\n"
    assert bash.run("pwd").stdout == "/repo/drafts\n"


test_publish()
test_empty_body()
test_state_between_calls()
print("3 tests passed")
```

Each test starts from a new `Bash` and needs no temporary folder, no mount and
no network. Name the file `test_*.py` and pytest collects the same three
functions; run it as it is and the last line prints the result.

The command set a snippet may use is in [The shell it runs](10-the-shell.md).
