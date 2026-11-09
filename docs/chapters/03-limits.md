# Bounding every call

A model writes the command lines your product runs, and nothing in a prompt
stops it from writing `sleep 999`, `seq 1 2000000000`, or a loop that writes a
file until the disk is full. Without a bound, one such line holds your process
and fills the host's disk. spelaion puts four numbers on every sandbox, stops a
call that passes one, and says in the `Result` which bound it hit.

## Four numbers on every sandbox

`Limits` holds the bounds for one sandbox:

| field | default | what it bounds |
| --- | --- | --- |
| `timeout_s` | `30` | seconds one call may run |
| `max_output` | `30_000` | characters of `stdout`, and of `stderr` separately |
| `max_disk` | `50_000_000` | bytes of files under all writable mounts together |
| `memory_mb` | `1024` | mebibytes of data the child process may allocate |

With no arguments, `Limits()` holds those defaults:

```{python export=examples/limits.py}
import tempfile
import threading
import time
from pathlib import Path

from spelaion import Limits, Mount, Sandbox

print(Limits())
```

A `Limits` is frozen, so the bounds of a running sandbox cannot change under an
agent; build another one and pass it as `limits=` when you build the sandbox. A
value out of range raises `ValueError` at construction, before any call runs:

```{python continue export=examples/limits.py}
for bad in ({"timeout_s": 0}, {"max_output": 0}, {"max_disk": -1}, {"memory_mb": True}):
    try:
        Limits(**bad)
    except ValueError as e:
        print(e)
```

`timeout_s` may be a float and must be finite; the other three must be positive
integers. A bool is refused, though Python counts one as an int.

## A call that runs too long

The rest of the chapter uses small bounds so every example finishes quickly:
two seconds, 200 characters, 400 bytes, 64 MiB. A product would keep the
defaults, or raise them.

```{python continue export=examples/limits.py}
work = Path(tempfile.mkdtemp())
cache = Path(tempfile.mkdtemp())
limits = Limits(timeout_s=2, max_output=200, max_disk=400, memory_mb=64)
sb = Sandbox(
    [Mount("/work", host=work), Mount("/cache", host=cache)],
    cwd="/work",
    limits=limits,
)
```

`timeout_s` is the time one call may take. A command that sleeps past it does
not hold the caller:

```{python continue export=examples/limits.py}
r = sb.bash("echo start > keep.txt; sleep 999")
print("timed_out:", r.timed_out, "exit code:", r.exit_code)
print(r.stderr, end="")
```

The call returns after two seconds. `timed_out` is `True`, the exit code is 124
(the code `timeout(1)` uses for the same case), and `stderr` names the bound.
Behind that result, the parent killed the child process: a call that is already
running cannot be interrupted from outside. The mounts are the same for the
next child, so a file written before the sleep is still there:

```{python continue export=examples/limits.py}
print("after the restart:", sb.bash("cat keep.txt").stdout, end="")
```

What the killed call loses is its shell state: variables and the working
directory, which start fresh on every call anyway. Files survive because they
live on the host mount, not in the child. [Giving the agent
folders](giving-the-agent-folders.html) covers which mounts keep writes and which refuse them.

## A shorter deadline inside the shell

Killing the child is the last resort, since it also ends work the call has
already done. For a bound on one command, the shell has `timeout`, as bash
does. It marks that command with status 124 and lets the call continue:

```{python continue export=examples/limits.py}
r = sb.bash("timeout 0.3 sleep 999; echo status=$?")
print(r.stdout, end="")
print("timed_out:", r.timed_out, "exit code:", r.exit_code)
```

`timed_out` stays `False`: the call itself did not reach `timeout_s`, and `echo`
ran after the stopped command. `timeout` sets a deadline the shell checks
before each command it runs and inside `sleep`; when a command reaches it, the
shell ends that command and goes on. A single long command that does not check
the deadline, such as a big `grep`, is not interrupted this way and runs until
the call's own bound. A duration longer than `timeout_s` never fires, because
the sandbox ends the call first, and that result has `timed_out=True`. [The
shell](what-the-shell-can-do.html) lists the commands spelaion implements and where they
differ from bash.

A loop is bounded by the call's deadline too. On top of that, a `while` or
`until` loop, or a C-style `for ((...))`, that runs a million times stops the
whole script with an `iteration limit reached` line on stderr and exit code 1,
so a script never carries on as if a cut-short loop had finished.

## Cutting long output

`max_output` bounds what a call hands back. A command may print more; the
middle of the text is removed on line boundaries, and a notice says how much
went in its place:

