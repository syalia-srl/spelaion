# AGENTS.md

## What this is

spelaion is a Python library that gives an AI agent a shell that looks like bash
and a python with the full standard library, while the agent sees only the
folders the host mounts: no network, no other agent's files, no host binaries.
The host extends it with commands written in Python. It began as a copy of
an MIT-licensed shell by Mayflower GmbH; their license is kept in `LICENSES/`.

The shell is pure Python: a tree-sitter-bash parser, a project-owned AST, an
evaluator with three-tier resolution (function, builtin, virtual command),
128 commands and 39 builtins, over the mounted folders (`MountFs`); the
in-memory filesystem remains for the `Bash` test class.

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

The book in `docs/` is the user and developer guide; `make docs-check` renders
it with every block run, runs the tangled examples and checks rift's coverage
rules, and the Docs workflow runs it on every pull request. A change to
behaviour updates the chapter that describes it; `docs/chapters/20-architecture.md`
has the layout. Never edit `docs/examples/`: the chapters tangle it.

After adding an import between modules, `uv run tach sync` updates `tach.toml`.

Tests marked `wasi` need CPython for WASI, which the first one downloads
(about 14 MB) and prepares (about 70 MB) in the cache: `$SPELAION_CACHE`, else
`$XDG_CACHE_HOME/spelaion`, else `~/.cache/spelaion`. CI caches that folder.
`uv run pytest -m "not wasi"` skips them.

## python

`python` and `python3` run CPython for WASI under wasmtime, in the sandbox's
child process (`src/spelaion/python/`). The guest sees `/lib` (the standard
library) and `/site` (PyYAML and `_boot`) read-only, and each mount at its
own path; WASI gives it no sockets and no processes. Mounts at `/lib` or
`/site` are refused when `python=True`.

- The cache folder is keyed on the build (`python-3.14.9/`), the compiled
  module on the wasmtime version (`python.wasm.cwasm-X.Y.Z`) and `site-HASH/`
  on its sources, so upgrading spelaion never runs files an older one left.
- Memory: the guest's linear memory counts against the child's `RLIMIT_DATA`
  (`memory_mb`), and no extra allowance is needed. Measured with wasmtime
  50.0.1: the child holds about 50 MB of data with the engine and module
  loaded; the largest `bytearray` that succeeds is 180 MB at `memory_mb=256`
  and 940 MB at 1024. Past that the guest gets `MemoryError`, and the next
  call works. Keep `RLIMIT_DATA`: with one instance the child's address
  space peaks near 5 GB (`VmPeak`), mostly reservations, which `RLIMIT_AS`
  would refuse.
- Time: the guest's epoch deadline is the call's deadline as the child sees
  it plus `PYTHON_LAG` (0.5 s), so the parent always reports the timeout and
  restarts the child; the epoch and then the child's own timer only back it up.
- Output and disk: while the guest runs, a watcher thread samples its output
  files and `disk_used()` and stops it through the epoch past
  `4 * max_output` bytes or the disk cap. The child's `RLIMIT_FSIZE` is
  `max_disk`, so no single file passes the cap (EFBIG).
- Symlinks: WASI lets the guest create a symlink in a writable mount, and
  one with `../` can point out of it. It stays on the host: the resolver
  refuses it inside the sandbox, but another program on the host could
  follow it. Treat writable mounts as untrusted input on the host side.
- Only the parent builds the cache (`ensure_python`); a child that finds it
  missing prints a message and exits 127. A writable mount may not hold or
  lie inside the cache, which holds native code.

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
  python/     # python on CPython for WASI; vendor/ holds PyYAML as released
  runtime/    # ShellState, CommandResult
  semantics/  # resolution, expansion, planner
  tools/      # agent tool registry
  vfs/        # in-memory virtual filesystem
```

## Spec and plan

The design spec (`2026-11-07-spelaion-design.html`) and its implementation plan
(`plans/2026-11-07-spelaion.html`) are kept with the maintainers' architecture
notes, outside this repo. Work follows the plan's tasks in order.
