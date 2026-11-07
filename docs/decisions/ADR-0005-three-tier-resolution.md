# ADR-0005: Three-Tier Command Resolution -- Function, Builtin, Agent-Tool Only

## Status
Accepted

## Context
Real Bash resolves commands in this order: aliases, functions, builtins, and then external binaries found via PATH. agentsh cannot safely support external binaries because virtual execution forbids subprocess calls (ADR-0003). We need a resolution strategy that is predictable, secure, and extensible.

## Decision
Command resolution follows a strict three-tier order:

1. **Shell functions** -- user-defined functions in the current shell state.
2. **Builtins** -- Python implementations of shell builtins (`echo`, `cd`, `export`, `test`, etc.).
3. **Agent tools** -- commands registered in the `ToolRegistry` by the embedding application.

There is no fourth tier. If a command is not found in any of these three tiers, execution fails with a clear "command not found" error. There is no fallback to the host PATH or any external binary execution.

This resolution order mirrors real Bash (minus aliases and external binaries) and ensures that:
- Functions can shadow builtins (matching Bash semantics).
- Builtins have known, tested behavior.
- Agent tools provide an explicit extension point for custom commands.

## Consequences

### Positive
- Security: no arbitrary binary execution. Every executable command is either defined in-session, implemented in Python, or explicitly registered.
- Predictability: the resolution order is simple and documented.
- Extensibility: new capabilities are added via `ToolRegistry` without modifying the executor.
- Testability: all tiers can be tested independently.

### Negative
- Common Unix commands (`grep`, `sed`, `awk`, `find`, `cat`) are not available unless registered as agent tools.
- Users must explicitly register any domain-specific tools they want the shell to invoke.
- Scripts written for real Bash will fail on unregistered external commands rather than degrading gracefully.
