# spelaion

[![CI](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml/badge.svg)](https://github.com/syalia-srl/spelaion/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A bash for agents, run from Python, with nothing real behind it.

spelaion is a Python library that gives an agent a shell that looks like bash and a python with the full standard library, while it sees only the folders the host mounts and reaches nothing else: no network, no other agent's files, no host binaries. The host extends it with commands written in Python, which run with the host's power and decide what the agent may do.

The name is Plato's cave (σπήλαιον, Republic VII): the prisoners see only the shadows someone casts on the wall. The agent sees only what the host mounts.

spelaion began as a copy of agentsh by Mayflower GmbH (MIT); see [LICENSES/agentsh-MIT.txt](LICENSES/agentsh-MIT.txt).

## Install

```bash
uv add git+https://github.com/syalia-srl/spelaion@v0.1.0
```

It needs Python 3.11 or later and is tested on Linux. `python` inside a sandbox runs CPython compiled to WASI, which is not in the wheel: the first sandbox made with `python=True` downloads it (about 14 MB, pinned by sha256) and prepares it in a cache folder (`$SPELAION_CACHE`, else `$XDG_CACHE_HOME/spelaion`, else `~/.cache/spelaion`). `spelaion fetch-python` does the same ahead of time.

## Example

```python
from spelaion import HostContext, Limits, Mount, Result, Sandbox

sb = Sandbox(
    mounts=[
        Mount("/project", host="data/p1", readonly=True),
        Mount("/know-how", host="agent/know-how", readonly=True),
        Mount("/scratch", host="scratch/p1"),  # the only writable one
    ],
    cwd="/scratch",
    env={"PROJECT": "p1"},
    limits=Limits(timeout_s=30, max_output=30_000, max_disk=50_000_000),
    python=True,
)


@sb.command("oikos")
def oikos(ctx: HostContext, args: list[str]) -> Result:
    # Runs on the host, trusted. ctx.path() maps a sandbox path to the real
    # one and refuses anything outside the mounts.
    plan = ctx.path(args[1])
    return Result(stdout=f"checked {plan.name}\n")


r = sb.bash("cp /project/plan.yaml . && oikos check plan.yaml")
r.stdout, r.stderr, r.exit_code, r.timed_out, r.attachments

sb.edit("/scratch/plan.yaml", old="height: 2.7", new="height: 3.0")
sb.write("/scratch/notes.md", "...")

sb.tools()       # the three tools as plain functions with JSON schemas
sb.serve_mcp()   # the same three tools over MCP
sb.close()       # or use the sandbox as a context manager
```

The three methods are the three tools: what the agent can do and what the host does on its behalf are the same calls. The host also reads and writes the mounted folders directly, since they are its own.

## Mounts and calls

A `Mount` maps a sandbox path to a host folder, read-only or writable. Paths outside every mount do not exist, and `/` lists the mount points. Every path from the shell, from `edit` and `write`, from python and from `ctx.path()` goes through one resolver, which normalises `..` lexically, picks the longest mount point, follows symlinks and refuses a result outside that mount's folder.

Files persist between calls, because they are real files. Shell state does not: variables, functions and `cd` start afresh from `cwd` and `env` on every `bash` call, so each call can be reproduced from its text alone.

Each sandbox runs its shell and its python in a child Python process of its own, started with the sandbox (about 100 ms) and alive as long as it. `Limits` bounds every call:

| Limit | Default | What happens past it |
|---|---|---|
| `timeout_s` | 30 | The child is killed and restarted with the same mounts; the call returns exit code 124 and `timed_out=True`. |
| `max_output` | 30 000 characters | stdout and stderr each keep their head and tail around `[… N lines cut; narrow with grep or head]`. |
| `max_disk` | 50 MB | The writable mounts together, whoever wrote the files. Shell, `edit` and `write` refuse a write over it; a python call that ends over it fails with a message. |
| `memory_mb` | 1024 | An rlimit on the child's data. The call fails with an out-of-memory message and the next one works. |

Calls to one sandbox run one at a time; a second waits for the first.

## python

`python` and `python3` run CPython 3.14 for WASI under wasmtime, inside the sandbox's child. The guest sees each mount at its own path, read-only where the mount is, and the standard library and PyYAML read-only at `/lib` and `/site`. WASI gives it no sockets and no processes. Each call is a fresh instance with the shell's arguments, stdin, working directory and environment, and its output flows through pipes like any command's:

```bash
python3 -c 'import yaml; print(yaml.safe_load(open("/project/plan.yaml"))["levels"])' | head
```

## Host commands

A host command is a Python function the agent calls like any other command, in pipes and redirections. It is the only way the agent affects the world beyond its writable mounts, and it runs in the host's process with the host's permissions, so it is trusted code. The shell, in the child, sends it the call and waits for its result. Secrets, tokens and product state stay in the closure that defines it; the sandbox never sees them.

```python
@sb.command            # named after the function: greet
def greet(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=f"hello, {' '.join(args) or 'world'}\n")


@sb.command("render")  # or named explicitly
def render(ctx: HostContext, args: list[str]) -> Result:
    out = ctx.path("/scratch/look.png", write=True)
    out.write_bytes(make_png(ctx.path(args[0]).read_text()))
    ctx.attach("/scratch/look.png")  # the model sees the image
    return Result(stdout="rendered\n")
```

A handler receives the arguments as the shell expanded them and a `HostContext` with:

- `stdin` (text), `cwd` and `env`, as the calling shell had them;
- `remaining_s`, the time left before the call's deadline; a handler that runs past it still finishes, but the call reports the timeout;
- `path(p, write=False)`, the resolver above, which raises on any path outside the mounts and, with `write=True`, on a read-only mount;
- `attach(data_or_path, mime=None)`, which hands a PNG, JPEG or WebP image back with the call's result.

It returns a `Result` with `stdout`, `stderr` and `exit_code`. An exception becomes an error result naming sandbox paths, never host ones. The built-in `show FILE...` is a host command that ships with spelaion and attaches images from the mounts.

## The three tools

| Tool | Arguments | Behaviour |
|---|---|---|
| `bash` | `command` | Runs the command in a fresh shell at the sandbox's `cwd`. Returns stdout, then `[stderr]` and its text, then `[exit code N]` when not 0, with attachments as images. |
| `edit` | `path`, `old`, `new` | Replaces the one occurrence of `old` with `new`. Fails, changing nothing, if `old` is missing or occurs more than once, and says which. Returns a few lines around the change. |
| `write` | `path`, `content` | Creates or replaces a whole file, creating parent folders inside the mount. Fails on a read-only mount or over the disk cap. |

The `bash` description the model reads names the folders, the working directory, the host commands and the timeout, and says what is not there (network, pip, background processes) so the agent does not spend turns finding out.

`sb.tools()` returns them as `Tool` objects (`name`, `description`, `input_schema`, `fn`) for a loop that calls the model itself. `fn(**arguments)` returns a `ToolOutput` with the text and the images.

## MCP

```python
import secrets

token = secrets.token_urlsafe(32)
server = sb.serve_mcp(token=token)   # 127.0.0.1, a free port
print(server.url)                    # http://127.0.0.1:PORT/mcp
...
server.stop()
```

`serve_mcp` serves the three tools over MCP's streamable HTTP from a background thread of the product's own process, where the host commands live. With a `token`, every request must carry `Authorization: Bearer <token>`; listening beyond loopback without one raises `ValueError`. [`examples/serve.py`](examples/serve.py) runs one until Ctrl-C.

A harness such as Claude Code or OpenCode must run with its own tools off, with these three tools and no others, with a configuration folder of its own and in an empty working folder. [docs/harnesses.md](docs/harnesses.md) gives the recipe and [`examples/claude_code.py`](examples/claude_code.py) runs Claude Code with it.

## Security model

- **Reachable:** the mounted folders (read-only ones only for reading), the standard library and PyYAML for python, and the host commands the product registers.
- **Not reachable:** any other file, the network, host binaries and processes. The shell is pure Python and never starts a program; python is WASI, which has no sockets or processes to grant.
- **The child process** holds the shell and python, so a stuck command or a runaway allocation is killed by the deadline or the memory rlimit and the product keeps running. The output and disk caps bound what one call can produce.
- **Out of scope:** a bug in wasmtime or in CPython's WASI build that escapes the guest, and anything a host command does, since host commands are the product's trusted code.
- The child is not a kernel sandbox: it runs as the product's user. The resolver, the WASI preopens and the absence of any way to start a process are what keep the agent inside.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## The shell

The interpreter parses with tree-sitter-bash into its own AST and evaluates it in Python: 128 commands and 39 builtins, among them grep, sed, awk, jq, yq, find, xargs, diff, patch, sort, uniq, cut, tr, head, tail, wc, tar and gzip. Syntax covers variables and parameter expansion, indexed and associative arrays, quoting, command and process substitution, arithmetic, `if`/`while`/`until`/`for`/`case`, `[ ]` and `[[ ]]`, functions, subshells, groups, pipelines, `&&`/`||`, redirections, here-documents and here-strings. Syntax it cannot parse is reported as an error. Where it parses a command and then does less than bash without saying so (awk's control flow, `cmd &`), the gap is listed under Known gaps.

`tests/battery` holds commands typical of coding agents (pipes into `head` and `tail`, `sed -i`, heredocs, `find | xargs`, `$(...)`, `diff -u`, `grep -rn`, `jq`, `python -c` with yaml). `record.py` runs each under real bash 5 and commits what it printed; the test runs each through a `Sandbox` and compares stdout and exit code.

## Known gaps

- awk is a subset: patterns, `print`, `printf`, assignments and arithmetic. It has no built-in functions (`length`, `substr`, `split`, `gsub`, ...) and no `if`, `for` or `while` inside actions, which it skips without an error.
- A here-document followed on its own line by `;` or `&` (`cat <<EOF; echo next`) is a syntax error; put the next command after the terminator. `>`, `|`, `&&` and `||` there work.
- `/dev/null` works in redirections only; `cat /dev/null` or `diff f /dev/null` say it does not exist.
- `cmd &` runs `cmd` in the foreground: there are no background processes or job control. `sleep` sleeps, within the call's deadline.
- `timeout N cmd` stops `cmd` with status 124 at the next command it runs or inside `sleep`. One long command (a python guest, a grep over a big tree) runs on until the call's deadline.
- `bash -c` and `sh -c` are not commands; a function does the same job.
- Symlinks and hard links cannot be created (`ln` fails with a message). `grep -r` follows a symlink to a file inside its mount, where GNU grep skips it.
- `ls -l` shows the same permissions for every file, and `which` prints `name: virtual command` rather than a path.
- Pipes carry text (UTF-8); binary data travels through files.
- Not available by design: network (no curl), pip, git, node and other host programs.
- A python guest can create a symlink with `../` that points out of its mount. It stays on the host: the sandbox's resolver refuses it, but another program on the host could follow it.

## The in-memory `Bash` class

`spelaion.Bash` runs the same shell in the calling process over an in-memory filesystem, with no mounts, no child process and no limits beyond the interpreter's own loop and recursion caps. No deadline bounds `sleep` or a long command there, only `timeout` does. It is for tests of the shell itself, not for agents:

```python
from spelaion import Bash

bash = Bash(files={"/data/a.txt": "hello\n"})
print(bash.run("cat /data/a.txt | tr a-z A-Z").stdout)  # HELLO
```

Unlike a `Sandbox`, a `Bash` keeps its variables, functions and working directory between `run` calls.

## Development

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run tach check
uv run pytest -q                 # -m "not wasi" skips the tests that need python
uv run python tests/battery/record.py   # re-record the battery under bash 5
```

[AGENTS.md](AGENTS.md) has the constraints and the layout.

## License

MIT, see [LICENSE](LICENSE). spelaion began as a copy of agentsh by Mayflower GmbH, MIT-licensed; their license is kept in [LICENSES/agentsh-MIT.txt](LICENSES/agentsh-MIT.txt).
