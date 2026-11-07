# ADR-0001: tree-sitter as Parser Frontend

## Status
Accepted

## Context
agentsh needs to parse a practical subset of Bash syntax reliably. Writing a custom recursive-descent parser for Bash is error-prone and expensive -- Bash grammar is large, context-sensitive, and full of edge cases. We need a parser that handles error recovery gracefully so agents can inspect partially valid scripts.

The main candidates were:
1. Custom recursive-descent parser in Python
2. `tree-sitter` + `tree-sitter-bash` (incremental, error-recovering, widely used)
3. `bashlex` (Python-native, limited maintenance)
4. Shelling out to `bash --dump-po-strings` or similar (host-dependent)

## Decision
Use `tree-sitter` with the `tree-sitter-bash` grammar as the parsing frontend. The tree-sitter CST is consumed only within the parser layer and is never exposed to downstream modules -- it is immediately normalized into a project-owned AST.

Reasons:
- **Mature grammar**: `tree-sitter-bash` covers a broad Bash syntax surface including quoting, heredocs, and compound commands.
- **Error recovery**: tree-sitter produces partial trees on syntax errors rather than aborting, which is essential for agent-facing diagnostics.
- **Performance**: Incremental parsing in C is fast enough for interactive and batch use.
- **Active maintenance**: tree-sitter and its Bash grammar have large communities and continuous updates.

## Consequences

### Positive
- Reliable parsing of a large Bash subset with minimal effort.
- Error recovery provides useful diagnostics even for malformed input.
- Decoupling via the normalized AST means the parser frontend can be swapped later without affecting the rest of the system.

### Negative
- tree-sitter produces a CST, not a semantic AST -- a normalization pass is required.
- The tree-sitter Python bindings introduce a native dependency (compiled C library).
- Some Bash constructs may be parsed syntactically but require semantic disambiguation that tree-sitter cannot provide (e.g., distinguishing assignment words from command arguments).
