"""The three tools over MCP's streamable HTTP, served from a background thread."""

from __future__ import annotations

import base64
import hmac
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

import anyio.to_thread
import mcp_types as types
import uvicorn
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from starlette.types import ASGIApp, Receive, Scope, Send

from spelaion._tools import Tool, ToolOutput

# A started server answers at once; this only catches one that never does.
_START_TIMEOUT_S = 30

# Open streams get this long to finish when the server stops.
_GRACEFUL_S = 2


class McpServer:
    """An MCP server for one sandbox, on its own thread, until :meth:`stop`.

    Closing the sandbox does not stop it: its tool calls then return the
    error "the sandbox is closed". Stop it yourself.
    """

    url: str  # http://HOST:PORT/mcp

    def __init__(
        self,
        tools: Callable[[], list[Tool]],
        host: str,
        port: int,
        token: str | None,
    ) -> None:
        family, _, _, _, address = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )[0]
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(address)
        except OSError:
            sock.close()
            raise
        bound = sock.getsockname()[1]
        shown = f"[{host}]" if ":" in host else host
        self.url = f"http://{shown}:{bound}/mcp"
        app: ASGIApp = _app(tools).streamable_http_app(host=host)
        if token is not None:
            app = _BearerToken(app, token)
        config = uvicorn.Config(
            app,
            log_level="warning",
            timeout_graceful_shutdown=_GRACEFUL_S,
        )
        self._server = uvicorn.Server(config)
        self._socket = sock
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [sock]},
            name=f"spelaion-mcp-{bound}",
            daemon=True,
        )
        self._thread.start()
        deadline = time.monotonic() + _START_TIMEOUT_S
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("the MCP server did not start")
            time.sleep(0.01)

    def stop(self) -> None:
        """Shut the server down and free its port; later calls do nothing."""
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
            self._server.should_exit = True
            self._thread.join()
            self._socket.close()


def _app(tools: Callable[[], list[Tool]]) -> Server[Any]:
    async def list_tools(
        ctx: ServerRequestContext[Any, Any], params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=t.name, description=t.description, input_schema=t.input_schema
                )
                for t in tools()
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext[Any, Any], params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        tool = next((t for t in tools() if t.name == params.name), None)
        if tool is None:
            return _error(f"unknown tool {params.name}")
        args = params.arguments or {}
        fields = list(tool.input_schema["properties"])
        if set(args) != set(fields) or not all(
            isinstance(v, str) for v in args.values()
        ):
            return _error(f"{tool.name} takes {', '.join(fields)}, each a string")
        try:
            # The sandbox's lock makes a second call wait for the first.
            out = await anyio.to_thread.run_sync(lambda: tool.fn(**args))
        except RuntimeError as e:
            return _error(str(e))
        return _result(out)

    return Server("spelaion", on_list_tools=list_tools, on_call_tool=call_tool)


def _result(out: ToolOutput) -> types.CallToolResult:
    content: list[types.ContentBlock] = [types.TextContent(type="text", text=out.text)]
    content += [
        types.ImageContent(
            type="image", data=base64.b64encode(a.data).decode(), mime_type=a.mime
        )
        for a in out.images
    ]
    return types.CallToolResult(content=content)


def _error(text: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], is_error=True
    )


class _BearerToken:
    """Refuses with 401 every HTTP request without ``Authorization: Bearer <token>``."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            given = [v for k, v in scope["headers"] if k.lower() == b"authorization"]
            if len(given) != 1 or not hmac.compare_digest(given[0], self._expected):
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"text/plain"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": b"unauthorized\n"})
                return
        await self._app(scope, receive, send)
