# How spelaion is built

You are about to change spelaion. Your product may need a command it does not
have, a piece of syntax may be missing, or you may want the rule for a write to
be stricter. Before you write the change you need to answer two questions:
which package owns that decision, and what happens to one line of shell between
the text the agent sends and the result it reads.

This chapter answers both by following one line through every layer:
`grep -n TODO notes.txt | sort`, run over a project mounted at `/proj`. The
program the blocks build is that trace: it parses the line, resolves it, runs
it over a mount, and then runs it again in a sandbox child.

## The packages and their boundaries

`tach.toml` declares one module per package and lists the spelaion modules each
may import. `exact = true` closes the list: an import that is not declared
fails `uv run tach check`, and `uv run tach sync` rewrites the file from the
imports it finds in the code.

| Package | What it owns | May import |
|---|---|---|
| `spelaion.ast` | `Program`, `Pipeline`, `SimpleCommand`, `Word` and its segments, `Span` | nothing |
| `spelaion.vfs` | the `Filesystem` protocol, `MountFs`, `VirtualFilesystem` | nothing |
| `spelaion.runtime` | `ShellState`, `CommandResult`, `ShellOptions` | nothing |
| `spelaion.policy` | `PolicyConfig`, `PolicyEngine`, allow, deny and warn | nothing |
| `spelaion.tools` | `ToolRegistry`, the `AgentTool` protocol | runtime |
| `spelaion.parser` | the tree-sitter frontend, `normalize`, diagnostics | ast |
| `spelaion.commands` | 128 virtual commands and the `@command` registry | exec, runtime, vfs |
| `spelaion.exec` | the evaluators, builtins, redirections, pipelines | ast, commands, parser, runtime, semantics |
| `spelaion.semantics` | `resolve_command`, the planner, the expansion facade | ast, commands, exec |

The table is an allow-list of edges, not a proof of layering.
`forbid_circular_dependencies = false`, and two pairs do import each other:
`exec` and `commands`, since a command receives an `IOContext` from
`exec.redirs` and the evaluator reads `COMMANDS`; and `exec` and `semantics`,
since `semantics.expand` uses the word and arithmetic evaluators and
`exec.cmd_eval` calls `resolve_command`. What the packages do protect is
narrower. `spelaion.parser` is the only package that holds a tree-sitter
object, `MountFs.host_path` is the only code that turns a sandbox path into a
host path, and `Sandbox._start` is the only place that starts a process.

Two entry points sit above the nine. `spelaion.api` holds `Bash` and
`ShellEngine`, which run the shell in the caller's own process, and imports
all of the nine except `ast` and `commands`. `spelaion.cli` is the `spelaion`
command with its `parse`, `plan`, `run` and `fetch-python` subcommands, and
imports `api`, `ast` and `python`. A product that gives an agent tools holds a
`Sandbox` instead, which is the same shell in a child process, with mounts,
limits and host commands.

The nine packages are the shell. The process around it lives outside them, in
`_shell`, `_child`, `_wire`, `_host`, `_tools`, `_mcp`, `python` and `sandbox`:

- `_shell` runs one call, `bash`, `edit` or `write`, over a `MountFs`, and
  truncates both output streams to `Limits.max_output`;
- `_child` is the bootstrap and the serve loop inside the child;
- `_wire` in `src/spelaion/_wire.py` holds the six message tuples and the
  restricted unpickler;
- `_host` holds `HostContext`, `show` and the attachment limits;
- `_tools` builds the three `Tool` objects and the `bash` description;
- `_mcp` serves those tools over MCP;
- `python` holds the cache builder and the wasmtime runner;
- `sandbox` is the parent side, the class the product uses.

## The line becomes a tree

