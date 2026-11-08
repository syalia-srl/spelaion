"""Sandbox.serve_mcp(): the three tools over MCP's streamable HTTP."""

from __future__ import annotations

import asyncio
import base64
import shutil
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import mcp_types as types
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from spelaion import McpServer, Mount, Sandbox

PNG_FIXTURE = Path(__file__).parent / "sandbox" / "data" / "pixel.png"


@pytest.fixture
def rw(tmp_path: Path) -> Path:
    d = tmp_path / "rw"
    d.mkdir()
    return d


@pytest.fixture
def sb(rw: Path) -> Iterator[Sandbox]:
    with Sandbox([Mount("/scratch", rw)], cwd="/scratch") as s:
        yield s


@pytest.fixture
def server(sb: Sandbox) -> Iterator[McpServer]:
    srv = sb.serve_mcp()
    yield srv
    srv.stop()


def client(url: str, token: str | None = None) -> Client:
    headers = {"Authorization": f"Bearer {token}"} if token else None
    http = create_mcp_http_client(headers=headers)
    return Client(streamable_http_client(url, http_client=http))


async def list_names(url: str, token: str | None = None) -> list[str]:
    async with client(url, token) as c:
        return [t.name for t in (await c.list_tools()).tools]


async def call(
    url: str, name: str, args: dict[str, Any], token: str | None = None
) -> types.CallToolResult:
    async with client(url, token) as c:
        return await c.call_tool(name, args)


def status(url: str, headers: dict[str, str]) -> int:
    body = b'{"jsonrpc": "2.0", "id": 1, "method": "ping"}'
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
    except urllib.error.HTTPError as e:
        return e.code