```{python continue export=examples/limits.py}
r = sb.bash("seq 1 100")
print(r.stdout, end="")
print("characters:", len(r.stdout))
```

About half of the limit is kept at the head and half at the tail, with 32 lines
between them. The notice is a line of output, not a field of `Result`, so a
model reading `stdout` sees it and can narrow the command with `grep` or `head`.
The result is 239 characters, over the limit of 200, because the line
boundaries and the notice are added to the kept halves. Truncation happens
after the command has run: the child collects the whole output in memory first,
which is why `memory_mb` matters for a command that prints without end.

## Filling the disk

`max_disk` counts bytes of files, and it counts every writable mount together.
spelaion sums the sizes of the regular files under those mounts before each
write, and refuses a write that would pass the cap. Here the cap is
400 bytes, `/work` already holds `keep.txt`, and a write to `/cache` does not
get a second budget:

```{python continue export=examples/limits.py}
r = sb.bash("seq 1 50 > /work/a.txt")
print("first write:", r.exit_code, (work / "a.txt").stat().st_size, "bytes")
r = sb.bash("seq 1 100 > /cache/b.txt")
print(r.stderr, end="")
print("exit code:", r.exit_code)
print("work:", sorted(p.name for p in work.iterdir()))
print("cache:", sorted(p.name for p in cache.iterdir()))
```

The first file is 141 bytes; the second would add 292 more, past 400 together
with `keep.txt`. The write fails with the code EDQUOT, printed as `Disk quota
exceeded`, and leaves no file behind. The message names the sandbox path, never the host
folder. `sb.write` reports the same reason in its own form:
`write: /cache/b.txt: Disk quota exceeded` with exit code 1. Read-only mounts
are not counted, since nothing can be written there. Because the check runs at
each write, an agent that deletes a file has room again:

```{python continue export=examples/limits.py}
r = sb.bash("rm /work/a.txt; seq 1 100 > /cache/b.txt; wc -c /cache/b.txt")
print(r.stdout, end="")
```

## Running out of memory

`memory_mb` is the data limit of the child process, set as `RLIMIT_DATA` when
it starts. It covers everything the child's Python allocates, the shell's own
work included. A command that asks for more gets `MemoryError`, which the child
turns into a result:

```{python continue export=examples/limits.py}
r = sb.bash("seq 1 10000000 | wc -l")
print(r.stderr, end="")
print("exit code:", r.exit_code)
print("still alive:", sb.bash("echo alive").stdout, end="")
```

Ten million lines are about 79 MB, more than the 64 MiB cap; the pipeline holds
the text in the child's memory before `wc` reads it. The result carries one
line, `spelaion: out of memory`, and exit code 1. Anything the command printed
before the allocation failed is dropped, because the shell returns only the
message. The child survives: it catches `MemoryError` at the top of the call,
so the next call runs on the same child with the same files, unlike a timeout.

## One call at a time

A sandbox owns one child and one shell, so its calls take a lock: calls from
several threads run one after another, never in the middle of each other.

```{python continue export=examples/limits.py}
started = time.monotonic()


def slow():
    sb.bash("sleep 0.4")


threads = [threading.Thread(target=slow) for _ in range(2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
print(f"two 0.4 s calls took {time.monotonic() - started:.2f} s")
```

Two threads, and the wall time is the sum rather than the overlap. The wait
does not count against the second call's `timeout_s`: the deadline is set when
the call reaches the child, not when the thread calls `bash`. For real
parallelism, give each worker its own `Sandbox` and its own child process.

The files the agent kept are still on the host, and the program closes the
sandbox at the end:

```{python continue export=examples/limits.py}
print("work:", sorted(p.name for p in work.iterdir()))
print("cache:", sorted(p.name for p in cache.iterdir()))
sb.close()
```

## Where to go next

- [Giving the agent folders](giving-the-agent-folders.html): read-only mounts, which do not
  count against `max_disk`, and what lasts between calls.
- [Host commands](giving-the-agent-powers-with-host-commands.html): commands written in Python in your
  process; `ctx.remaining_s` reports the time left, and a handler that overruns
  is not interrupted, but the call returns the timeout result and the child
  restarts.
- [Python in the sandbox](running-python-in-the-sandbox.html): the python guest's memory counts
  against `memory_mb` as well.
- [Your own agent loop](your-own-agent-loop.html): what to tell the model when
  `timed_out` is true.
- [MCP](serving-the-tools-over-mcp.html): serve the same three tools; requests that arrive together
  run one after another.
