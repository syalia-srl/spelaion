# ADR-0006: Subshells Get Copied State but Share VFS

## Status
Accepted

## Context
In real Bash, a subshell `( ... )` runs in a forked child process. The child inherits a copy of all shell state (variables, functions, options) but shares the same filesystem with the parent. Variable assignments in the subshell do not affect the parent, but file writes do.

agentsh has no processes to fork. We need to decide how subshell isolation works in a virtual environment.

Options considered:
1. **Full isolation**: Copy both ShellState and VFS. Subshell file writes are invisible to the parent.
2. **Shared VFS**: Copy ShellState but share the VFS instance. Subshell file writes are visible to the parent.
3. **No isolation**: Run subshells in the same context as the parent (incorrect).

## Decision
Subshells receive a **deep copy of ShellState** (variables, functions, cwd, options, positional params, last_status) but **share the same VirtualFilesystem** instance with the parent.

This matches real Bash behavior:
- `(export FOO=bar)` -- FOO is not set in the parent after the subshell exits.
- `(echo hello > /tmp/out)` -- `/tmp/out` exists and is visible to the parent after the subshell exits.
- `(cd /tmp; pwd)` -- parent's cwd is unchanged.

Groups `{ ...; }` run in the current shell context with no copying, also matching Bash.

## Consequences

### Positive
- Correct Bash semantics: subshells isolate variables but share the filesystem.
- Enables patterns like `(cd /tmp && generate_files)` where the parent sees generated files but retains its cwd.
- Simple to implement: copy state dict, keep VFS reference.

### Negative
- The shared VFS means subshell file mutations are not rollback-able.
- Deep copying ShellState on every subshell has a cost proportional to state size (acceptable for typical scripts).
- If future features need VFS isolation (e.g., speculative execution), a separate mechanism will be required.
