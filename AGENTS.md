# AGENTS.md

## What this is

spelaion is a Python library that gives an AI agent a shell that looks like bash
and a python with the full standard library, while the agent sees only the
folders the host mounts: no network, no other agent's files, no host binaries.
The host extends it with commands written in Python. It began as a copy of
an MIT-licensed shell by Mayflower GmbH; their license is kept in `LICENSES/`.

The shell is pure Python: a tree-sitter-bash parser, a project-owned AST, an
evaluator with three-tier resolution (function, builtin, virtual command) and
about 160 commands, over a virtual filesystem.

## Constraints

- The repo is public: nothing in code, docs, issues or commits names people,
  machines, servers or accounts. Products (Oikos, Skene) may be named.
- The agent never starts a host binary. No `subprocess` and no `shell=True` in
  production code; the only process spelaion may start is its own child Python.
- Every path from the agent, from `edit`/`write` and from `ctx.path()` goes
  through `MountFs.host_path()`. No other code turns a sandbox path into a host
  path.
- Tool names are exactly `bash`, `edit`, `write`.
- Defaults: `Limits(timeout_s=30, max_output=30_000, max_disk=50_000_000, memory_mb=1024)`.
- Truncation notice, exact copy: `[… {n} lines cut; narrow with grep or head]`.
- Keep parser, AST, semantics and executor as separate layers; tach enforces
  the boundaries in `tach.toml`.
- Unsupported syntax gives an explicit diagnostic, never a silent fallback.
- No publishing to PyPI without asking the maintainer first. The first release
  is a GitHub tag.

## Gates

All five pass before every commit, and CI (`.github/workflows/ci.yml`) runs them:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run tach check
uv run pytest -q
```

After adding an import between modules, `uv run tach sync` updates `tach.toml`.

## Layout

```
src/spelaion/
  api/        # Bash class, ShellEngine
  ast/        # AST node types (leaf module)
  cli/        # spelaion parse|plan|run
  commands/   # virtual commands, registered with @command("name")
  exec/       # evaluators
  parser/     # tree-sitter frontend + normalization
  policy/     # allow/deny/warn rules
  runtime/    # ShellState, CommandResult
  semantics/  # resolution, expansion, planner
  tools/      # agent tool registry
  vfs/        # in-memory virtual filesystem
```

## Spec and plan

The design spec (`2026-11-07-spelaion-design.html`) and its implementation plan
(`plans/2026-11-07-spelaion.html`) are kept with the maintainers' architecture
notes, outside this repo. Work follows the plan's tasks in order.
