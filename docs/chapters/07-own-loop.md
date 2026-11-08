# Your own agent loop

Your product already has a model client: it sends the conversation and a list
of tools, the model answers with a tool call, and the product runs the call and
sends the result back. spelaion can run those calls over the folders you mount,
but only if its three tools arrive in the shape the API expects. This chapter
turns `sb.tools()` into that shape and runs the loop against a scripted stand-in
for the model, so nothing here needs a network or an API key.

## The tools a model reads

Start with a folder, a sandbox, and one image, which a later call shows:

```{python export=examples/own_loop.py}
import base64
import json
import tempfile
from pathlib import Path

from spelaion import HostContext, Limits, Mount, Result, Sandbox

project = Path(tempfile.mkdtemp())
(project / "notes.md").write_text("# Notes\n\n- buy paint\n- call the plumber\n")
dot = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "2mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
(project / "dot.png").write_bytes(dot)
sb = Sandbox([Mount("/work", host=project)], cwd="/work", limits=Limits(timeout_s=20))
```

`Sandbox.tools()` returns three `Tool` objects, in the order `bash`, `edit`,
`write`. A `Tool` holds the name, the description the model reads, an
`input_schema` in JSON Schema, and `fn`, the callable that runs it. The
callable takes the schema's properties as keyword arguments, so a model's
`{"command": "ls"}` becomes `fn(command="ls")`:

```{python continue export=examples/own_loop.py}
by_name = {tool.name: tool for tool in sb.tools()}
print([tool.name for tool in sb.tools()])
print(type(by_name["bash"]).__name__)
```

In all three schemas every argument is a string, every property is required,
and no other property is allowed:

```{python continue export=examples/own_loop.py}
print(json.dumps(by_name["bash"].input_schema, indent=2))
```

That schema is what a tool-use API forwards to the model. Nothing in it names
a provider yet.

## What a call hands back

`fn` returns a `ToolOutput` with two fields, `text` and `images`. For `bash`,
`edit` and `write`, `text` is the result formatted for a model: stdout first,
then a `[stderr]` block when the call wrote to stderr, then `[exit code N]`
when it did not exit 0. A call that printed nothing, failed nothing and showed
no image reads `(no output)`. When stdout does not end in a newline, one is
added before the next block, so a marker always starts its own line:

```{python continue export=examples/own_loop.py}
for command in [
    "echo hello",
    "echo out; echo err >&2",
    "echo out; echo err >&2; exit 3",
    "echo err >&2",
    "exit 3",
    "true",
    "printf x; printf y >&2; exit 2",
]:
    print(f"{command!r} -> {by_name['bash'].fn(command=command).text!r}")
```

The first line is plain stdout. The second adds stderr and leaves the exit code
out, because the command succeeded. The third has both markers. The fourth has
no stdout, and the fifth no output at all except the code. The sixth succeeded
with nothing to say. The last one shows the newline inserted after an
unterminated stdout.

That format is produced by `output()`, the small function in
`spelaion._tools` behind each tool's `fn`. It is not part of the exported API,
so call `fn` rather than reuse the formatter.

`images` is empty for those calls. A command that produces an image puts the
text in `text` and the picture in `images`, as `Attachment` objects with
`mime`, `data` and `name`:

```{python continue export=examples/own_loop.py}
out = by_name["bash"].fn(command="show dot.png")
print("text:", repr(out.text))
print("images:", [(image.mime, image.name, len(image.data)) for image in out.images])
```

`show` prints nothing, so the text is empty and the image carries the result.
An API call sends that image beside the text; [Images](06-images.md) covers
where the bytes come from.

## The description the model reads

The `bash` description is built for the sandbox, not copied from a constant.
Print it once:

```{python continue export=examples/own_loop.py}
print(by_name["bash"].description)


```

It states the folders and whether each is read-only or read-write, the working
directory, that each call starts a fresh shell, and what is absent: no network,
no pip, no background processes, and python only when the sandbox has it
([python](04-python.md)). It names the timeout from `Limits`, which is 20
seconds here, and the host commands registered when the tools were built.
Those are sandbox paths throughout; the host folder behind `/work` never
appears, so the model cannot learn the host layout from the description.

The timeout is a per-sandbox limit, and the description reports the number the
sandbox was built with, so changing `Limits` changes what the model is told.
[Bounding every call](03-limits.md) covers what happens when the deadline
passes.

## Commands registered later

The list of extra commands is read when `tools()` is called, not when the
sandbox starts. Register a host command after the first call and ask for the
tools again:

