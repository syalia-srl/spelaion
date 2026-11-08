# Running python in the sandbox

An agent asked to report on a build gets two files from the user's project: a
`settings.yaml` with a time budget, and a `runs.csv` with one row per job.
Counting rows is bash work. Parsing YAML, comparing every row to a value in it
and writing a JSON report is python work, and a model will write it in python.
Running the host's python would hand the agent the machine with it: the user's
whole disk, the network, every binary on PATH. This chapter gives the sandbox a
python of its own, with the standard library and PyYAML, over the same mounts
and nothing else.

## An interpreter of its own

`Sandbox(python=True)` adds `python` and `python3` to the shell. They run
CPython 3.14.9 compiled to WASI, under wasmtime, inside the sandbox's child
process. It is not the host's python, and it reaches only the mounts, as the
shell does.

The WASI build is not in the wheel, because it is a wasm binary and not Python
code. The first sandbox made with `python=True` downloads it (about 14 MB,
pinned by sha256) and prepares it in a cache folder, so that constructor takes
the wait once; later sandboxes find it ready. To pay it before an agent is
waiting, run the CLI:

```bash
spelaion fetch-python
```

It prepares the same folder and prints its path. The folder is `$SPELAION_CACHE`
when that is set, else `$XDG_CACHE_HOME/spelaion`, else `~/.cache/spelaion`.
The cache holds one folder per CPython build:

```text
python-3.14.9/
  python.wasm
  python.wasm.cwasm-<wasmtime version>-<cpu hash>
  lib/
  site-<hash>/
```

`python.wasm` is the interpreter, `lib/` the standard library and `site-<hash>/`
PyYAML with the module that starts the guest. The compiled module's name
carries the wasmtime version and the site folder's name a hash of its sources,
so an upgrade writes new files instead of loading native code an older spelaion
left behind. wasmtime compiles for the features of the CPU it runs on, so the
compiled module's name also carries a hash of them, and a cache that two
machines share keeps one compiled module for each. Only the parent process builds the cache; a child that finds it
incomplete prints a message and exits 127. The sandbox refuses a writable mount
that holds the cache or lies inside it, because the cache holds native code the
host loads.

The chapter's project has a settings file and a run log, mounted read-only,
plus an empty folder for the agent's output:

```{python export=examples/python.py}
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

project = Path(tempfile.mkdtemp())
output = Path(tempfile.mkdtemp())
settings = "budget_s: 4.0\ncolumns: [name, seconds]\n"
(project / "settings.yaml").write_text(settings)
(project / "runs.csv").write_text(
    "name,seconds\nbuild,3.2\ntests,9.5\ndocs,1.1\nscan,6.4\n"
)
```

```{python continue export=examples/python.py}
sb = Sandbox(
    [
        Mount("/project", host=project, readonly=True),
        Mount("/out", host=output),
    ],
    cwd="/project",
    python=True,
)
```

## One line

`python3 -c` runs the string that follows, and `yaml` is PyYAML 6.0.3 from the
site folder. The call starts in the shell's working directory, so the relative
path in the program resolves under `/project`:

```{python continue export=examples/python.py}
r = sb.bash("python3 -c 'import yaml; print(yaml.safe_load(open(\"settings.yaml\")))'")
print(r.stdout, end="")
```

The single quotes are the shell's and the double quotes the program's, which is
the form a model writes when it composes one line. `python` and `python3` are
the same command.

## Pipes and stdin

`python3` is a pipeline stage like any other command. The agent can feed it a
file on stdin and read its stdout through `head`. The first call counts the
rows over the budget and prints 2; the second writes ten numbers, and `head`
keeps three of them:

```{python continue}
r = sb.bash(
    "cat runs.csv | python3 -c 'import csv, sys; "
    "rows = list(csv.DictReader(sys.stdin)); "
    "print(sum(1 for row in rows if float(row[\"seconds\"]) > 4))'"
)
print(r.stdout, end="")
r = sb.bash("python3 -c 'for n in range(10): print(n)' | head -3")
print(r.stdout, end="")
```

The call's output cap applies to the guest's output as it does to any command's,
and the deadline covers the whole pipeline. [Bounding every
call](bounding-every-call.html) gives the numbers.

## The mounts are all it has

From python each mount appears at the path the sandbox gave it, read-only where
the mount is. `/project` holds the two input files and `/out` is empty, because
the agent has not written its report yet:

```{python continue}
r = sb.bash(
    "python3 -c 'import os; "
    "print(sorted(os.listdir(\"/project\")), sorted(os.listdir(\"/out\")))'"
)
print(r.stdout, end="")
```

The host folder behind a mount never appears: neither path is a host path, and
the random directory names the host chose are not visible. There is no root
folder either. `/` was never preopened, so listing it raises
`FileNotFoundError` rather than returning an empty list, and a file outside the
mounts does not exist:

```{python continue}
r = sb.bash("python3 -c 'import os; print(os.listdir(\"/\"))'")
print(r.stderr.strip().splitlines()[-1])
r = sb.bash("python3 -c 'print(open(\"/etc/passwd\").read())'")
print(r.stderr.strip().splitlines()[-1])
```

Reading the same file works because the mount is there, read-only. Writing to it
fails inside the guest with `PermissionError`, and the call exits 1:

