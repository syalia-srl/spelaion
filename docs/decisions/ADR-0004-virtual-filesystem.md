# ADR-0004: In-Memory Virtual Filesystem as Single Source of Truth

## Status
Accepted

## Context
Shell scripts read and write files constantly. If agentsh accessed the real host filesystem, it would:
- Create side effects that are hard to predict, test, and undo.
- Require sandboxing at the OS level to prevent damage.
- Couple execution results to the host's filesystem state.
- Make the planner's job impossible (can't predict effects on unknown files).

We need a filesystem abstraction that is fully controlled, pre-seedable, and inspectable.

## Decision
Implement `VirtualFilesystem` as a pure in-memory tree of `DirNode` and `FileNode` objects. All file operations in the executor (redirections, `cat`, `source`, etc.) target the VFS exclusively. No `os.open()`, `os.read()`, `os.write()`, `pathlib.Path.read_text()`, or any other real filesystem call is made during script execution.

Key properties:
- Pre-seedable via `initial_files` dict at engine construction.
- POSIX-like path semantics (absolute paths, `normpath`).
- Supports `read`, `write` (with append), `mkdir`, `exists`, `is_dir`, `is_file`, `listdir`, `unlink`, `rmdir`, and `glob`.
- Implicit `mkdir -p` on write for convenience.
- Inspectable after execution: tests and agents can examine the VFS state.

## Consequences

### Positive
- Zero host coupling: execution is fully isolated.
- Test-friendly: pre-seed input files, assert output files after execution.
- Agent-friendly: VFS state can be serialized, diffed, or presented to the agent.
- No cleanup needed: VFS is garbage-collected with the engine instance.

### Negative
- Large files are held entirely in memory (no streaming or mmap).
- No file permissions, ownership, or timestamps (simplified model).
- Scripts that depend on real filesystem state (e.g., reading `/etc/passwd`) need explicit VFS seeding.