```{python continue export=examples/own_loop.py}
@sb.command
def word_count(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=f"{len(ctx.path(args[0]).read_text().split())}\n")


old_description = by_name["bash"].description
by_name = {tool.name: tool for tool in sb.tools()}
print("word-count in old:", "word-count" in old_description)
print("word-count in new:", "word-count" in by_name["bash"].description)
print(by_name["bash"].fn(command="word-count notes.md").text, end="")
```

The `Tool` you already held keeps the old description. In a product that
registers commands at startup or per request, build the list after the last
registration. [Host commands](05-host-commands.md) explains what a handler is
and why it runs on the host.

## The shape each API wants

The Messages API from Anthropic takes the name, the description and the
`input_schema` at the top level of each tool. An OpenAI-style chat completion
takes the same three fields nested under `"type": "function"`, with the schema
called `"parameters"`. Both are plain dictionaries, so no SDK and no network
call is involved in making them:

```{python continue export=examples/own_loop.py}
tools = list(by_name.values())
anthropic_tools = [
    {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
    for tool in tools
]
openai_tools = [
    {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }
    for tool in tools
]
print([tool["name"] for tool in anthropic_tools])
print([tool["function"]["name"] for tool in openai_tools])
```

The first entry of each list shows the nesting:

```{python continue export=examples/own_loop.py}
print(json.dumps(anthropic_tools[0], indent=2))
print(json.dumps(openai_tools[0], indent=2))
```

The model, the headers, the retries and the streaming are the product's
business. spelaion supplies the three definitions and the functions behind
them. If the model is reached through a harness instead, `sb.serve_mcp()`
serves the same three tools over MCP; [MCP](08-mcp.md) takes that route.

## A loop with a stand-in for the model

A tool-use reply is a list of calls, each with an id, a name and arguments.
The list below is what a model might return over two turns: look at the
folder, count the words, then replace one line. It stands in for the API call.
In a real product each turn comes from the provider; the loop below sends
`messages` and `anthropic_tools` in a request, reads the `tool_use` blocks from
the response, and runs the same dispatch:

```{python continue export=examples/own_loop.py}
turns = [
    [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "bash",
            "input": {"command": "ls -1"},
        },
        {
            "type": "tool_use",
            "id": "call_2",
            "name": "bash",
            "input": {"command": "word-count notes.md"},
        },
    ],
    [
        {
            "type": "tool_use",
            "id": "call_3",
            "name": "edit",
            "input": {
                "path": "notes.md",
                "old": "- buy paint",
                "new": "- buy paint (white)",
            },
        },
    ],
]


```

Dispatch is a lookup by name and a call with the arguments as keywords. Each
result becomes a `tool_result` block whose `tool_use_id` matches the call, and
the blocks go back in a user message. Images join the text as image blocks in
the same result:

```{python continue export=examples/own_loop.py}
def image_block(image):
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": image.mime,
            "data": base64.b64encode(image.data).decode(),
        },
    }


def run_tools(calls):
    results = []
    for call in calls:
        tool = by_name[call["name"]]
        out = tool.fn(**call["input"])
        content = [{"type": "text", "text": out.text}] if out.text else []
        content += [image_block(image) for image in out.images]
        results.append(
            {"type": "tool_result", "tool_use_id": call["id"], "content": content}
        )
        print(f"{call['id']} {call['name']}: {out.text!r}")
    return {"role": "user", "content": results}


messages = [{"role": "user", "content": "Note that the paint is white."}]
for calls in turns:
    messages.append({"role": "assistant", "content": calls})
    messages.append(run_tools(calls))
    blocks = [block["type"] for block in messages[-1]["content"]]
    print("  ->", messages[-1]["role"], blocks)
messages.append({"role": "assistant", "content": [{"type": "text", "text": "Done."}]})
print("assistant:", messages[-1]["content"][0]["text"])
print(sb.bash("cat notes.md").stdout, end="")
sb.close()
```

The loop is the whole contract: the model names a tool, the product looks it
up in the list it sent, calls `fn` with the arguments, and returns the text and
images with the call's id. The `for calls in turns` line is where the request
to the provider goes; replace `turns` with the response and append the
assistant message before dispatching. An OpenAI-style loop keeps the same
lookup and call, and sends each result as a `role: tool` message with a
`tool_call_id` instead of a `tool_result` block.

## Where to go next

- [Mounts](02-mounts.md): read-only and writable folders, which the
  description reports.
- [Host commands](05-host-commands.md): the functions the agent calls as
  commands, and what they may reach.
- [MCP](08-mcp.md): serve these three tools to a harness instead of writing
  the loop.
