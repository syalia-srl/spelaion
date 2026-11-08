# The security model

You are about to give an agent driven by a model you do not control the three
tools that can read and change a user's files. Before you register them, you
need a precise answer to three questions: what can the agent reach, what
refuses it when it tries to reach past that, and what does spelaion not
promise. This chapter states the model for a `Sandbox`, then runs each boundary
as an attack against a real one, so the refusals are shown rather than
asserted.

## What the agent can reach

An agent inside a `Sandbox` gets:

- the host folders you mount, with a `readonly` mount available only for
  reading;
- for `python`, the standard library and PyYAML;
- the host commands your product registers.

It gets nothing else. Any other host file, the network, host binaries and host
processes are absent, not hidden behind a permission check that some command
might skip. The shell is a Python interpreter that parses bash and evaluates
its own tree; it has no function that starts a program. `python` is CPython
built for WASI and run under wasmtime, and WASI has no socket and no process to
grant. [python](running-python-in-the-sandbox.html) and [host commands](giving-the-agent-powers-with-host-commands.html) cover
those two entry points.

The mount table is the part every entry point shares, though not every entry
point reaches it by the same call. `bash`, `edit`, `write` and a host command's
`ctx.path()` reach the host through `MountFs.host_path()`, the only function
that turns a sandbox path into a host path for them. `python` gets each mount
as a WASI preopen, writable only when the mount is writable. `host_path()`
normalises the path lexically, so `..` stops at `/`; takes the longest mount
point that prefixes the result; follows a symlink and refuses a target outside
that mount. A path outside every mount does not exist, and a write also rejects
a `readonly` mount and a writable mount over its disk cap.
[Giving the agent folders](giving-the-agent-folders.html) describes the mount table itself.

## The child process

Each sandbox runs its shell and python in a child Python process. A call past
its deadline kills that child, and the next call starts a fresh one; an rlimit
caps the child's memory; the output cap and the disk cap bound what one call
can print and what the writable mounts can hold. A runaway command returns an
error and the product stays up. [Bounding every call](bounding-every-call.html) has the
numbers and how each bound is enforced.

The child is not a kernel sandbox. It runs as the product's user, with that
user's permissions. What keeps the agent inside is the resolver, the WASI
preopens and the absence of any way to start a process. If the product runs as
root, the child runs as root too; the user ID adds no boundary, and the mount
table and the WASI preopens are what remain.

## An audit sandbox

Build one sandbox over three host folders. `/work` stands for the user's
project and is mounted read-only; `/scratch` is mounted writable. `private`
sits next to them and is not mounted at all, so it stands for every file the
agent must not see. `python=True` enables the python command, because three of
the boundaries below are python's.

```{python export=examples/security.py}
import shutil
import tempfile
from pathlib import Path

from spelaion import HostContext, Mount, Result, Sandbox

root = Path(tempfile.mkdtemp())
work = root / "work"
scratch = root / "scratch"
private = root / "private"
for folder in (work, scratch, private):
    folder.mkdir()
(work / "notes.md").write_text("hello\n")
(private / "key.txt").write_text("secret\n")
```

The sandbox takes the two mounts and a working directory in the writable one.
`attempt` prints the last line of whatever the call wrote and its exit code, so
each attack takes one line in the output:

```{python continue export=examples/security.py}
sb = Sandbox(
    [Mount("/work", work, readonly=True), Mount("/scratch", scratch)],
    cwd="/scratch",
    python=True,
)


def attempt(label: str, result: Result) -> None:
    lines = (result.stderr or result.stdout).strip().splitlines()
    print(f"{label}: {lines[-1] if lines else 'no output'} (exit {result.exit_code})")


```

## A path outside the mounts

The first attack climbs out of a mount with `..`, and the second asks for an
absolute path that no mount covers:

```{python continue export=examples/security.py}
attempt("dot dot", sb.bash("cat /work/../private/key.txt"))
attempt("absolute", sb.bash("cat /etc/passwd"))
```

`host_path()` normalises `..` before it looks for a mount, so
`/work/../private` becomes `/private`. There is no `/private` mount, and the
folder next to the mounts has no sandbox name. `/etc/passwd` is outside every
mount in the same way. Both errors are `No such file or directory`, not
`Permission denied`: the sandbox has no object to deny, because the path does
not exist in its namespace. The message quotes the path as the agent typed it,
`..` included.

## A symlink planted on the host

A host program can put a symlink in a writable mount. The next attempt points
one at the unmounted folder:

```{python continue export=examples/security.py}
(scratch / "planted").symlink_to(private / "key.txt")
(scratch / "planted_dir").symlink_to(private)
attempt("planted symlink", sb.bash("cat planted"))
attempt("planted folder", sb.bash("cat planted_dir/key.txt"))
```

`host_path()` resolves the path, finds `private/key.txt`, and refuses it
because the resolved host path is not inside the host folder behind
`/scratch`. The shell reports `Permission denied` (EACCES) and exits 1. A link
to a folder fails the same way, because the check runs on the resolved target,
not on the name of the link.

## A read-only mount

Four entry points try to change the same file on `/work`: a shell redirection,
`edit`, `write` and a python guest.

```{python continue export=examples/security.py}
attempt("bash write", sb.bash("echo changed > /work/notes.md"))
attempt("edit", sb.edit("/work/notes.md", "hello", "changed"))
attempt("write", sb.write("/work/notes.md", "changed\n"))
attempt("python write", sb.bash("python -c \"open('/work/notes.md', 'w')\""))
print("host file:", repr((work / "notes.md").read_text()))
```

The first three are refused by `host_path()` with `Read-only file system`
(EROFS). The shell prints the refusal with a `spelaion:` prefix; `edit` and
`write` prefix their own names. The python guest is refused earlier, by WASI:
the mount is a read-only preopen, and `open(..., "w")` raises
`PermissionError` with errno 63, this build's `EPERM`, not the EROFS a Linux
file would give. The host file still contains `hello`.

