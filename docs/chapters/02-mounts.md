# Giving the agent folders

Your product's agent must read the user's project but never change it, and it
must have one folder of its own to write drafts in. This chapter mounts both
folders in one sandbox, shows what the agent sees at the root, and separates
what lasts between calls from what does not.

The [Quick Start](quick-start.html) gave the agent one writable folder. This
chapter adds a read-only one and shows what that prevents.

## Two mounts

A `Mount` maps a host folder to a path inside the sandbox. `path` is where the
agent sees it, `host` is the folder on the machine, and `readonly` says whether
the agent may write there. `readonly` defaults to `False`, so the project mount
states it. Build a project and a drafts folder to mount:

```{python export=examples/mounts.py}
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

root = Path(tempfile.mkdtemp())
project = root / "project"
drafts = root / "drafts"
project.mkdir()
drafts.mkdir()
(project / "plan.yaml").write_text(
    "name: tower\n"
    "height: 2.7\n"
    "levels: 3\n"
    "roof: flat\n"
    "walls: stone\n"
    "floors: 3\n"
    "garden: yes\n"
)
(project / "README.md").write_text("# Tower\n\nA plan for a small tower.\n")
```

The `Sandbox` takes the list of mounts, the working directory every call starts
in, and the environment every call starts with:

```{python continue export=examples/mounts.py}
sb = Sandbox(
    [
        Mount("/project", host=project, readonly=True),
        Mount("/drafts", host=drafts),
    ],
    cwd="/drafts",
    env={"PROJECT": "tower"},
)
```

A sandbox takes any number of mounts. `cwd` must be an absolute path to a
folder the sandbox can see, or the constructor raises `ValueError`; `/drafts`
is the folder the agent may write, so it starts there. The variable in `env` is
set and exported on every call.

## What the agent sees

The root of the sandbox is not the machine's root. It is a folder the sandbox
constructs, and its entries are the mount points:

```{python continue export=examples/mounts.py}
print(sb.bash("ls /").stdout, end="")
print(sb.bash("pwd").stdout, end="")
print(sb.bash("echo $PROJECT").stdout, end="")
```

`ls /` prints the two mount names in sorted order. `pwd` prints the `cwd`, and
`echo` finds the variable from `env`.

A path outside every mount does not exist. The shell reports it as it would
report any missing file:

```{python continue export=examples/mounts.py}
r = sb.bash("cat /etc/passwd")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

The resolver finds no mount that contains `/etc/passwd`, so `cat` fails with
`No such file or directory`. The file exists on the machine, and the shell
cannot see it.

## Files persist, shell state does not

Each `bash` call is a fresh shell. It starts at `cwd` with `env`, and nothing a
previous call set survives. One call can show a variable, a function and a
`cd` taking effect inside it:

```{python continue export=examples/mounts.py}
command = "MARK=kept; greet() { echo hello; }; cd /project; echo $MARK $PWD"
print(sb.bash(command).stdout, end="")
```

The next call starts again at `/drafts`. The variable is empty and the function
is not a command:

```{python continue export=examples/mounts.py}
r = sb.bash("echo [$MARK] [$PWD]; greet")
print(r.stdout, end="")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

This is what makes a call reproducible from its text, `cwd` and `env` alone. A
model that needs a value in a later call writes it in the same call or puts it
in a file.

Files do last, because they are real files in the host folders:

```{python continue export=examples/mounts.py}
sb.bash("echo 'first draft' > /drafts/note.txt")
print(sb.bash("cat /drafts/note.txt").stdout, end="")
```

The file written by one call is read by the next. It is also on the host
already, in the folder behind `/drafts`.

## Result

`sb.bash` returns a `Result`. Its `stdout` is what the command wrote, its
`stderr` is what it complained, and its `exit_code` is what it returned. One
call fills two of its fields at once:

```{python continue export=examples/mounts.py}
r = sb.bash("cat /drafts/note.txt /drafts/missing.txt")
print("stdout:", repr(r.stdout))
print("stderr:", repr(r.stderr))
print("exit code:", r.exit_code)
```

The two fields are separate, and a command can write to both. `cat` printed the
file it found and complained about the one it did not, so the exit code is 1.
A model reads all three: the text on stdout, the error on stderr, and the code
that says whether the call worked.

`Result` has two more fields. `timed_out` is true when the call reached its
deadline, and `attachments` holds images a host command attached. The deadline
and the other bounds are a `Limits` value; [Bounding every call](bounding-every-call.html)
covers them.

## The project stays read-only

Three routes could change a file, and each one refuses on the read-only mount.
The shell, `write` and `edit` all fail with the same reason:

```{python continue export=examples/mounts.py}
for name, r in [
    ("bash", sb.bash("echo broken > /project/plan.yaml")),
    ("write", sb.write("/project/plan.yaml", "broken\n")),
    ("edit", sb.edit("/project/plan.yaml", old="height: 2.7", new="height: 3.0")),
]:
    print(name, "->", r.exit_code, r.stderr.strip())
```

The redirection in the shell reports the refusal without a command name.
`write` and `edit` prefix their own. `edit` checks that the path is writable
before it reads the file, so this answer does not depend on whether the old
text is present.

