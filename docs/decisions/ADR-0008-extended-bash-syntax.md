# ADR-0008: Extended Bash Syntax -- Arrays, Extended Tests, C-Style For, Here-Docs

## Status
Accepted

## Context

The initial release supported basic bash syntax (variables, quoting, simple expansion, if/while/for/case, functions, pipelines, redirections). Real-world agent scripts required additional syntax features that tree-sitter already parses correctly but the normalizer and executor did not handle.

Analysis of 20 production-style bash scripts (log analyzers, config templaters, build tools, linters, migration planners) identified the critical gaps.

## Decision

Implement six syntax extensions in the normalizer and executor layers:

1. **Parameter expansion operators**: `${#x}` (length), `${x:0:3}` (substring), `${x/p/r}` (replace), `${x^^}`/`${x,,}` (case conversion)
2. **Here-documents and here-strings**: `<<EOF` with variable expansion, `<<'EOF'` without, `<<-EOF` (tab strip), `<<<word`
3. **C-style for loops**: `for (( init; cond; update ))` with full arithmetic statements
4. **Arrays**: indexed `arr=(a b c)` and associative `declare -A`, `${arr[idx]}`, `${arr[@]}`, `${#arr[@]}`, `${!arr[@]}`
5. **Extended test**: `[[ expr ]]` with glob `==`, regex `=~` (setting BASH_REMATCH), `&&`/`||` inside brackets
6. **Process substitution**: `<(cmd)` and `>(cmd)` via temporary VFS files

Additionally: `break`/`continue` as signal-based flow control, `echo -e` escape interpretation, `read -ra` with IFS splitting, `printf` format strings with width/alignment, `RedirectedCommand` node for compound commands with redirections.

## Consequences

- The AST gained 4 new node types: `ExtendedTest`, `CStyleForLoop`, `ArrayAssignmentWord`, `RedirectedCommand`, and 1 new word segment: `ProcessSubstitutionSegment`
- `ShellState.Scope` gained `array_bindings` (indexed) and `assoc_bindings` (associative) alongside scalar `bindings`
- `ArithEvaluator` gained `eval_statement()` for assignments/increments and comparison/logical/ternary operators
- `BoolEvaluator` gained `eval_extended_test()` with recursive-descent parsing for `&&`/`||`/`!`/`()`
- 20 real-world scripts serve as integration regression tests
- The normalizer grew but was subsequently simplified (-135 lines via extracted helpers)
