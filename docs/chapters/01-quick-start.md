# Quick Start

You have a folder of files an agent should work on, and you do not want the
agent to touch anything else on the machine. This chapter gives it that
folder, runs a few commands the way a model would, and reads what came back.

## Install

spelaion needs Python 3.11 or later and is tested on Linux:

```bash
uv add git+https://github.com/syalia-srl/spelaion@v0.1.0
```

## A folder for the agent

Make a folder with one file in it. In a product this is the user's project;
here it is a temporary folder:

```{python export=examples/quick_start.py}
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

project = Path(tempfile.mkdtemp())
(project / "notes.md").write_text("# Notes\n\n- buy paint\n- call the plumber\n")
```

A `Mount` puts a host folder at a path inside the sandbox. The `Sandbox`
takes a list of them and a working directory, and starts the shell:

```{python continue export=examples/quick_start.py}
sb = Sandbox([Mount("/work", host=project)], cwd="/work")
```

## Run what a model would run

`sb.bash` runs one command line and returns a `Result`:

```{python continue export=examples/quick_start.py}
r = sb.bash("ls && grep -c '^- ' notes.md")
print(r.stdout, end="")
print("exit code:", r.exit_code)
```

The agent sees `/work` and nothing around it. The root lists the mount
points, and a path outside them does not exist:

```{python continue export=examples/quick_start.py}
print(sb.bash("ls /").stdout, end="")
r = sb.bash("cat /etc/passwd")
print(r.stderr, end="")
print("exit code:", r.exit_code)
```

## Change a file

`edit` replaces one exact piece of text, and `write` writes a whole file.
They are the other two tools a model gets:

```{python continue export=examples/quick_start.py}
sb.edit("/work/notes.md", old="- buy paint", new="- buy paint (white)")
sb.write("/work/todo.txt", "plumber on Monday\n")
print(sb.bash("cat notes.md todo.txt").stdout, end="")
```

The files are real: the host reads the same folder.

```{python continue export=examples/quick_start.py}
print(sorted(p.name for p in project.iterdir()))
sb.close()
```

`close()` stops the shell's child process. A `Sandbox` is also a context
manager, which closes it on the way out.

## Where to go next

- [Giving the agent folders](giving-the-agent-folders.html): read-only and writable mounts,
  and what lasts between calls.
- [Your own agent loop](your-own-agent-loop.html): hand these three calls to a model.
