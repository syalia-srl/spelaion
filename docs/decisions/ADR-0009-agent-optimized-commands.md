# ADR-0009: Agent-Optimized Virtual Commands -- rg, fd, jq, yq, patch

## Status
Accepted

## Context

AI coding agents (Claude Code, Codex CLI, Aider, SWE-agent, OpenHands) rely heavily on a small set of modern CLI tools that agentsh did not support. Research into agent tool-use patterns identified `rg` (ripgrep) as the #1 most-called tool, followed by `jq` for structured data processing and `patch` for diff-apply workflows.

The question was which tools to implement as virtual commands versus leaving as agent-tool delegates. The criteria: tools that operate purely on text/VFS data are feasible; tools requiring network, real processes, or language runtimes are not.

## Decision

Implement 15 new virtual commands in three categories:

**Search & structured data** (high-impact for agents):
- `rg` -- ripgrep-compatible recursive search with `--type`, `--glob`, context flags
- `fd` -- modern find with regex filename matching, `--type`, `--extension`, `--exec`
- `jq` -- JSON processor with recursive descent parser, 60+ builtins, pipe/filter/construct
- `yq` -- YAML/TOML/JSON processor reusing jq filter language
- `patch` -- unified diff applier with `-p` strip, `-R` reverse, fuzz matching

**Archive & encoding**:
- `zip` -- ZIP creation (complement to existing `unzip`)
- `sha1sum` -- SHA-1 hash (complement to existing md5sum/sha256sum)

**Utilities**:
- `file` -- file type detection by content magic bytes and extension
- `tac`, `column`, `fmt` -- text formatting
- `shuf`, `uuidgen` -- random data generation
- `envsubst` -- template variable substitution from shell state
- `install` -- copy with permissions

**Not implemented** (require real system access):
- `curl`/`wget` -- need network; better as agent-tool delegates
- `git` -- would need content-addressable store; massive scope
- `make` -- Makefile parsing nearly as complex as bash itself
- `python3`/`node` -- require real language runtimes

## Consequences

- Total command count: 166 (40 builtins + 126 virtual commands)
- `jq` implementation is ~2600 lines with its own recursive descent parser -- the largest single command. Pyright strict-mode diagnostics are suppressed for the evaluator module since JSON values are inherently `Any`-typed.
- `rg` and `fd` reuse the VFS walk/glob infrastructure rather than delegating to existing `grep`/`find` -- they have different default behaviors (recursive by default, skip hidden files, line numbers on).
- `yq` reuses the `jq` parser and evaluator, only changing the input parser (YAML/TOML via PyYAML/tomllib) and output serializer.
