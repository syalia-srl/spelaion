import json
import secrets
import shutil
import tempfile
from pathlib import Path

from spelaion import Mount, Sandbox

root = Path(tempfile.mkdtemp())
project = root / "project"
work = root / "work"
for folder in (project, work):
    folder.mkdir()
(project / "notes.md").write_text("# Notes\n\n- buy paint\n- call the plumber\n")

sb = Sandbox([Mount("/work", host=project, readonly=True)], cwd="/work")
token = secrets.token_urlsafe(32)
server = sb.serve_mcp(token=token)
print(server.url)
config = root / "mcp.json"
config.touch(mode=0o600)
servers = {
    "spelaion": {
        "type": "http",
        "url": server.url,
        "headers": {"Authorization": f"Bearer {token}"},
    }
}
config.write_text(json.dumps({"mcpServers": servers}))
shown = json.dumps({"mcpServers": servers}, indent=2).replace(token, "<token>")
print("mode:", oct(config.stat().st_mode & 0o777))
print(shown)
argv = [
    "claude",
    "-p",
    "<prompt>",
    "--output-format",
    "stream-json",
    "--verbose",
    "--allowedTools",
    "mcp__spelaion",
    "--tools",
    "",
    "--strict-mcp-config",
    "--mcp-config",
    str(config),
]
print(argv)
server.stop()
sb.close()
shutil.rmtree(root)
