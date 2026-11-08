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
by_name = {tool.name: tool for tool in sb.tools()}
print([tool.name for tool in sb.tools()])
print(type(by_name["bash"]).__name__)
print(json.dumps(by_name["bash"].input_schema, indent=2))
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
out = by_name["bash"].fn(command="show dot.png")
print("text:", repr(out.text))
print("images:", [(image.mime, image.name, len(image.data)) for image in out.images])
print(by_name["bash"].description)


@sb.command
def word_count(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=f"{len(ctx.path(args[0]).read_text().split())}\n")


old_description = by_name["bash"].description
by_name = {tool.name: tool for tool in sb.tools()}
print("word-count in old:", "word-count" in old_description)
print("word-count in new:", "word-count" in by_name["bash"].description)
print(by_name["bash"].fn(command="word-count notes.md").text, end="")
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
print(json.dumps(anthropic_tools[0], indent=2))
print(json.dumps(openai_tools[0], indent=2))
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
