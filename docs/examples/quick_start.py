import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

project = Path(tempfile.mkdtemp())
(project / "notes.md").write_text("# Notes\n\n- buy paint\n- call the plumber\n")
sb = Sandbox([Mount("/work", host=project)], cwd="/work")
r = sb.bash("ls && grep -c '^- ' notes.md")
print(r.stdout, end="")
print("exit code:", r.exit_code)
print(sb.bash("ls /").stdout, end="")
r = sb.bash("cat /etc/passwd")
print(r.stderr, end="")
print("exit code:", r.exit_code)
sb.edit("/work/notes.md", old="- buy paint", new="- buy paint (white)")
sb.write("/work/todo.txt", "plumber on Monday\n")
print(sb.bash("cat notes.md todo.txt").stdout, end="")
print(sorted(p.name for p in project.iterdir()))
sb.close()
