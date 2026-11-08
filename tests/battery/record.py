"""Record what real bash prints for each battery case into ``expected.json``.

Developer tooling, never on the agent path: it runs ``bash`` on the host.
Each case gets fresh copies of ``fixtures/project`` and an empty scratch
folder under a temporary root; ``/project`` and ``/scratch`` in the command
become paths under that root, and the root is cut from the output again.

    uv run python tests/battery/record.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from cases import CASES  # noqa: E402

FIXTURES = HERE / "fixtures" / "project"
EXPECTED = HERE / "expected.json"


def record_one(command: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        shutil.copytree(FIXTURES, root / "project")
        (root / "scratch").mkdir()
        text = command.replace("/project", f"{root}/project").replace(
            "/scratch", f"{root}/scratch"
        )
        env = {
            "PATH": os.environ["PATH"],
            "HOME": str(root / "scratch"),
            "LC_ALL": "C.UTF-8",
        }
        done = subprocess.run(
            ["bash", "-c", text],
            cwd=root / "scratch",
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "stdout": done.stdout.replace(str(root), ""),
            "exit_code": done.returncode,
        }


def main() -> None:
    version = subprocess.run(
        ["bash", "-c", "echo $BASH_VERSION"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if not version.startswith("5."):
        raise SystemExit(f"record with bash 5, not {version}")
    expected = {case.name: record_one(case.command) for case in CASES}
    EXPECTED.write_text(json.dumps(expected, indent=2, ensure_ascii=False) + "\n")
    print(f"recorded {len(expected)} cases with bash {version}")


if __name__ == "__main__":
    main()