```{python continue}
r = sb.bash("python3 -c 'open(\"/project/runs.csv\", \"a\").write(\"late,0\\n\")'")
print(r.stderr.strip().splitlines()[-1])
print("exit code:", r.exit_code)
```

A writable mount takes writes from the guest as it does from the shell. The
report script goes into `/out` with the `write` tool, and python runs it by
path, with the working directory still `/project`:

```{python continue export=examples/python.py}
sb.write(
    "/out/report.py",
    """\
import csv
import json

import yaml

settings = yaml.safe_load(open("/project/settings.yaml"))
with open("/project/runs.csv", newline="") as f:
    runs = list(csv.DictReader(f))
over = [r["name"] for r in runs if float(r["seconds"]) > settings["budget_s"]]
with open("/out/report.json", "w") as f:
    json.dump({"budget_s": settings["budget_s"], "over": over}, f)
print(len(runs), "runs,", len(over), "over budget")
""",
)
r = sb.bash("python3 /out/report.py")
print(r.stdout, end="")
print("exit code:", r.exit_code)
```

The script reads both mounts by their sandbox paths and writes its result into
the writable one. The file is on the host when the call returns, so the product
reads the same bytes the guest wrote:

```{python continue export=examples/python.py}
print((output / "report.json").read_text())
```

A script is the better shape once the job has more than a couple of imports:
quoting a program inside `-c` through the shell gets unreadable, and a file in
a writable mount is easy for the next call to fix with `edit`. [Giving the agent
folders](giving-the-agent-folders.html) covers what a writable mount exposes on the host.

## What is not there

WASI gives the guest no sockets. The WASI build of `_socket` has no
`getaddrinfo`, so `socket.create_connection` raises `AttributeError` before it
resolves a name, and a socket opened directly raises `OSError` 58, `Not
supported`:

```{python continue}
r = sb.bash(
    "python3 -c 'import socket; socket.create_connection((\"example.com\", 80))'"
)
print(r.stderr.strip().splitlines()[-1])
r = sb.bash("python3 -c 'import socket; socket.socket()'")
print(r.stderr.strip().splitlines()[-1])
```

There are no processes either. `subprocess` imports, since it is part of the
standard library, and starting one raises `OSError` 58, `wasi does not support
processes`:

```{python continue}
r = sb.bash("python3 -c 'import subprocess; subprocess.run([\"ls\"])'")
print(r.stderr.strip().splitlines()[-1])
print("exit code:", r.exit_code)
```

There is no `pip` either: `python3 -m pip` fails with `No module named pip`, and
the site folder is built from the PyYAML copy spelaion vendors, so nothing
installs into it from inside the sandbox. When the job needs the network or a
host program, the product gives the agent a command for that job, not a wider
guest; [Host commands](giving-the-agent-powers-with-host-commands.html) shows how.

## Each call a new interpreter

Every `python3` call instantiates the prepared module again. Names, imports and
open files are gone at the end of the call, so a name the earlier program bound
raises `NameError`. Files live on the mounts, and the next call reads them:

```{python continue}
sb.bash(
    "python3 -c 'answer = 42; "
    "open(\"/out/answer.txt\", \"w\").write(str(answer))'"
)
r = sb.bash("python3 -c 'print(open(\"/out/answer.txt\").read())'")
print(r.stdout, end="")
r = sb.bash("python3 -c 'print(answer)'")
print(r.stderr.strip().splitlines()[-1])
```

The shell behaves the same way: variables and functions do not survive a call,
and files do. That is what makes each call reproducible and keeps one agent's
state out of the next request.

## What the model is told

The `bash` tool carries a description, and `python=True` changes one sentence of
it. The rest names the mounts, the working directory, the timeout and the other
commands:

```{python continue}
print(sb.tools()[0].description)
```

Without python the same sentence says there is no python, and the commands are
still registered but refuse to run:

```{python continue}
plain = Sandbox([Mount("/project", host=project, readonly=True)], cwd="/project")
python_rule = next(
    sentence
    for sentence in plain.tools()[0].description.split(". ")
    if "python" in sentence
)
print(python_rule)
r = plain.bash("python3 -c 'print(1)'")
print(r.stderr, end="")
print("exit code:", r.exit_code)
r = plain.bash("which python")
print(r.stderr, end="")
plain.close()
```

The `python3` call exits with 127, the code a shell gives for a command that is
not there, and `which python` answers that there is no python in the virtual
shell. A model that reads the description does not try.

With python on, a mount at `/lib` or `/site`, or anywhere under them, would hide
the standard library or PyYAML, so the sandbox refuses it while it is being
built:

```{python continue}
for path in ("/lib", "/site"):
    try:
        Sandbox([Mount(path, host=project)], python=True)
    except ValueError as e:
        print(e)
```

The check belongs to `python=True` only; without python those paths are ordinary
mount points, and a mount there does not hide an interpreter that is not
running.

```{python continue export=examples/python.py}
sb.close()
```

## Where to go next

- [Giving the agent folders](giving-the-agent-folders.html): read-only and writable mounts, and
  what lasts between calls.
- [Bounding every call](bounding-every-call.html): the deadline, memory, output and disk
  caps that a python call shares with the shell.
- [Host commands](giving-the-agent-powers-with-host-commands.html): when the job needs the network or the
  host, a command the product writes with its own power.
- [Your own agent loop](your-own-agent-loop.html): handing these three tools to a model.
