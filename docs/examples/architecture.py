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
program, diagnostics = normalize(parsed.root_node, line)
tree = ast_to_dict(program)
pipeline = tree["body"][0]
print(tree["type"], "->", pipeline["type"], "with", len(pipeline["commands"]), "stages")
print(json.dumps(pipeline["commands"][0], indent=2))
print("diagnostics:", len(diagnostics))
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
