# CLAUDE.md

## Project Goal
This repository implements `agentsh`: a Python library and CLI for a virtual Bash-syntax parser
and policy-governed agent executor. 100% virtual — no subprocess, no os.* file I/O in production paths.

## Architecture
- **Parser frontend**: tree-sitter + tree-sitter-bash
- **AST**: Project-owned normalized nodes (not tree-sitter nodes)
- **Word model**: Structured segments (literal, single-quoted, double-quoted, param expansion, command sub, arithmetic, glob)
- **VFS**: In-memory virtual filesystem, all file I/O goes through VFS
- **Runtime**: ShellState with variables, cwd, functions, positional params
- **Expansion**: tilde → parameter → command substitution → quote removal → word splitting → globbing
- **Execution**: Three-tier resolution: function → builtin → agent-tool (no external binaries)
- **Policy**: Allow/deny/warn rules for commands, paths, tools
- **LangChain tools**: parse/plan/run exposed as BaseTool/StructuredTool

## Working Rules
1. Never use `subprocess` or `shell=True` in production code
2. All filesystem access goes through VirtualFilesystem
3. Command resolution: function → builtin → agent-tool only
4. Keep parser, AST, semantics, and executor as separate layers
5. Unsupported syntax → explicit diagnostics, never silent fallbacks
6. Type annotations everywhere; all quality gates must pass

## Toolchain
All tools are Rust-based for speed. Managed by **uv**.

| Tool | Role | Config |
|------|------|--------|
| **uv** | Package management, venvs, lockfile | `pyproject.toml` |
| **Ruff** | Linter + formatter (replaces flake8/pylint/black/isort) | `pyproject.toml [tool.ruff]` |
| **Pyright** | Type checker, strict mode (replaces mypy) | `pyproject.toml [tool.pyright]` |
| **Tach** | Module boundary enforcement | `tach.toml` |
| **pre-commit** | Git hooks running all tools | `.pre-commit-config.yaml` |

## Quality Gates
All must pass before commit (enforced by pre-commit hooks):
```bash
uv run ruff check .                     # Lint (B, C90, PL, SIM, RUF rules)
uv run ruff format --check .            # Formatting
uv run pyright                          # Type check (strict mode)
uv run tach check                       # Module boundaries
uv run pytest tests/ -q                 # 1005+ tests
```

## Commands
```bash
uv sync                                 # Install/update all deps
uv run pytest tests/ -q                 # Run tests
uv run ruff check .                     # Lint
uv run ruff format .                    # Format
uv run pyright                          # Type check
uv run tach check                       # Architecture boundaries
uv run tach sync                        # Sync tach config with actual imports
uv run pre-commit run --all-files       # Run all hooks
uv run agentsh parse <file>             # Parse script
uv run agentsh plan <file>              # Dry-run plan
uv run agentsh run <file>               # Execute script
```
