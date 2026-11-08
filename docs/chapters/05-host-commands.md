# Giving the agent powers with host commands

The agent can write only inside the folders you mount. Sooner or later the
product needs something outside them: a plan checked against a rule the agent
must not be able to edit, a draft published to a service that wants a token, a
record read from the product's own store. Give the agent a real shell and the
token sits on its disk while the rule sits in a file it can change. The
spelaion answer is a host command: a Python function you register on the
sandbox, which the agent calls by name like any other command and which runs in
your process, with your access.

## A plan the product checks

The example is a release checklist. The agent writes plan steps in its work
folder, and the product publishes them. There are two folders: the work folder,
mounted writable at `/work`, and the product's outbox, which is not mounted at
all. A step is one line that begins with `- [ ] ` when open or `- [x] ` when
done; the product accepts no other line.

```{python export=examples/host_commands.py}
import tempfile
from pathlib import Path

from spelaion import HostContext, HostHandler, Mount, Result, Sandbox

work = Path(tempfile.mkdtemp())
outbox = Path(tempfile.mkdtemp())
(work / "plan.md").write_text("# Plan\n\n- [ ] paint the fence\n- [ ] buy paint\n")
(work / "post.md").write_text("The fence is painted.\n")
sb = Sandbox([Mount("/work", host=work)], cwd="/work")
```

## A function the agent can call

`@sb.command` registers the function under it. Bare, the name is the function's
own, with `_` written as `-`; `check_plan` becomes `check-plan`, and that is
what the agent types. The handler takes a `HostContext` and the arguments the
shell expanded, and returns a `Result` that carries all of its output. Nothing
the handler prints reaches the agent, because the handler runs in your process:
a `print` goes to your own stdout. Only the `Result` travels back.

```{python continue export=examples/host_commands.py}


@sb.command
def check_plan(ctx: HostContext, args: list[str]) -> Result:
    if args or not ctx.stdin:
        return Result(stderr="check-plan: usage: check-plan < plan.md\n", exit_code=2)
    bad = [
        f"{number}: {line}"
        for number, line in enumerate(ctx.stdin.splitlines(), 1)
        if line and not line.startswith(("- [ ] ", "- [x] "))
    ]
    if bad:
        return Result(
            stderr="check-plan: not a plan step\n" + "\n".join(bad) + "\n", exit_code=2
        )
    return Result(stdout="plan ok\n")
```

The handler reads the plan from its standard input, so the agent can pipe the
file in. Pipes, `<`, `>`, `2>` and here-strings all work on a host command the
same way they work on any command:

```{python continue export=examples/host_commands.py}


r = sb.bash("cat plan.md | check-plan")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

The title line fails the rule. The agent removes it and checks the plan again:

```{python continue export=examples/host_commands.py}
sb.write("/work/plan.md", "- [ ] paint the fence\n- [ ] buy paint\n")
print(sb.bash("check-plan < plan.md").stdout, end="")
```

## What a handler receives

The `HostContext` is the handler's view of the call. It has four fields:

| field | what it holds |
| --- | --- |
| `stdin` | the text the command's standard input collected |
| `cwd` | the calling shell's working directory, after any `cd` in the same call |
| `env` | its exported variables, after any `export` in the same call |
| `remaining_s` | seconds left before the call's deadline, measured at the start of the handler |

A handler that wants to stay ahead of the deadline reads `remaining_s` and
returns early. The deadline does not stop the handler itself; [a handler that
runs too long](#a-handler-that-runs-too-long) shows what happens when it runs
past.

The second argument is the shell's words after the command name, already
expanded. A handler can report the call it received:

```{python continue}
config = Path(tempfile.mkdtemp())
(config / "rules.toml").write_text("max_steps = 20\n")
demo = Sandbox(
    [Mount("/work", host=work), Mount("/config", host=config, readonly=True)],
    cwd="/work",
)


@demo.command("where")
def where(ctx: HostContext, args: list[str]) -> Result:
    left = "yes" if ctx.remaining_s > 0 else "no"
    return Result(
        stdout=f"cwd={ctx.cwd} args={args} env={','.join(sorted(ctx.env))} "
        f"stdin={ctx.stdin!r} time_left={left}\n"
    )