```{python export=examples/architecture.py}
import json
import os
import shutil
import signal
import tempfile
import time
from pathlib import Path

from spelaion import HostContext, Limits, Mount, Result, Sandbox
from spelaion._wire import max_message
from spelaion.ast.to_dict import ast_to_dict
from spelaion.exec.executor import Executor
from spelaion.exec.redirs import IOContext
from spelaion.parser.frontend import parse_script
from spelaion.parser.normalize import normalize
from spelaion.policy.decisions import PolicyEngine
from spelaion.policy.rules import PolicyConfig
from spelaion.runtime.state import ShellState
from spelaion.semantics.resolve import resolve_command
from spelaion.tools.registry import ToolRegistry
from spelaion.vfs.filesystem import VirtualFilesystem
from spelaion.vfs.mounts import MountFs

project = Path(tempfile.mkdtemp())
(project / "notes.txt").write_text("TODO: paint\ndone: call\nTODO: tiles\n")
line = "grep -n TODO notes.txt | sort"

parsed = parse_script(line)
print("root:", parsed.root_node.type, "| has_errors:", parsed.has_errors)
```

`spelaion.parser.frontend.parse_script` encodes the text as UTF-8, parses it
with one module-level `Parser` and the `tree-sitter-bash` grammar, and walks
the tree for `ERROR` and missing nodes. It returns a `ParseResult` with the tree, the source, the
diagnostics and `has_errors`. The root is a `program`. This is the last place a
tree-sitter object exists: the parse tree is a CST, with every token and every
piece of whitespace, and nothing downstream imports it.

```{python continue export=examples/architecture.py}
program, diagnostics = normalize(parsed.root_node, line)
tree = ast_to_dict(program)
pipeline = tree["body"][0]
print(tree["type"], "->", pipeline["type"], "with", len(pipeline["commands"]), "stages")
print(json.dumps(pipeline["commands"][0], indent=2))
print("diagnostics:", len(diagnostics))
```

`spelaion.parser.normalize.normalize(root, source)` is the second step. It maps
each CST node through a handler table into the project's AST and returns a
`Program` plus diagnostics.
A named node with no handler raises `UnsupportedSyntaxError`, which the caller
turns into a warning and leaves out.

The output is the whole shape of the line. The `Program` holds one `Pipeline`
with two stages; the first stage is a `SimpleCommand` with four words and no
assignments. `-n` is a literal, and `grep` is a literal: expansion happens at
run time, against a `ShellState` that does not exist yet. Each word is a list
of segments rather than a string because a word may mix literal text, quotes, a
parameter expansion, a command substitution and a glob, and the segment list
keeps them apart until the evaluator expands them. Every node carries a `Span`
with byte offsets and row and column, which is what a diagnostic points at.

`spelaion.ast.to_dict.ast_to_dict` covers the structural nodes: `Program`,
`Sequence`, `AndOrList`,
`Pipeline`, `SimpleCommand`, `Group`, `Subshell` and `FunctionDef`. An `if`, a
loop, a `case` or a redirected command prints only its type name, so the JSON
is a view for reading, not a serializer for the whole AST.

One warning does not reach a sandbox call. `Shell.bash` checks
`parsed.has_errors` and discards the diagnostics that `normalize` returns. A
construct the normalizer can only partly model becomes a warning and an empty
command:

```{python continue}
_, warnings = normalize(parse_script("(( x = 1 ))").root_node, "(( x = 1 ))")
print(warnings[0].message)
```

`(( x = 1 ))` is dropped: the call returns 0 and prints nothing, while
`ShellEngine.parse` would show the warning. Keep that in mind when a new
construct seems to work but has no effect; the shell's own gaps are in
[The shell](what-the-shell-can-do.html).

## Three tiers, then the evaluator

```{python continue export=examples/architecture.py}
state = ShellState()
definition, _ = normalize(
    parse_script("greet() { echo hi; }").root_node, "greet() { echo hi; }"
)
Executor(
    state=state,
    vfs=VirtualFilesystem(),
    tools=ToolRegistry(),
    policy=PolicyEngine(config=PolicyConfig()),
).execute_node(definition, IOContext())


class Deploy:
    name = "deploy"

    def invoke(self, args, stdin=None):
        raise NotImplementedError


tools = ToolRegistry()
tools.register("deploy", Deploy())
for name in ("greet", "sort", "deploy", "nope"):
    print(f"{name:7} {resolve_command(name, state, tools).kind}")
```

