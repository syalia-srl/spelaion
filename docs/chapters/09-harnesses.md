# Running Claude Code or OpenCode

A product agent answers questions about a user's project and must not change
it. spelaion already gives the model that project: `bash`, `edit` and `write`
over a read-only mount, and nothing else on the machine. What is missing is
the program that drives the model. You could write that loop yourself, as
[Your own loop](your-own-agent-loop.html) does, but Claude Code and OpenCode already do
it: they send the conversation to a model, read the tool calls it asks for,
run them and stop when it answers. You want one of them to drive, with
spelaion's three tools as its whole reach.

That last part is the work. A harness ships with a shell, a file reader, a web
fetcher, sub-agents and its own MCP servers. Any of those that stays on
reaches the host directly, around the mounts, and the sandbox then describes
only the calls the model makes through spelaion, not what the model can do.
This chapter starts a harness whose only tools are spelaion's three, over the
folders you mounted and no others.

## Five requirements

For spelaion's three tools to be the harness's whole reach, the harness must
run with:

- its own tools off. Built-in shells, file readers, web fetchers and
  sub-agents all reach the host directly.
- these three MCP tools and no others. No MCP server from the user's or the
  machine's configuration.
- an isolated configuration. A config folder of its own, so the user's
  settings, hooks, plugins, skills and memory are not loaded.
- an empty working folder unrelated to the sandbox. Harnesses read instruction
  files (`CLAUDE.md`, `AGENTS.md`, `.claude/skills`) from their working folder
  and its parents. Do not start one inside a mounted folder.
- spelaion over HTTP. `serve_mcp()` serves MCP's streamable HTTP and nothing
  else. OpenCode needs that: it hides a stdio server's tools behind its own
  `execute` tool, which is a built-in and is turned off with the rest.

`serve_mcp(token=...)` makes every request carry `Authorization: Bearer
<token>`. Give the harness the token in its MCP config, never on its command
line, where every user on the machine can read it from the process list.

## Serve the three tools

The parts of a run that need no login can be built and checked here: the
sandbox, the server, the config file and the argument list. The harness itself
runs afterwards, from a shell.

The project is mounted read-only, so the model can read it and a write from
the model is refused by the mount. The mount, not the harness's behaviour,
decides what the agent may change; [Giving the agent folders](giving-the-agent-folders.html)
covers the difference between the two kinds of mount.

```{python export=examples/harnesses.py}
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
```

The refusal comes back as an ordinary tool result:

```{python continue}
print(sb.write("/work/notes.md", "rewritten\n").stderr, end="")
```

`serve_mcp` serves the three tools over streamable HTTP, on a background
thread, and returns an `McpServer`. It listens on `127.0.0.1` only and on a
free port when the port is `0`, so the URL is known once the server is up:

```{python continue export=examples/harnesses.py}
token = secrets.token_urlsafe(32)
server = sb.serve_mcp(token=token)
print(server.url)
```

A request without the bearer token is turned away before it reaches a tool:

```{python continue}
import urllib.error
import urllib.request

try:
    urllib.request.urlopen(server.url, timeout=5)
except urllib.error.HTTPError as e:
    print("without the header:", e.code)
```

## The MCP config

Claude Code reads its MCP servers from a JSON file. The file here sits in the
temporary folder that holds the project and the working folder, outside the
working folder the harness starts in, and it is created with mode `0600`
before the token is written to it:

```{python continue export=examples/harnesses.py}
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
```

The name `spelaion` is the one the recipe uses, so the three tools arrive at
the model as `mcp__spelaion__bash`, `mcp__spelaion__edit` and
`mcp__spelaion__write`. The printed copy masks the token; the file holds the
real one and goes away with the folder. That is the whole file: one server
named `spelaion`, its URL and its bearer header. Write it with mode `0600`,
outside the working folder, and delete it after the run.

## The Claude Code command

Checked on Claude Code 2.1.296. The harness runs in print mode from an empty
working folder, with the config folder named in `CLAUDE_CONFIG_DIR`:

```bash
CLAUDE_CONFIG_DIR=~/.claude-spelaion \
claude -p "<prompt>" --output-format stream-json --verbose \
  --allowedTools mcp__spelaion \
  --tools "" \
  --strict-mcp-config \
  --mcp-config /path/to/mcp.json
```

- `-p` runs one prompt from the command line, with no terminal.
- `--output-format stream-json --verbose` writes one JSON event per line,
  which is how a program reads the run; in print mode the format needs
  `--verbose`.
- `--tools ""` turns every built-in tool off.
- `--strict-mcp-config` ignores every MCP server except those named in
  `--mcp-config`.
- `--mcp-config` names the file above.
- `--allowedTools mcp__spelaion` lets the three tools run in print mode, where
  nobody is there to approve a call.
