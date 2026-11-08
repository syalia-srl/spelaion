import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

project = Path(tempfile.mkdtemp())
output = Path(tempfile.mkdtemp())
settings = "budget_s: 4.0\ncolumns: [name, seconds]\n"
(project / "settings.yaml").write_text(settings)
(project / "runs.csv").write_text(
    "name,seconds\nbuild,3.2\ntests,9.5\ndocs,1.1\nscan,6.4\n"
)
sb = Sandbox(
    [
        Mount("/project", host=project, readonly=True),
        Mount("/out", host=output),
    ],
    cwd="/project",
    python=True,
)
r = sb.bash("python3 -c 'import yaml; print(yaml.safe_load(open(\"settings.yaml\")))'")
print(r.stdout, end="")
sb.write(
    "/out/report.py",
    """\
import csv
import json

import yaml

settings = yaml.safe_load(open("/project/settings.yaml"))
with open("/project/runs.csv", newline="") as f:
    runs = list(csv.DictReader(f))
over = [r["name"] for r in runs if float(r["seconds"]) > settings["budget_s"]]
with open("/out/report.json", "w") as f:
    json.dump({"budget_s": settings["budget_s"], "over": over}, f)
print(len(runs), "runs,", len(over), "over budget")
""",
)
r = sb.bash("python3 /out/report.py")
print(r.stdout, end="")
print("exit code:", r.exit_code)
print((output / "report.json").read_text())
sb.close()