## No processes and no network

The next three calls ask for a socket, for a process, and for a program the
shell does not have:

```{python continue export=examples/security.py}
attempt("socket", sb.bash("python -c 'import socket; socket.socket()'"))
attempt("process", sb.bash("python -c 'import subprocess; subprocess.run([\"ls\"])'"))
attempt("host program", sb.bash("curl https://example.com"))


```

`curl` is not a denied host binary; there is no command by that name in the
shell, so the evaluator reports `command not found` and exits 127. The python
guest can import `subprocess` and `socket` from the standard library, and the
calls fail at the WASI boundary. `socket.socket()` raises
`OSError: [Errno 58] Not supported`; `subprocess.run` raises
`OSError: [Errno 58] wasi does not support processes.`; the message names the
missing feature. Errno 58 is this build's `ENOTSUP`. The module is present and
the operation is not. For the same reason `os.system` and `os.fork` do not
exist in this build, and a call to either raises `AttributeError`.

## What a host command can say

A host command reaches files through `ctx.path()`, which applies the same
resolver and takes the calling shell's working directory. The block defines
two commands: one asks the resolver for a missing file, the other opens a host
path directly and finds nothing.

```{python continue export=examples/security.py}
@sb.command
def cat_host(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=ctx.path(args[0]).read_text())


@sb.command
def host_only(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=(private / "absent").read_text())


attempt("host command", sb.bash("cat-host missing.txt"))
attempt("host error", sb.bash("host-only"))
r = sb.bash("cat-host missing.txt; host-only")
print("host folder named:", str(root) in r.stderr)
```

The first error names the sandbox path, `/scratch/missing.txt`. The second
names no path at all, only the reason, because the host path it touched is
outside every mount. The last line checks the full text of both errors for the
temporary root and prints `False`: no host folder appears in what the agent
reads.

Two mechanisms produce that result. An exception raised through `ctx.path()`
carries the sandbox path, and the sandbox maps a host filename back to the
mount that holds it before printing. A message that still contains a mount's
host folder is rewritten to the mount path. Neither is a general taint
tracker: whatever a handler puts in `Result.stdout` or in its own exception
text is what the agent sees.

## The symlink a python guest can make

WASI lets a guest create a symlink in a writable mount, and it does not stop
the guest from writing `..` into the target. The next block writes a small
script in `/scratch` and runs it in the guest; the script creates `/scratch/out`
pointing at `../private/key.txt`. The block then reads the link from both
sides:

```{python continue export=examples/security.py}
(scratch / "link.py").write_text(
    'import os\nos.symlink("../private/key.txt", "/scratch/out")\n'
)
r = sb.bash("python link.py")
print("guest made a symlink:", r.exit_code == 0)
attempt("follow guest symlink", sb.bash("cat /scratch/out"))
print("host sees a symlink:", (scratch / "out").is_symlink())
print("host follows it:", (scratch / "out").read_text() == "secret\n")
```

Inside the sandbox the link is useless. `cat /scratch/out` is refused with
`Permission denied`, and a python `open` on it raises the same permission
error, because WASI resolves the link and finds a target outside the preopen.
On the host the entry is a real symlink, and opening it returns the contents of
`private/key.txt`; the program checks that text against `"secret\n"` and
prints `True`. The resolver refuses the link; a host program that opens the
path directly is not using the resolver. Treat a writable mount as untrusted
input on the host side.

The program closes the sandbox and removes its temporary folder:

```{python continue export=examples/security.py}
sb.close()
shutil.rmtree(root)
print("audit complete")
```

Every line above that names an error is a boundary holding. Run the same
script against your own mount layout after a configuration change, and check
that each boundary still refuses.

## What is out of scope

Four things are outside this design.

A bug in wasmtime or in CPython's WASI build that lets the guest escape. The
sandbox relies on WASI for python's file access, for the missing sockets and
for the missing processes. If that implementation is wrong, spelaion inherits
the bug.

Anything a host command does. Host commands are the product's trusted code: a
handler runs in the product's process, as the product's user, with the
product's permissions. `ctx.path()` is a convenience that applies the mount
table, not a restriction on the handler: a handler that opens a host path
directly reads it. Register only handlers you would run yourself, and do not
pass an agent-chosen string to `open` without `ctx.path()`.
[host commands](giving-the-agent-powers-with-host-commands.html) shows how to write one.

The child is not a kernel sandbox, as the model above says. It runs as the
product's user, so the host's own access controls still apply: a kernel bug,
another process with the same user's rights, or a setuid program on the host
is outside what the mount table addresses.

The in-memory `Bash` class is a test tool with none of these limits: no mount
table, no child process and no deadline, only the interpreter's own loop and
recursion caps. Do not give it to a model. [Testing with bash](testing-shell-scripts-with-bash.html)
uses it for the shell's own tests.

## Reporting a vulnerability

Do not open a public issue. Report it privately at
<https://github.com/syalia-srl/spelaion/security/advisories/new>; the policy is
in [SECURITY.md](https://github.com/syalia-srl/spelaion/blob/main/SECURITY.md)
on GitHub.

A report is in scope when it shows reading or writing a host file outside the
mounts, or writing a read-only mount, through any entry point; starting a host
program or opening a network connection from inside; a call that outlives its
deadline or exceeds the memory, output or disk caps without being stopped; or a
host path appearing in what the agent sees. It is out of scope when it needs
control of the Python host process, when the report is about what a host
command does with the power the product gives it, or when it is a performance
problem that does not exhaust a resource.

The maintainers acknowledge receipt within 48 hours and provide a fix timeline
within 7 days.