def text(result: types.CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    return block.text


# --- From the brief ---------------------------------------------------------


def test_url_reports_the_port(server: McpServer) -> None:
    assert server.url.startswith("http://127.0.0.1:")
    assert server.url.endswith("/mcp")
    assert int(server.url.split(":")[2].split("/")[0]) > 0


def test_list_tools(server: McpServer) -> None:
    assert asyncio.run(list_names(server.url)) == ["bash", "edit", "write"]


def test_tools_carry_description_and_schema(sb: Sandbox, server: McpServer) -> None:
    async def listed() -> list[types.Tool]:
        async with client(server.url) as c:
            return (await c.list_tools()).tools

    for ours, theirs in zip(sb.tools(), asyncio.run(listed()), strict=True):
        assert theirs.description == ours.description
        assert theirs.input_schema == ours.input_schema


def test_call_bash(server: McpServer) -> None:
    result = asyncio.run(call(server.url, "bash", {"command": "echo hi"}))
    assert text(result) == "hi\n"
    assert len(result.content) == 1
    assert not result.is_error


def test_show_returns_an_image_block(server: McpServer, rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")
    result = asyncio.run(call(server.url, "bash", {"command": "echo look; show v.png"}))
    assert text(result) == "look\n"
    image = result.content[1]
    assert isinstance(image, types.ImageContent)
    assert image.mime_type == "image/png"
    assert base64.b64decode(image.data) == PNG_FIXTURE.read_bytes()


def test_two_calls_at_once(server: McpServer) -> None:
    async def both() -> tuple[types.CallToolResult, types.CallToolResult]:
        async with client(server.url) as c:
            return await asyncio.gather(
                c.call_tool("bash", {"command": "sleep 0.5; echo a"}),
                c.call_tool("bash", {"command": "echo b"}),
            )

    start = time.monotonic()
    a, b = asyncio.run(both())
    assert (text(a), text(b)) == ("a\n", "b\n")
    assert time.monotonic() - start >= 0.5


def test_two_clients_at_once(server: McpServer) -> None:
    async def both() -> list[types.CallToolResult]:
        return await asyncio.gather(
            call(server.url, "bash", {"command": "sleep 0.5; echo a"}),
            call(server.url, "bash", {"command": "echo b"}),
        )

    assert [text(r) for r in asyncio.run(both())] == ["a\n", "b\n"]


def test_edit_and_write(server: McpServer, rw: Path) -> None:
    async def run() -> list[types.CallToolResult]:
        async with client(server.url) as c:
            return [
                await c.call_tool("write", {"path": "a.txt", "content": "one\n"}),
                await c.call_tool("edit", {"path": "a.txt", "old": "one", "new": "1"}),
            ]

    asyncio.run(run())
    assert (rw / "a.txt").read_text() == "1\n"


def test_nonzero_exit_is_not_a_tool_error(server: McpServer) -> None:
    result = asyncio.run(call(server.url, "bash", {"command": "exit 3"}))
    assert text(result) == "[exit code 3]"
    assert not result.is_error


def test_unknown_tool_is_an_error(server: McpServer) -> None:
    result = asyncio.run(call(server.url, "rm", {}))
    assert result.is_error
    assert text(result) == "unknown tool rm"


@pytest.mark.parametrize(
    "args",
    [{}, {"command": 1}, {"command": "echo", "extra": "x"}],
)
def test_bad_arguments_are_an_error(server: McpServer, args: dict[str, Any]) -> None:
    result = asyncio.run(call(server.url, "bash", args))
    assert result.is_error
    assert text(result).startswith("bash takes ")


def test_closed_sandbox_is_an_error(sb: Sandbox, server: McpServer) -> None:
    sb.close()
    result = asyncio.run(call(server.url, "bash", {"command": "echo hi"}))
    assert result.is_error
    assert text(result) == "the sandbox is closed"


# --- Lifetime ---------------------------------------------------------------


def port_of(server: McpServer) -> int:
    return int(server.url.split(":")[2].split("/")[0])


def test_stop_frees_the_port_and_is_idempotent(sb: Sandbox) -> None:
    srv = sb.serve_mcp()
    port = port_of(srv)
    asyncio.run(list_names(srv.url))
    srv.stop()
    srv.stop()
    with socket.socket() as s, pytest.raises(ConnectionRefusedError):
        s.connect(("127.0.0.1", port))
    again = sb.serve_mcp(port=port)
    try:
        assert asyncio.run(list_names(again.url)) == ["bash", "edit", "write"]
    finally:
        again.stop()
    assert sb.bash("echo still").stdout == "still\n"


def test_given_port(sb: Sandbox) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = sb.serve_mcp(port=port)
    try:
        assert srv.url == f"http://127.0.0.1:{port}/mcp"
        assert asyncio.run(list_names(srv.url)) == ["bash", "edit", "write"]
    finally:
        srv.stop()


def test_port_in_use_raises(sb: Sandbox, server: McpServer) -> None:
    with pytest.raises(OSError):
        sb.serve_mcp(port=port_of(server))


def test_close_does_not_stop_the_server(rw: Path) -> None:
    sb = Sandbox([Mount("/scratch", rw)])
    srv = sb.serve_mcp()
    try:
        sb.close()
        assert asyncio.run(list_names(srv.url)) == ["bash", "edit", "write"]
    finally:
        srv.stop()


# --- Token (ruling 16) ------------------------------------------------------


@pytest.fixture
def guarded(sb: Sandbox) -> Iterator[McpServer]:
    srv = sb.serve_mcp(token="s3cret")
    yield srv
    srv.stop()


def test_no_header_is_401(guarded: McpServer) -> None:
    assert status(guarded.url, {}) == 401


def test_wrong_token_is_401(guarded: McpServer) -> None:
    assert status(guarded.url, {"Authorization": "Bearer nope"}) == 401
    assert status(guarded.url, {"Authorization": "Bearer s3cret2"}) == 401
    assert status(guarded.url, {"Authorization": "Bearer s3cre"}) == 401
    assert status(guarded.url, {"Authorization": "bearer s3cret"}) == 401
    assert status(guarded.url, {"Authorization": "s3cret"}) == 401


def test_any_path_is_401(guarded: McpServer) -> None:
    root = guarded.url.removesuffix("/mcp")
    assert status(root + "/other", {}) == 401


def test_right_token_works(guarded: McpServer) -> None:
    assert status(guarded.url, {"Authorization": "Bearer s3cret"}) != 401
    result = asyncio.run(call(guarded.url, "bash", {"command": "echo hi"}, "s3cret"))
    assert text(result) == "hi\n"


def test_client_with_wrong_token_fails(guarded: McpServer) -> None:
    with pytest.raises(ExceptionGroup):
        asyncio.run(list_names(guarded.url, "nope"))


def test_no_token_means_no_auth(server: McpServer) -> None:
    assert status(server.url, {}) != 401