`spelaion.semantics.resolve` holds the order in one function,
`resolve_command`: a name in `state.functions` is a function, a name in
`BUILTIN_NAMES` is a builtin, a name in the `ToolRegistry` is an `agent_tool`,
and anything else is `not_found`. `BUILTIN_NAMES` is the
union of the 42 names in `_SHELL_BUILTINS` and the 128 in `COMMANDS`, so a
virtual command such as `sort` resolves in the builtin tier. The shell's
implementation table `BUILTINS` has 39 entries, because `[[`, `source` and `.`
are handled by the evaluator or by a special case before the table. The third
kind is called `agent_tool` in the code and a host command in the product; in a
`Sandbox` the registry holds one `_HostProxy` per host command, and the stub in
the block stands in for it because resolution only asks whether the name is
there. The last kind prints `command not found` and exits 127.

Resolution names the tier. `spelaion.exec.executor.Executor` runs it. The
constructor builds four
evaluators, `WordEvaluator`, `ArithEvaluator`, `BoolEvaluator` and
`CommandEvaluator`, and patches the word evaluator's command-substitution hook
to the command evaluator's, which closes the loop for `$(...)`. `execute_node`
matches on the AST type; the simple-command path is the one to know: prefix
assignments, word expansion, redirections, a policy check, resolution, dispatch,
and then the redirection buffers are written back to the filesystem. A pipeline
with two or more stages gives each stage an `IOContext` whose stdin is the
previous stage's stdout, and runs the stages one after another, so `yes | head`
stops at its own line cap rather than at a closed pipe. Each status goes into
`PIPESTATUS`.

The policy check is `check_command` and nothing else. `PolicyEngine` also has
`check_path_read`, `check_path_write` and `check_tool`, but no caller in the
shell uses them. Today the rules match a command name and the evaluator acts
only on `deny`: `warn` behaves as allow, the default is allow, and a deny
prints `denied by policy` and exits 126.
`ShellState.deadline` is checked at the top of every node: once it passes,
`execute_node` raises `TimeoutExpired`, which unwinds to the `timeout` command
that set it.

```{python continue export=examples/architecture.py}
fs = MountFs([Mount("/proj", host=project)])
state = ShellState()
state.cwd = "/proj"
io = IOContext()
executor = Executor(
    state=state, vfs=fs, tools=tools, policy=PolicyEngine(config=PolicyConfig())
)
exit_code = executor.execute_node(program, io).exit_code
print(io.stdout.getvalue(), end="")
print("exit:", exit_code)
```

This is the shell without the process: the same `parse_script`, `normalize` and
`Executor` calls the child makes, over a `MountFs` instead of a
`VirtualFilesystem`, and an `IOContext` in place of the call's result.
`_shell.Shell.bash` is those three calls in order, with a fresh `ShellState`
for every call. It sorted the two matching lines and returned 0.

## One resolver, two filesystems

Every path the agent names, from the shell, from `edit` and `write`, and from
`ctx.path()` in a host command, becomes a host path in
`spelaion.vfs.mounts.MountFs.host_path`, and nowhere else. That is the security model in one sentence. The method does four
things:

1. it normalises the path lexically, so `..` stops at `/`;
2. it takes the longest mount point that prefixes the path, and raises
   `ENOENT` when there is none;
3. it joins the rest to the mount's host folder, resolves symlinks, and refuses
   a result outside that folder with `EACCES`;
4. for a write it refuses when the host folder is gone (`ENOENT`), when the
   mount is read-only (`EROFS`), or when the disk is full (`EDQUOT`).

