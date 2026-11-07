# Contributing to agentsh

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/mayflower/agentsh.git
cd agentsh
uv sync              # Install all dependencies
uv run pytest -q     # Verify everything works
```

## Quality Gates

All of these must pass before a PR can be merged:

```bash
uv run ruff check .              # Lint (B, C90, PL, SIM, RUF rules)
uv run ruff format --check .     # Formatting
uv run pyright                   # Type checking (strict mode)
uv run tach check                # Module boundary enforcement
uv run pytest tests/ -q          # 1500+ tests
```

Pre-commit hooks run these automatically on every commit:

```bash
uv run pre-commit install        # One-time setup
```

## Project Structure

```
src/agentsh/
  api/          # Public API (Bash class, ShellEngine)
  ast/          # AST node types (leaf module, no dependencies)
  cli/          # CLI entry point
  commands/     # 111 virtual commands (cat, grep, sed, awk, ...)
  exec/         # Execution engine (split evaluators)
  langchain_tools/  # LangChain tool wrappers
  parser/       # tree-sitter frontend + AST normalization
  policy/       # Allow/deny/warn policy engine
  runtime/      # ShellState, CommandResult, options
  semantics/    # Command resolution, expansion, planner
  tools/        # Agent tool registry
  vfs/          # In-memory virtual filesystem
```

Module boundaries are enforced by [tach](https://github.com/gauge-sh/tach). Run `uv run tach check` to verify, `uv run tach sync` to update after adding new inter-module imports.

## Adding a New Command

1. Find the right module in `src/agentsh/commands/` (or create a new one)
2. Use the `@command("name")` decorator
3. Follow the standard signature: `(args, state, vfs, io) -> CommandResult`
4. Add tests in `tests/commands/`
5. Run all quality gates

Example:

```python
from agentsh.commands._registry import command
from agentsh.runtime.result import CommandResult

@command("mycommand")
def cmd_mycommand(args, state, vfs, io):
    io.stdout.write("hello\n")
    return CommandResult(exit_code=0)
```

## Working Rules

1. **No subprocess** — never use `subprocess` or `shell=True` in production code
2. **All I/O through VFS** — no `os.*` file operations
3. **Type everything** — pyright strict mode, no `Any` without justification
4. **Test everything** — new features need tests, bug fixes need regression tests
5. **Keep boundaries** — don't add cross-module imports without updating `tach.toml`

## Pull Requests

- Keep PRs focused — one feature or fix per PR
- Include tests for new functionality
- Ensure all quality gates pass
- Use conventional commit messages: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`

## Reporting Issues

Use [GitHub Issues](https://github.com/mayflower/agentsh/issues). Please include:

- What you expected to happen
- What actually happened
- A minimal script that reproduces the issue
- Your Python version (`python --version`)
