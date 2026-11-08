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
sb = Sandbox(
    [Mount("/work", work, readonly=True), Mount("/scratch", scratch)],
    cwd="/scratch",
    python=True,
)


def attempt(label: str, result: Result) -> None:
    lines = (result.stderr or result.stdout).strip().splitlines()
    print(f"{label}: {lines[-1] if lines else 'no output'} (exit {result.exit_code})")


attempt("dot dot", sb.bash("cat /work/../private/key.txt"))
attempt("absolute", sb.bash("cat /etc/passwd"))
(scratch / "planted").symlink_to(private / "key.txt")
(scratch / "planted_dir").symlink_to(private)
attempt("planted symlink", sb.bash("cat planted"))
attempt("planted folder", sb.bash("cat planted_dir/key.txt"))
attempt("bash write", sb.bash("echo changed > /work/notes.md"))
attempt("edit", sb.edit("/work/notes.md", "hello", "changed"))
attempt("write", sb.write("/work/notes.md", "changed\n"))
attempt("python write", sb.bash("python -c \"open('/work/notes.md', 'w')\""))
print("host file:", repr((work / "notes.md").read_text()))
attempt("socket", sb.bash("python -c 'import socket; socket.socket()'"))
attempt("process", sb.bash("python -c 'import subprocess; subprocess.run([\"ls\"])'"))
attempt("host program", sb.bash("curl https://example.com"))


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
(scratch / "link.py").write_text(
    'import os\nos.symlink("../private/key.txt", "/scratch/out")\n'
)
r = sb.bash("python link.py")
print("guest made a symlink:", r.exit_code == 0)
attempt("follow guest symlink", sb.bash("cat /scratch/out"))
print("host sees a symlink:", (scratch / "out").is_symlink())
print("host follows it:", (scratch / "out").read_text() == "secret\n")
sb.close()
shutil.rmtree(root)
print("audit complete")
