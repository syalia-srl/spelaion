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
