# ADR-0003: No Subprocess in Production -- Virtual Execution Only

## Status
Accepted

## Context
agentsh is designed as an execution engine for AI agents. Agents need predictable, inspectable, and safe command execution. Delegating to real process spawning introduces:
- Non-determinism from host environment differences.
- Security risks from arbitrary command execution.
- Opaque side effects that cannot be planned or rolled back.
- Dependency on specific binaries being installed on the host.

The core question: should agentsh execute commands by spawning real processes, or should it implement execution virtually?

## Decision
All production execution is virtual. No `subprocess` calls, no real process spawning, no `shell=True` anywhere in the execution path.

- **Builtins** (`echo`, `cd`, `export`, `test`, etc.) are implemented as Python functions operating on `ShellState` and `VirtualFilesystem`.
- **Pipelines** are simulated by chaining stdout/stdin between virtual command invocations.
- **Agent tools** are dispatched through a `ToolRegistry` protocol.
- **External binaries** are not supported in the default profile. The resolution order is: function, builtin, agent-tool. There is no fallback to the host PATH.

## Consequences

### Positive
- Fully deterministic: same input always produces same output regardless of host.
- Safe for agents: no accidental destructive commands or network access.
- Testable: every execution path can be unit-tested without mocking system calls.
- Inspectable: the planner can predict all effects before execution.
- Portable: no dependency on host OS, installed binaries, or filesystem layout.

### Negative
- Commands not implemented as builtins or registered as tools are unavailable.
- Some real-world scripts that depend on external binaries (e.g., `grep`, `sed`, `awk`) cannot run without registering them as agent tools.
- Performance characteristics differ from real process execution (no true parallelism in pipelines).
