# Running a harness with spelaion's tools only

spelaion gives an agent three tools, `bash`, `edit` and `write`, over the
folders you mount. Those tools are its whole reach only if the harness that
drives the model adds nothing of its own. The harness must run with:

- **its own tools off.** Built-in shells, file readers, web fetchers and
  sub-agents all reach the host directly.
- **these three MCP tools and no others.** No MCP server from the user's or
  the machine's configuration.
- **an isolated configuration.** A config folder of its own, so the user's
  settings, hooks, plugins, skills and memory are not loaded.
- **an empty working folder unrelated to the sandbox.** Harnesses read
  instruction files (`CLAUDE.md`, `AGENTS.md`, `.claude/skills`) from their
  working folder and its parents. Do not start one inside a mounted folder.
- **spelaion over HTTP.** `Sandbox.serve_mcp()` serves MCP's streamable HTTP
  only. OpenCode needs that: it hides a stdio server's tools behind its own
  `execute` tool, which is a built-in and is turned off with the rest.

`serve_mcp(token=...)` makes every request carry
`Authorization: Bearer <token>`. Give the harness the token in its MCP
config, never on its command line.

## Who keeps the recipe

The flags that contain each harness change between releases. aegis keeps
them per harness and tests them against the real binaries:
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
the Claude Code recipe below is the same one.

## Claude Code without aegis

Checked on Claude Code 2.1.296.

```bash
claude -p "<prompt>" --output-format stream-json --verbose \
  --allowedTools mcp__spelaion \
  --tools "" \
  --strict-mcp-config \
  --mcp-config /path/to/mcp.json
```

run with `CLAUDE_CONFIG_DIR` set to a folder of its own and from an empty
working folder.

- `--tools ""` turns every built-in tool off.
- `--strict-mcp-config` ignores every MCP server except those in
  `--mcp-config`.
- `--mcp-config` names the server `spelaion`, so its tools are
  `mcp__spelaion__bash`, `mcp__spelaion__edit` and `mcp__spelaion__write`:

  ```json
  {
    "mcpServers": {
      "spelaion": {
        "type": "http",
        "url": "http://127.0.0.1:PORT/mcp",
        "headers": {"Authorization": "Bearer TOKEN"}
      }
    }
  }
  ```

  The file holds the token: write it with mode 0600, outside the working
  folder, and delete it after the run.
- `--allowedTools mcp__spelaion` lets the three tools run in print mode,
  where nobody is there to approve a call.
- `CLAUDE_CONFIG_DIR` points at a folder that holds only a login. Make it
  once with `CLAUDE_CONFIG_DIR=<folder> claude /login`.
- `--bare` would skip settings and `CLAUDE.md` discovery too, but it reads
  only `ANTHROPIC_API_KEY` or an `apiKeyHelper` given with `--settings`,
  never an OAuth login. With a subscription login, use the dedicated config
  folder instead.

The `system`/`init` event at the start of the stream lists the tools the
model got. With this recipe it lists exactly the three.

### The example

[`examples/serve.py`](../examples/serve.py) serves a sandbox over a temporary
`/scratch` with one host command, `greet`, and prints the URL and a fresh
token until Ctrl-C:

```bash
uv run python examples/serve.py
```

[`examples/claude_code.py`](../examples/claude_code.py) serves the same
sandbox in its own process, writes the MCP config in a temporary folder,
runs `claude` with the recipe above from an empty temporary folder, and
prints the init event's tools and the answer:

```bash
CLAUDE_CONFIG_DIR=~/.claude-spelaion claude /login     # once
SPELAION_CLAUDE_CONFIG_DIR=~/.claude-spelaion \
  uv run python examples/claude_code.py "greet the world from /scratch"
```

It never creates the config folder and never copies a login into it.

### The test

[`tests/harness/test_claude.py`](../tests/harness/test_claude.py) runs the
example with the prompt `say ok` and asserts that the init event lists
exactly the three tools. It is marked `harness` and skipped unless
`SPELAION_HARNESS=1` and `claude` is on `PATH`, so CI never runs it:

```bash
SPELAION_HARNESS=1 SPELAION_CLAUDE_CONFIG_DIR=~/.claude-spelaion \
  uv run pytest -m harness -q
```