print(
    demo.bash("cd /work && export MODE=fast && echo plan | where one two").stdout,
    end="",
)
```

## Reaching a file the agent names

`ctx.path(p)` returns the host `Path` behind sandbox path `p`, resolved against
`ctx.cwd`. It is the only supported way for a handler to turn what the agent
typed into a host path. A path outside every mount raises `FileNotFoundError`, a
symlink that leaves its mount raises `PermissionError`, and with `write=True` a
read-only mount or a full disk raises too. The check is made when you call it,
so a handler that opens a path it got with the default `write=False` can still
write there. Host commands are trusted; the flag asks the mount whether it would
allow the write.

The `demo` sandbox from the section before also has a read-only mount at
`/config`. Writing to it is refused, and so is a path the sandbox does not have:

```{python continue}
@demo.command
def save(ctx: HostContext, args: list[str]) -> Result:
    ctx.path(args[0], write=True).write_text("max_steps = 30\n")
    return Result()


print(demo.bash("save /config/rules.toml").stderr, end="")
print(demo.bash("save /etc/hosts").stderr, end="")
```

## A secret the agent never sees

Publishing needs the product's API token. The token never enters the sandbox:
it lives in the handler's closure, read from the product's configuration
before the sandbox is built. `@sb.command("publish")` gives the command a name
of its own, and the factory's return type is the handler type,
`HostHandler` = `Callable[[HostContext, list[str]], Result]`:

```{python continue export=examples/host_commands.py}


def make_publisher(token: str, outbox: Path) -> HostHandler:
    @sb.command("publish")
    def publish(ctx: HostContext, args: list[str]) -> Result:
        if len(args) != 1:
            return Result(stderr="publish: usage: publish DRAFT\n", exit_code=2)
        try:
            draft = ctx.path(args[0]).read_text()
        except OSError:
            return Result(stderr=f"publish: cannot read {args[0]}\n", exit_code=1)
        name = Path(args[0]).name
        (outbox / name).write_text(f"token: {token}\n\n{draft}")
        return Result(stdout=f"published {name}\n")

    return publish


make_publisher("token-2f8c", outbox)
```

The handler writes the token into the outbox, which the sandbox cannot see. A
search of the whole sandbox finds neither the token nor the outbox:

```{python continue export=examples/host_commands.py}
print(sb.bash("check-plan < plan.md && publish post.md").stdout, end="")
print(
    sb.bash("grep -r 'token-2f8c' / || echo 'no token in the sandbox'").stdout, end=""
)
print(sb.bash("ls /").stdout, end="")
print((outbox / "post.md").read_text(), end="")
```

## When the handler fails

An exception becomes `name: message` on stderr with exit code 1. The message is
the exception's own text, with each mount's host folder rewritten as its
sandbox path, so the agent is never told where the folder really is. The
rewriting is worth seeing on a handler that opens a path it got from
`ctx.path`: the path check looks at the mounts, not at whether the file exists,
so a missing file fails at the open.

```{python continue}
@demo.command
def broken(ctx: HostContext, args: list[str]) -> Result:
    text = Path(ctx.path("missing.md")).read_text()
    return Result(stdout=text)


r = demo.bash("broken")
print(r.stderr, end="")
print("exit code:", r.exit_code)
print("host folder in the message:", str(work) in r.stderr)
```

The message names `/work/missing.md`, the sandbox path; the host folder behind
it never appears in what the agent reads.

`SystemExit` is handled separately. An integer code ends the command with that
code, and a string becomes `name: message` with exit code 1. An exit code in a
`Result`, or an integer given to `SystemExit`, is wrapped to 0 to 255, as bash
wraps it:

```{python continue}
@demo.command
def refuse(ctx: HostContext, args: list[str]) -> Result:
    raise ValueError("the plan is empty")


@demo.command
def give_up(ctx: HostContext, args: list[str]) -> Result:
    raise SystemExit(3)