```{python continue export=examples/architecture.py}
readonly = MountFs([Mount("/proj", host=project, readonly=True)], max_disk=1_000_000)
print(readonly.host_path("/proj/notes.txt").relative_to(project.resolve()))
print(
    "normalised:",
    readonly.host_path("/proj/../proj/notes.txt")
    == readonly.host_path("/proj/notes.txt"),
)
print("root:", readonly.listdir("/"))
os.symlink("/etc", project / "escape")
for path in ("/etc/passwd", "/proj/escape/passwd"):
    try:
        readonly.host_path(path)
    except OSError as e:
        print(path, "->", type(e).__name__, e.strerror)
try:
    readonly.host_path("/proj/new.txt", write=True)
except OSError as e:
    print("write ->", type(e).__name__, e.strerror)
```

The root and the folders above a mount point are synthetic: `listdir("/")`
returns the mount names even though no host folder holds them. Errors are
rebuilt with the sandbox path by `_as_sandbox`, so a command's message never
names a host folder. `disk_used()` walks the writable mounts and sums their
regular files; `write` refuses a write that would pass `max_disk`, and
`host_path(write=True)` refuses while the total is already over it. `unlink`
and `rename` use `_entry`, which resolves the parent and leaves the last
component unfollowed, so a symlink is removed rather than its target.

The other implementation of the `Filesystem` protocol is `VirtualFilesystem`, a
tree of `DirNode` and `FileNode` objects in memory. It has no host path and no
`host_path`; its paths exist only in the object. `Bash` runs on it:

```{python continue}
from spelaion import Bash
from spelaion.vfs.filesystem import VirtualFilesystem

b = Bash(files={"/data/plan.txt": "ship it\n"})
print(b.run("cat /data/plan.txt | tr a-z A-Z").stdout, end="")
print(type(b.vfs).__name__, isinstance(b.vfs, VirtualFilesystem))
```

`Bash` keeps one `ShellState` and one `VirtualFilesystem` across `run` calls,
which is useful for tests of the shell itself; a `Sandbox` builds a fresh
`ShellState` for every call and keeps only the files, since those are real. The
protocol is the seam: every command receives `(args, ShellState, Filesystem,
IOContext)` and works through those methods, so the same `grep` runs on either
filesystem. [The in-memory Bash](testing-shell-scripts-with-bash.html) has the rest.

## The product's process and its child

A `Sandbox` runs in the product's process. Its constructor checks the mounts,
builds a `MountFs`, and calls `_start`, which makes a `socket.socketpair()` and
starts `[sys.executable, "-I", "-c", _child.BOOTSTRAP, str(fd)]` with the
child's end in `pass_fds` and the standard streams on `DEVNULL`. `-I` makes the
child ignore `PYTHON*` variables and the user's site folder, so the product's
environment cannot change what the child imports. The parent then sends its own
`sys.path` and the pickled `(mounts, cwd, env, limits, python_folder,
host_names)` as the first message on the socket, and the child's bootstrap, a
few lines of standard library, receives them and imports `spelaion._child` from
that path. It never imports the product's main script.

Before serving, the child sets `RLIMIT_DATA` to `memory_mb`, sets `RLIMIT_FSIZE`
to `max_disk` and ignores `SIGXFSZ` so a write past it fails with `EFBIG`
instead of ending the process, ignores `SIGINT` because Ctrl-C reaches the
whole group and the parent decides, and restores `SIGALRM`'s default action so
a timer can end even a C loop. It builds one `Shell` over a `MountFs`, installs
the python runner when there is one, registers a `_HostProxy` for every host
command, and sends `("ready",)`. Then it serves until the socket closes.

The messages are picklable tuples:

| Message | From to | When |
|---|---|---|
| `("ready",)` | child to parent | once, after the shell exists |
| `("call", kind, payload)` | parent to child | one `bash`, `edit` or `write` call |
| `("host", name, args, stdin, cwd, env)` | child to parent | a host command is invoked |
| `("host_result", result)` | parent to child | that command's `Result`, text only |
| `("register", name)` | parent to child | a host command registered after start |
| `("done", result)` | child to parent | the call's `Result` |

