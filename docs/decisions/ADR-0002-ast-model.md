# ADR-0002: Project-Owned AST Separate from CST

## Status
Accepted

## Context
tree-sitter produces a concrete syntax tree (CST) that includes every token, whitespace, and syntactic detail. Building execution logic, expansion, and planning directly on CST nodes would tightly couple the entire system to tree-sitter's node layout, naming conventions, and versioning.

We need a stable intermediate representation that:
- Exposes only semantically relevant structure.
- Can evolve independently of tree-sitter grammar updates.
- Supports typed traversal and pattern matching.
- Carries source spans for diagnostics.

## Decision
Define a project-owned AST as Python dataclasses in `agentsh.ast.nodes` and `agentsh.ast.words`. The normalization pass in `agentsh.parser.normalize` converts tree-sitter CST nodes into these typed AST nodes. No tree-sitter node objects are stored in or leak through the AST layer.

Key design choices:
- Every AST node carries a `SourceSpan` with byte offsets and row/column positions.
- `Word` nodes contain an ordered list of typed segments (literal, quoted, expansion, glob) rather than flat strings.
- Unsupported CST node types produce explicit diagnostics rather than silent fallbacks.

## Consequences

### Positive
- The AST is a stable API contract: downstream layers (expander, planner, executor) are insulated from parser changes.
- Typed nodes enable exhaustive pattern matching and static analysis.
- Source spans on every node allow precise error reporting.
- The word segment model preserves quoting context needed for correct expansion.

### Negative
- An additional normalization pass adds code and maintenance.
- New Bash syntax support requires changes in both the normalizer and the AST model.
- Some CST detail is intentionally discarded, so round-tripping back to exact source formatting is not supported.