- `CLAUDE_CONFIG_DIR` points at a folder that holds only a login. Make it once
  with `CLAUDE_CONFIG_DIR=<folder> claude /login`.

`--bare` would skip settings and `CLAUDE.md` discovery too, but it reads only
`ANTHROPIC_API_KEY` or an `apiKeyHelper` given with `--settings`, never an
OAuth login. With a subscription login, use the dedicated config folder
instead.

The example builds the same argument list:

```{python continue export=examples/harnesses.py}
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
```

A program that ends must stop the server and delete the folder itself.
Closing the sandbox does not stop the server; `stop()` does, and the token
goes with the folder.

```{python continue export=examples/harnesses.py}
server.stop()
sb.close()
shutil.rmtree(root)
```

## The init event

At the start of the stream, the `system`/`init` event lists the tools the
model got. With this recipe it lists exactly
`mcp__spelaion__bash`, `mcp__spelaion__edit` and `mcp__spelaion__write`. The
event is the cheapest check of containment: a built-in tool or another
server's tool on the list means the recipe is wrong, or the harness changed
how it reads one of the flags.

## Who keeps the recipe

The flags that contain each harness change between releases. aegis keeps them
per harness and tests them against the real binaries:
[`tests/test_live_product_agent.py`](https://github.com/syalia-srl/aegis/blob/ea988cfbd4975c9e8b8f88df3bca2837a18807da/tests/test_live_product_agent.py)
runs a session with the harness's tools off, an isolated config, one MCP
server and nothing else. It asserts that only that server's tools reach the
model, that a `CLAUDE.md`, an `AGENTS.md` and a `.claude/skills` planted in
the working folder never do, and that aegis writes nothing there. It was
measured on Claude Code 2.1.296 (the init event's tools were exactly
`['mcp__echo__ping']`, the working folder an empty isolated one) and on
OpenCode 2.1.2. Codex, pi and Cursor are not contained yet and aegis refuses
them in that mode.

Run spelaion through aegis to get that recipe kept for you. Without aegis,
the Claude Code recipe above follows the same rules: its own tools off, a
strict MCP config, an isolated config folder and an empty working folder. It
lets the MCP calls run with `--allowedTools` where aegis uses a hook.

## OpenCode

OpenCode follows the same five requirements, and spelaion's HTTP server is
what makes it possible: a stdio server's tools stay behind OpenCode's own
`execute` tool, which is a built-in and is turned off with the rest. The
flags differ from Claude Code's and change between releases, so the working
set for OpenCode 2.1.2 is the one aegis keeps and tests. Without aegis, apply
the five requirements to OpenCode's own options and check the first
conversation for the three tools.

## The example

[`examples/serve.py`](../examples/serve.py) serves a sandbox over a temporary
`/scratch` with one host command, `greet`, and prints the URL and a fresh
token until Ctrl-C:

```bash
uv run python examples/serve.py
```

[`examples/claude_code.py`](../examples/claude_code.py) serves the same
sandbox in its own process, writes the MCP config in a temporary folder, runs
`claude` with the recipe above from an empty temporary folder, and prints the
init event's tools and the answer:

```bash
CLAUDE_CONFIG_DIR=~/.claude-spelaion claude /login     # once
SPELAION_CLAUDE_CONFIG_DIR=~/.claude-spelaion \
  uv run python examples/claude_code.py "greet the world from /scratch"
```

It never creates the config folder and never copies a login into it. It gives
Claude Code this process's environment without the three variables that mark
a run inside another Claude Code session, `CLAUDECODE`,
`CLAUDE_CODE_ENTRYPOINT` and `CLAUDE_CODE_SSE_PORT`, so a harness started
from inside one behaves as a harness started from a shell. Provider and login
variables such as `CLAUDE_CODE_USE_BEDROCK` or `CLAUDE_CODE_OAUTH_TOKEN` pass
through.

## The test

[`tests/harness/test_claude.py`](../tests/harness/test_claude.py) runs the
example with the prompt `say ok` and asserts that the init event lists
exactly the three tools. It is marked `harness` and skipped unless
`SPELAION_HARNESS=1` and `claude` is on `PATH`, so CI never runs it:

```bash
SPELAION_HARNESS=1 SPELAION_CLAUDE_CONFIG_DIR=~/.claude-spelaion \
  uv run pytest -m harness -q
```

[`tests/harness/test_claude_env.py`](../tests/harness/test_claude_env.py)
checks the environment rule instead: the three session markers are dropped
and provider and login variables survive.

## Where to go next

- [MCP](serving-the-tools-over-mcp.html): the server behind these tools, its tool list and its
  authentication.
- [Bounding every call](bounding-every-call.html): the deadline, memory and output caps
  that apply to the harness's calls too.
- [Your own loop](your-own-agent-loop.html): the same three tools without a harness.