The parent trusts nothing it reads. It reads at most `max_message(limits)`
bytes, which is `8 * max_output + 1_000_000` (1,240,000 at the default
`max_output`), unpickles with a `find_class` that allows only `Result` and
`Attachment`, and checks the tuple's tag and shape. A child that sends anything
else is not trusted to go on: `_refused` restarts it and returns 125 with
`spelaion: child sent a bad message; restarted`. The tests produce the three
bad shapes with `forge_for_test`, registered in the child only when
`SPELAION_TEST_HOOKS=1`.

A call holds the sandbox lock, so two calls to one sandbox run one after the
other. `_call` restarts a child that is already dead before sending. If the
child dies before reading the call, the socket resets and the call is sent once
more, because it never ran. If it dies after reading, `_died` reaps it,
restarts, and returns 125 with `spelaion: child exited (code); restarted`. On
the deadline the parent restarts the child and returns 124 with
`timed_out=True`; the child's own timer at `timeout_s + 5` and python's epoch
at `+0.5 s` are backups for a parent that died mid-call.

A host command is served in the parent. The `("host", ...)` message carries the
expanded arguments, stdin, cwd and the exported environment as the child sees
them at that moment; `_serve_host` builds a `HostContext` with `remaining_s`,
calls the handler in the product's process, turns an exception into
`name: message` with a sandbox path and exit 1, wraps the exit code into
0-255, and sends back text only. Attachments stay in the parent and are put on
the call's `Result`. Anything the handler prints goes to the product's stdout,
not to the agent.

```{python continue export=examples/architecture.py}
sb = Sandbox(
    [Mount("/proj", host=project, readonly=True)],
    cwd="/proj",
    limits=Limits(timeout_s=1),
)


@sb.command("deploy")
def deploy(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout="deployed\n")


print("pid:", sb._child_pid)
r = sb.bash(line)
print(r.stdout, end="")
print("exit:", r.exit_code)
typed = sb.bash("type deploy show sort echo nope")
print(typed.stdout, end="")
print(typed.stderr, end="")
pid = sb._child_pid
os.kill(pid, signal.SIGKILL)
time.sleep(0.1)
print("killed:", pid, "poll:", sb._process.poll())
print("next:", sb.bash("echo alive").stdout.strip(), "pid:", sb._child_pid)
r = sb.bash("sleep 3")
print("timeout:", r.exit_code, r.timed_out, repr(r.stderr), "pid:", sb._child_pid)
print("max message:", max_message(sb.limits))
sb.close()
shutil.rmtree(project)
```

The block reaches into `_child_pid` and `_process` to show the mechanism, as the
tests do. `os.kill` ended the first child between calls, so the next `bash`
noticed with `poll()` and restarted before sending; the call succeeded and only
the pid changed. The timeout call returned 124 and also restarted. `type` went
through the same tiers the earlier block resolved in-process, and `show`
answered as a host command because every sandbox registers it.

## python is a guest in the same child

With `python=True`, the child installs a runner for `python` and `python3`;
both names are virtual commands, and `python_cmd.install` replaces what they do.
The runner in `src/spelaion/python/runner.py`, `run_python`, starts no process.
It opens one wasmtime `Store`, preopens `/lib` and `/site` read-only and each
mount at its own path with `mutable=not m.readonly`, sets argv to
`["python", "-m", "_boot", cwd, "--", *args]`, and gives the guest
`PYTHONPATH=/site`, `PYTHONDONTWRITEBYTECODE=1` and `PWD`. stdin, stdout and
stderr are three files in a temporary folder, because WASI has no pipes here.
`_boot` changes to the cwd inside the guest and implements `-c`, `-m`, a script
and `-` with the `sys.argv` CPython would set.