## Editing a draft

The agent cannot change the plan in place, so it copies the plan into its own
folder and edits the copy:

```{python continue export=examples/mounts.py}
r = sb.bash("cp /project/plan.yaml /drafts/plan.yaml")
print("copied:", r.exit_code)
r = sb.edit("/drafts/plan.yaml", old="height: 2.7", new="height: 3.0")
print(r.stdout, end="")
print("exit code:", r.exit_code)
```

`edit` replaces the one occurrence of `old` with `new` and returns the changed
lines with up to three lines either side, so the model can check the result
without another read. Here the change is on line 2, and the answer is the first
five lines of the file.

`edit` refuses two cases rather than guessing. If `old` is missing, nothing is
written:

```{python continue export=examples/mounts.py}
r = sb.edit("/drafts/plan.yaml", old="height: 9.9", new="height: 10.0")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

If `old` occurs more than once, it says how many times and asks for more
context:

```{python continue export=examples/mounts.py}
sb.write("/drafts/dupe.txt", "tower\ntower\n")
r = sb.edit("/drafts/dupe.txt", old="tower", new="keep")
print(r.stderr, end="")
print(sb.bash("cat /drafts/dupe.txt").stdout, end="")
```

The file still holds both lines. On success `edit` returns the context and an
exit code of 0; on either failure it returns an empty stdout, the message on
stderr, and exit code 1.

## Writing a new file

`write` replaces a whole file, and it creates the parent folders it needs
inside the mount:

```{python continue export=examples/mounts.py}
r = sb.write("/drafts/notes/day-1/plan.md", "# Day 1\n\n- measure the site\n")
print("exit code:", r.exit_code)
print(sb.bash("find /drafts/notes").stdout, end="")
```

A successful `write` returns an empty `Result`: no stdout, no stderr, exit code
0. The two missing folders were created. It will not create the host folder
behind a mount, and it will not write past the disk cap, which
[Bounding every call](bounding-every-call.html) describes.

## The host sees the same files

The mounts are not copies. The host reads the same folder the agent wrote:

```{python continue export=examples/mounts.py}
print((drafts / "plan.yaml").read_text(), end="")
found = [p.relative_to(drafts).as_posix() for p in drafts.rglob("*") if p.is_file()]
print(sorted(found))
print((project / "plan.yaml").read_text().splitlines()[1])
```

The host sees the edited height in the draft, the files the agent created, and
the original height in the project. The `readonly` flag is enforced inside the
sandbox: the host process owns both folders and can write to either. Files in
a writable mount can be shaped by the agent, so the host reads them as
untrusted input.

## Refusals at construction

The constructor checks the mounts before it starts the shell. A host folder
that does not exist raises `FileNotFoundError`:

```{python continue export=examples/mounts.py}
try:
    Sandbox([Mount("/project", host=root / "missing")])
except FileNotFoundError as e:
    print(str(e).replace(str(root), "<root>"))
```

Two mounts whose host folders are the same or nested raise `ValueError`:

```{python continue export=examples/mounts.py}
(project / "secret").mkdir()
try:
    Sandbox(
        [
            Mount("/project", host=project),
            Mount("/secret", host=project / "secret", readonly=True),
        ]
    )
except ValueError as e:
    print(str(e).replace(str(root), "<root>"))
```

The second case matters for permissions. A write to `/project/secret/key.txt`
would go through the writable `/project` mount and never meet the read-only
`/secret`, so the pair is refused. The messages name the host folder; the
blocks replace the temporary root with `<root>` to keep the output short.

Two mounts at the same sandbox path raise `ValueError` too, since only one of
the two folders could answer there:

```{python continue export=examples/mounts.py}
try:
    Sandbox([Mount("/project", host=project), Mount("/project/", host=drafts)])
except ValueError as e:
    print(e)
```

A `cwd` that is not an absolute path to a folder the sandbox can see raises
`ValueError`, with `cwd /nowhere is not an absolute path to a folder`.

## Closing the sandbox

`close()` stops the shell's child process. After it, every call raises
`RuntimeError("the sandbox is closed")`, and the files stay on the host:

```{python continue export=examples/mounts.py}
sb.close()
try:
    sb.bash("ls /")
except RuntimeError as e:
    print(e)
```

A `Sandbox` is also a context manager. `with` calls `close()` on the way out,
including when the body raises:

```{python continue}
with Sandbox(
    [Mount("/project", host=project, readonly=True)], cwd="/project"
) as other:
    print(other.bash("cat README.md").stdout, end="")
try:
    other.bash("ls")
except RuntimeError as e:
    print(e)
```

## The finished program

The exported blocks above are tangled into `docs/examples/mounts.py`. It builds
the two folders, opens the sandbox at `/drafts`, reads the project,
edits a copy of the plan, writes a nested draft, prints the host's view,
checks the two construction refusals, and closes the sandbox.

## Where to go next

- [Bounding every call](bounding-every-call.html): the deadline, the output cap and the
  disk cap that apply to these calls.
- [Your own agent loop](your-own-agent-loop.html): hand `bash`, `edit` and `write` to a
  model and let it work.
