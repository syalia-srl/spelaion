import shutil
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

work = Path(tempfile.mkdtemp())
(work / "plan.yaml").write_text("name: demo\nwalls:\n  - 4.0\n  - 3.5\n")
(work / "words.txt").write_text("red\nblue\nred\n")
sb = Sandbox([Mount("/work", host=work)], cwd="/work")
probes = [
    ("arrays", 'names=(a b c); echo "${names[1]} ${#names[@]}"'),
    ("parameter expansion", 'f=plan.yaml; echo "${f%.yaml}"'),
    ("arithmetic", "echo $(( (3 + 4) * 2 ))"),
    ("here-document", "cat <<EOF\nvalue: $((1 + 1))\nEOF"),
    ("PIPESTATUS", "false | true | false; echo ${PIPESTATUS[*]}"),
    ("text", "sort words.txt | uniq -c | sort -rn | head -1"),
    ("search", "grep -c red words.txt"),
    ("structured", "yq '.walls | length' plan.yaml"),
    ("archive", "tar cf out.tar plan.yaml && tar tf out.tar"),
    ("host program", "git status"),
]
for label, command in probes:
    r = sb.bash(command)
    lines = (r.stdout or r.stderr).strip().splitlines()
    print(f"{label:20} {r.exit_code:3}  {lines[0] if lines else ''}")
sb.close()
shutil.rmtree(work)
