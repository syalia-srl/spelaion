import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

root = Path(tempfile.mkdtemp())
project = root / "project"
drafts = root / "drafts"
project.mkdir()
drafts.mkdir()
(project / "plan.yaml").write_text(
    "name: tower\n"
    "height: 2.7\n"
    "levels: 3\n"
    "roof: flat\n"
    "walls: stone\n"
    "floors: 3\n"
    "garden: yes\n"
)
(project / "README.md").write_text("# Tower\n\nA plan for a small tower.\n")
sb = Sandbox(
    [
        Mount("/project", host=project, readonly=True),
        Mount("/drafts", host=drafts),
    ],
    cwd="/drafts",
    env={"PROJECT": "tower"},
)
print(sb.bash("ls /").stdout, end="")
print(sb.bash("pwd").stdout, end="")
print(sb.bash("echo $PROJECT").stdout, end="")
r = sb.bash("cat /etc/passwd")
print(r.stderr, end="")
print("exit code:", r.exit_code)
command = "MARK=kept; greet() { echo hello; }; cd /project; echo $MARK $PWD"
print(sb.bash(command).stdout, end="")
r = sb.bash("echo [$MARK] [$PWD]; greet")
print(r.stdout, end="")
print(r.stderr, end="")
print("exit code:", r.exit_code)
sb.bash("echo 'first draft' > /drafts/note.txt")
print(sb.bash("cat /drafts/note.txt").stdout, end="")
r = sb.bash("cat /drafts/note.txt /drafts/missing.txt")
print("stdout:", repr(r.stdout))
print("stderr:", repr(r.stderr))
print("exit code:", r.exit_code)
for name, r in [
    ("bash", sb.bash("echo broken > /project/plan.yaml")),
    ("write", sb.write("/project/plan.yaml", "broken\n")),
    ("edit", sb.edit("/project/plan.yaml", old="height: 2.7", new="height: 3.0")),
]:
    print(name, "->", r.exit_code, r.stderr.strip())
r = sb.bash("cp /project/plan.yaml /drafts/plan.yaml")
print("copied:", r.exit_code)
r = sb.edit("/drafts/plan.yaml", old="height: 2.7", new="height: 3.0")
print(r.stdout, end="")
print("exit code:", r.exit_code)
r = sb.edit("/drafts/plan.yaml", old="height: 9.9", new="height: 10.0")
print(r.stderr, end="")
print("exit code:", r.exit_code)
sb.write("/drafts/dupe.txt", "tower\ntower\n")
r = sb.edit("/drafts/dupe.txt", old="tower", new="keep")
print(r.stderr, end="")
print(sb.bash("cat /drafts/dupe.txt").stdout, end="")
r = sb.write("/drafts/notes/day-1/plan.md", "# Day 1\n\n- measure the site\n")
print("exit code:", r.exit_code)
print(sb.bash("find /drafts/notes").stdout, end="")
print((drafts / "plan.yaml").read_text(), end="")
found = [p.relative_to(drafts).as_posix() for p in drafts.rglob("*") if p.is_file()]
print(sorted(found))
print((project / "plan.yaml").read_text().splitlines()[1])
try:
    Sandbox([Mount("/project", host=root / "missing")])
except FileNotFoundError as e:
    print(str(e).replace(str(root), "<root>"))
(project / "secret").mkdir()
try:
    Sandbox(
        [
            Mount("/project", host=project),
            Mount("/secret", host=project / "secret", readonly=True),
        ]
    )
except ValueError as e:
    print(str(e).replace(str(root), "<root>"))
sb.close()
try:
    sb.bash("ls /")
except RuntimeError as e:
    print(e)