The bounds sit on the same store. `set_limits(memory_size=memory_mb)` counts the
guest's linear memory inside the child's `RLIMIT_DATA`. `set_epoch_deadline(1)`
with `epoch_interruption` lets a watcher thread stop the guest: every 0.1 s it
checks the deadline, the size of the two output files past `4 * max_output`
bytes or the disk cap, whichever is smaller, and `disk_used()` past the cap,
then calls `engine.increment_epoch()`. The
interrupted trap becomes `python: timed out` with 124 or
`python: output limit reached` with 1. After the run, a disk total over the cap
adds `python: disk cap exceeded` and forces exit 1. The compiled module is
cached in the child's memory, so later calls in the same child load it once.

The folder it loads comes from a cache:

```{python continue}
from spelaion.python.fetch import PYTHON_WASI, cache_dir, compiled_name, site_name
from spelaion.python.runner import prepared

folder = cache_dir() / f"python-{PYTHON_WASI['version']}"
print(folder.name, "prepared:", prepared(folder))
print("compiled:", compiled_name())
print("site:", site_name())
if folder.is_dir():
    print(sorted(p.name for p in folder.iterdir()))
```

`cache_dir()` is `$SPELAION_CACHE`, else `$XDG_CACHE_HOME/spelaion`, else
`~/.cache/spelaion`. `python-3.14.9/` holds `python.wasm` (the pinned release,
checked by sha256), `python.wasm.cwasm-<wasmtime version>` (the compiled
module), `lib/` (the standard library compiled to bytecode) and
`site-<12 hex>/` (PyYAML and `_boot`, compiled). The three names answer three
different upgrades: the build names the folder, the wasmtime version names the
compiled module, and a hash of `_boot` and the vendored PyYAML names the site
folder, so a new spelaion or wasmtime never runs a file an older one wrote. Only
the parent builds the folder (`ensure_python`, called from the `Sandbox`
constructor when `python=True`); a child that finds it missing prints a message
and exits 127. A writable mount may not hold the cache or lie inside it,
because the cache holds native code the next process loads.
[python](running-python-in-the-sandbox.html) covers the guest from the user's side.

## Where a change goes

- A virtual command goes in `src/spelaion/commands/`, registered with
  `@command("name")`. It receives the expanded arguments, the `ShellState`, a
  `Filesystem` and an `IOContext`, and returns a `CommandResult`; it must work
  through the protocol, so it never learns a host path, and it must not resolve
  or run another command. Its module must be imported in `commands/__init__.py`,
  which is what registers it, and the name then enters `COMMANDS` and
  `BUILTIN_NAMES`. Add a case to `tests/battery` and a test.
  [Adding a command](22-adding-a-command.md) walks through one.
- A shell builtin goes in `exec/builtins.py`, and its name must also be in
  `semantics.resolve._SHELL_BUILTINS`. The tables are separate: a name in
  `BUILTINS` but not in the resolution set is never found, and a name in the
  resolution set with no implementation reports `builtin not implemented` and
  exits 2.
- New syntax needs three changes in three packages: a node or segment in
  `spelaion.ast`, a handler in `parser/normalize.py`, and a case in
  `exec/cmd_eval.py` or one of the evaluators. Until all three exist the syntax
  is a warning and a dropped node.
- A host command needs no change here; `@sb.command` registers a Python function
  in the product's process ([host commands](giving-the-agent-powers-with-host-commands.html)).
- A path rule belongs in `MountFs.host_path` or `_entry` and nowhere else. Read
  [the security model](the-security-model.html) before you loosen one.
- A limit starts in `Limits` in `_types.py` and then reaches `_child` for the
  rlimits and the timer, `_shell` for truncation, `MountFs` for the disk cap and
  `python/runner.py` for the guest ([Bounding every call](bounding-every-call.html)).

The gates are five: `ruff check`, `ruff format --check`, `pyright`,
`tach check` and `pytest -q`, and CI runs all of them. The book adds its own:
`make docs-check` renders every chapter, tangles every example, runs it, and
checks that every exported name, public method and command is named in the
docs.
