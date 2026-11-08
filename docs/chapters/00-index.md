spelaion is a Python library that gives an AI agent a shell that looks like
bash and a python with the full standard library, while the agent sees only
the folders the host mounts. It reaches nothing else: no network, no other
agent's files, no host binaries. The host extends the shell with commands
written in Python, which run with the host's power and decide what the agent
may do.

The name is Plato's cave (σπήλαιον, *Republic* VII): the prisoners see only
the shadows someone casts on the wall. The agent sees only what the host
mounts.

## What it has

- **A `Sandbox`** with the three tools an agent needs, `bash`, `edit` and
  `write`, over host folders you mount read-only or writable.
- **A shell in a child process**, pure Python, with 128 commands and 39
  builtins, bounded per call by a deadline, a memory cap and caps on output
  and disk.
- **python and python3**, CPython 3.14 compiled to WASI, with the standard
  library and PyYAML, and no sockets or processes to reach.
- **Host commands**: Python functions the agent calls like any other command,
  the only way it affects anything beyond its writable folders.
- **The tools as data** for a loop that calls the model itself, and **an MCP
  server** for a harness such as Claude Code or OpenCode.

## How this book is organised

The [Quick Start](quick-start.html) gives an agent a folder and runs its
first commands. The User Guide then takes one job per chapter, from mounting
folders to running Claude Code with nothing but these tools. The Developer
Guide shows how the shell is built and how to add a command to it.

This book is also a [PDF](spelaion.pdf). Every block of code in it ran against spelaion when the book was
built, and the output under it is what it printed. Each chapter's finished
program is in
[`docs/examples/`](https://github.com/syalia-srl/spelaion/tree/main/docs/examples).

spelaion began as a copy of agentsh by Mayflower GmbH, under the MIT license,
which is kept in
[`LICENSES/agentsh-MIT.txt`](https://github.com/syalia-srl/spelaion/blob/main/LICENSES/agentsh-MIT.txt).
