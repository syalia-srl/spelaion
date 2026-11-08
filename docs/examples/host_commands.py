import tempfile
from pathlib import Path

from spelaion import HostContext, HostHandler, Mount, Result, Sandbox

work = Path(tempfile.mkdtemp())
outbox = Path(tempfile.mkdtemp())
(work / "plan.md").write_text("# Plan\n\n- [ ] paint the fence\n- [ ] buy paint\n")
(work / "post.md").write_text("The fence is painted.\n")
sb = Sandbox([Mount("/work", host=work)], cwd="/work")


@sb.command
def check_plan(ctx: HostContext, args: list[str]) -> Result:
    if args or not ctx.stdin:
        return Result(stderr="check-plan: usage: check-plan < plan.md\n", exit_code=2)
    bad = [
        f"{number}: {line}"
        for number, line in enumerate(ctx.stdin.splitlines(), 1)
        if line and not line.startswith(("- [ ] ", "- [x] "))
    ]
    if bad:
        return Result(
            stderr="check-plan: not a plan step\n" + "\n".join(bad) + "\n", exit_code=2
        )
    return Result(stdout="plan ok\n")


r = sb.bash("cat plan.md | check-plan")
print(r.stderr, end="")
print("exit code:", r.exit_code)
sb.write("/work/plan.md", "- [ ] paint the fence\n- [ ] buy paint\n")
print(sb.bash("check-plan < plan.md").stdout, end="")


def make_publisher(token: str, outbox: Path) -> HostHandler:
    @sb.command("publish")
    def publish(ctx: HostContext, args: list[str]) -> Result:
        if len(args) != 1:
            return Result(stderr="publish: usage: publish DRAFT\n", exit_code=2)
        try:
            draft = ctx.path(args[0]).read_text()
        except OSError:
            return Result(stderr=f"publish: cannot read {args[0]}\n", exit_code=1)
        name = Path(args[0]).name
        (outbox / name).write_text(f"token: {token}\n\n{draft}")
        return Result(stdout=f"published {name}\n")

    return publish


make_publisher("token-2f8c", outbox)
print(sb.bash("check-plan < plan.md && publish post.md").stdout, end="")
print(
    sb.bash("grep -r 'token-2f8c' / || echo 'no token in the sandbox'").stdout, end=""
)
print(sb.bash("ls /").stdout, end="")
print((outbox / "post.md").read_text(), end="")
bash = next(tool for tool in sb.tools() if tool.name == "bash")
print(bash.description.split("Extra commands: ")[1])
print(sorted(p.name for p in outbox.iterdir()))
sb.close()
