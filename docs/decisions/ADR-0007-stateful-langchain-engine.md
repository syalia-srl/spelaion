# ADR-0007: Single Stateful ShellEngine Shared Across LangChain Tools

## Status
Accepted

## Context
agentsh provides three LangChain tools: `parse`, `plan`, and `run`. When an LLM agent uses these tools in a conversation, it typically builds up state incrementally -- setting variables, creating files, defining functions -- across multiple tool calls.

If each tool call created a fresh engine, all state would be lost between calls, making multi-step shell workflows impossible. Conversely, if tools were fully independent, the agent would need to replay all setup commands on every invocation.

## Decision
The `create_agentsh_tools()` factory creates a single `ShellEngine` instance and passes it to all three tools. Variables, VFS contents, function definitions, cwd, and exit status persist across tool calls within the same engine.

```python
parse_tool, plan_tool, run_tool = create_agentsh_tools(
    initial_files={"/config.sh": "export DB=prod"},
    initial_vars={"USER": "agent"},
)
# run_tool.invoke("source /config.sh")  -- sets DB=prod
# run_tool.invoke("echo $DB")           -- prints "prod"
```

The engine is constructed once per agent session (or per conversation thread). The embedding application controls engine lifetime and initial state.

## Consequences

### Positive
- Natural multi-step workflows: an agent can `export`, `cd`, `source`, and `echo` across calls and see accumulated state.
- The VFS grows incrementally: files written in one call are readable in the next.
- Plan mode sees the actual current state, making its predictions accurate for the current context.

### Negative
- State is mutable and shared: a bad `run` call can corrupt state for subsequent calls. There is no built-in undo.
- The engine is not thread-safe. Concurrent tool calls from the same agent would need external synchronization.
- Engine lifetime management is the embedding application's responsibility. Long-lived engines accumulate state that may become stale.
