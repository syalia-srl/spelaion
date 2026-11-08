# Serving the tools over MCP

Your product has built a sandbox and registered its host commands in it, but
the agent runs in a harness: a program such as Claude Code or OpenCode that
speaks MCP and cannot import your Python. The three tools must still act on
the same sandbox, with the same mounts and the same host commands, so the
product serves them from its own process. This chapter starts that server,
calls it from Python, guards it with a token, and stops it.

## A server beside the sandbox

`serve_mcp(host="127.0.0.1", port=0, token=None)` starts an MCP server on a
background thread of the process that holds the sandbox. It listens on
`127.0.0.1` at a free port unless you pass a host or a port, and returns an
`McpServer` with what the product needs: the endpoint's `url`, and `stop` to
shut it down. The tools it answers are the ones the sandbox builds for each
request, so a host command registered later appears in `bash`'s description
without restarting anything.

```{python export=examples/mcp_server.py}
import asyncio
import json
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from mcp import ClientSession, types
from mcp.client.streamable_http import streamable_http_client

from spelaion import HostContext, Mount, Result, Sandbox

project = Path(tempfile.mkdtemp())
(project / "notes.md").write_text("# Notes\n")

sb = Sandbox([Mount("/work", project)], cwd="/work")
server = sb.serve_mcp()
print(server.url)


```

The URL is the whole configuration a harness needs: streamable HTTP at `/mcp`
on the port the operating system found free. Pass `port=` when a harness
configuration must name a fixed one.

## Calling it from Python

The `mcp` package ships a client. `streamable_http_client` opens the transport
to a URL, and `ClientSession` speaks the protocol over it: `initialize` first,
then `list_tools` and `call_tool`.

```{python continue export=examples/mcp_server.py}
async def listed() -> list[types.Tool]:
    async with (
        streamable_http_client(server.url) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return (await session.list_tools()).tools


async def call_bash(command: str) -> types.CallToolResult:
    async with (
        streamable_http_client(server.url) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        return await session.call_tool("bash", {"command": command})


tools = asyncio.run(listed())
print("greet named before it exists:", "greet" in tools[0].description)


@sb.command
def greet(ctx: HostContext, args: list[str]) -> Result:
    return Result(stdout=f"hello, {', '.join(args) or 'world'}\n")


tools = asyncio.run(listed())
print("greet named after it exists:", "greet" in tools[0].description)
print([tool.name for tool in tools])
result = asyncio.run(call_bash("greet ana && cat notes.md"))
print(result.content[0].text, end="")
```

The two listings differ although the server never restarted: `tools/list` runs
the sandbox's tool builder when the request arrives, and `bash`'s description
names the host commands registered at that moment. The call to `greet` then
runs the function in the product's process, exactly as `sb.bash` would have,
and its output arrives as one text block.

## One call at a time

Calls can arrive together. A harness may issue several tool calls in one turn,
and two harnesses may share one URL. The server accepts them all and runs them
one after another, because every tool call goes through the sandbox's lock.

```{python continue export=examples/mcp_server.py}
started = threading.Event()
release = threading.Event()
returned: list[str] = []


@sb.command
def hold(ctx: HostContext, args: list[str]) -> Result:
    started.set()
    release.wait(30)
    return Result(stdout="held\n")


async def call_and_record(session: ClientSession, command: str) -> None:
    result = await session.call_tool("bash", {"command": command})
    returned.append(result.content[0].text.strip())


async def two_at_once() -> None:
    async with (
        streamable_http_client(server.url) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        first = asyncio.create_task(call_and_record(session, "hold"))
        await asyncio.to_thread(started.wait, 10)
        second = asyncio.create_task(call_and_record(session, "echo second"))
        await asyncio.sleep(0.5)
        print("second done while the first is held:", second.done())
        release.set()
        await asyncio.gather(first, second)


asyncio.run(two_at_once())
print("returned in order:", returned)
```

The second call was already at the server while the first held `hold`, and it
could not finish: its tool call was waiting for the lock. The results came back
in the order the calls started. Files are shared between calls, so this order
is what keeps two commands from interleaving their writes.

## A token for anything beyond loopback

Loopback is safe by default: only a process on the same machine can reach
`127.0.0.1`. A server in a container, or one a harness on another machine
reaches, listens on an address other processes can reach, so a token is
required there. `localhost`, any address in `127.0.0.0/8` and `::1` count as
loopback. `serve_mcp` refuses anything else without a token, before it binds a
socket. With a token, every HTTP request must carry
`Authorization: Bearer <token>`; a request without it, with the wrong token, or
with another scheme gets 401 before the MCP layer sees it.

```{python continue export=examples/mcp_server.py}
try:
    sb.serve_mcp(host="0.0.0.0")
except ValueError as error:
    print(error)


def status(url: str, headers: dict[str, str]) -> int:
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **headers,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


token = "s3cret"
guarded = sb.serve_mcp(token=token)
print("no header:", status(guarded.url, {}))
print("wrong token:", status(guarded.url, {"Authorization": "Bearer nope"}))
print("right token:", status(guarded.url, {"Authorization": f"Bearer {token}"}))
guarded.stop()
```

Those three requests are one `initialize` message sent with urllib. The last one
reached the MCP endpoint and was answered; the first two were refused at the
door. A client on a guarded server puts the header on the HTTP client it gives
`streamable_http_client`, and every request it makes then carries it.

## Closing the sandbox and stopping the server

`Sandbox.close()` stops the shell's child process. It does not touch the
server: the server thread belongs to the product, and its listing still comes
from the mounts and handlers, so `tools/list` keeps answering. A call that
needs the child then fails inside the sandbox with `the sandbox is closed`,
which the server returns as a tool error: `is_error` is true and the message is
the text. The harness sees a failed call, not a dropped connection.

```{python continue export=examples/mcp_server.py}
sb.close()

tools = asyncio.run(listed())
print("tools after close:", [tool.name for tool in tools])
result = asyncio.run(call_bash("echo still there"))
print(result.content[0].text, "isError:", result.is_error)

port = int(server.url.rsplit(":", 1)[1].split("/")[0])
server.stop()
try:
    socket.create_connection(("127.0.0.1", port), timeout=2).close()
except ConnectionRefusedError:
    print("the port is closed")
else:
    print("still listening")
```

`stop` sets the server's exit flag, joins its thread and closes the socket, so
the port is free when it returns and a second call to `stop` does nothing. A
call still running after a grace of 2 s is cut off: its client gets an error
while the sandbox finishes the command. Nothing else in this program needs the
server, so it stops last.

For a server you keep running, `examples/serve.py` at the repo root does the
same without the client: it prints the URL and a random token, then waits until
Ctrl-C.

## Where to go next

- [Host commands](05-host-commands.md): what a served sandbox exposes through
  `bash`, and how a handler gets its arguments and result.
- [Harnesses](09-harnesses.md): pointing Claude Code or OpenCode at this URL
  with these three tools and no others.
- [Bounding every call](03-limits.md): the timeout, output and disk limits that
  apply to calls arriving over MCP, because they go through the same sandbox.