@demo.command
def no_place(ctx: HostContext, args: list[str]) -> Result:
    raise SystemExit("no destination is configured")


@demo.command
def wrap(ctx: HostContext, args: list[str]) -> Result:
    return Result(exit_code=int(args[0]))


print(demo.bash("refuse").stderr, end="")
print(demo.bash("give-up").exit_code)
print(demo.bash("no-place").stderr, end="")
print(demo.bash("wrap 256").exit_code, demo.bash("wrap -1").exit_code)
```

`argparse` exits through the same door: a bad option raises `SystemExit(2)` and
`--help` raises `SystemExit(0)`. But argparse printed its usage on your
process's stderr, and its help on your stdout, so the agent gets the exit code
and no text. A handler that must show the agent its usage checks the arguments
itself and returns the text in `Result.stderr`, as `check-plan` does.

## Registering after the first call

A command may be registered before the first call or at any time after it. The
child is told about new names before the next call; until then the name is
unknown to the shell, which fails with 127:

```{python continue}
print(demo.bash("lint").stderr, end="")


@demo.command
def lint(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout="nothing to lint\n")


print(demo.bash("lint").stdout, end="")
```

A name must be a command word: letters, digits, `_`, `.` and `-`, not starting
with `-`. It may not be a shell keyword, may not be a name the shell already
resolves, and may not be taken by another host command. Each refusal is a
`ValueError`, raised when the decorator is applied:

```{python continue}
def unused(ctx: HostContext, args: list[str]) -> Result:
    return Result()


for name in ("if", "grep", "check-plan", "9 lives"):
    try:
        sb.command(name)(unused)
    except ValueError as error:
        print(error)
demo.close()
```

The message for `grep` says "builtin command" even though `grep` is one of the
virtual commands rather than a shell builtin. The check covers every name the
shell resolves itself.

## The agent has to know it exists

A model cannot call a command it was never told about. `sb.tools()` reads the
host commands registered at that moment, and the bash tool's description names
them after the shell's own commands:

```{python continue export=examples/host_commands.py}
bash = next(tool for tool in sb.tools() if tool.name == "bash")
print(bash.description.split("Extra commands: ")[1])
```

`show` comes first because it is a host command too, the built-in one that
hands images back. A tool list built before a later registration does not
update itself; call `sb.tools()` again to get a fresh description. That is what
matters for [your own loop](your-own-agent-loop.html) and for [MCP](serving-the-tools-over-mcp.html).

## A handler that runs too long

The deadline belongs to the call, not to the handler. A handler that runs past
it is not interrupted; the parent gives up first, returns the timeout result
and restarts the child:

```{python continue}
import time

from spelaion import Limits

slow = Sandbox(
    [Mount("/work", host=work)], cwd="/work", limits=Limits(timeout_s=1)
)


@slow.command
def wait_for_it(ctx: HostContext, args: list[str]) -> Result:
    time.sleep(2)
    return Result(stdout="done\n")


r = slow.bash("wait-for-it")
print(r.stderr, end="")
print(r.exit_code, r.timed_out)
print(slow.bash("ls").stdout, end="")
slow.close()
```

The call takes about two seconds, not the one second in its limit, because the
handler runs to its end before the parent notices. The result says exit 124 and
`timed_out`, and the next call runs in a new child. [Bounding every
call](bounding-every-call.html) covers the other limits the same way.

## Images

A handler can hand images back to the model with `ctx.attach()`, and the
built-in `show` command does exactly that for files the agent names;
[Images](showing-the-model-images.html) takes the whole subject.

## The finished program

The finished program is a sandbox with two host commands, one that enforces a
rule in the product and one that publishes with a token the sandbox never
holds:

```{python continue export=examples/host_commands.py}
print(sorted(p.name for p in outbox.iterdir()))
sb.close()
```

## Where to go next

- [Images](showing-the-model-images.html): host commands that hand images back, and `show`.
- [Your own loop](your-own-agent-loop.html): hand `sb.tools()` to a model.
- [Adding a command](adding-a-command-to-the-shell.html): write a command inside the shell
  instead of in the host.
