"""The three tools over MCP's streamable HTTP, served from a background thread."""

from __future__ import annotations

import base64
import hmac
import ipaddress
import itertools
import logging
import socket
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

import anyio.to_thread
import mcp_types as types
import uvicorn
from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server

from spelaion._tools import Tool, ToolOutput

# A started server answers at once; this only catches one that never does.
_START_TIMEOUT_S = 30

# Open streams get this long to finish when the server stops.
_GRACEFUL_S = 2

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# Threads of servers being stopped: uvicorn's log of the calls it cuts off
# there ("Cancel 1 running task(s)", a CancelledError traceback) is dropped.
_stopping: set[str] = set()


class _QuietWhileStopping(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.threadName not in _stopping


logging.getLogger("uvicorn.error").addFilter(_QuietWhileStopping())

# Numbers server threads apart: a port is reused once a server stops.
_serial = itertools.count(1)


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
        if token is None and not _is_loopback(host):
            raise ValueError(f"serving on {host}, beyond loopback, needs a token")
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
            # The product's own uvicorn loggers keep its handlers and levels;
            # a line per request would flood them.
            log_config=None,
            access_log=False,
            timeout_graceful_shutdown=_GRACEFUL_S,
        )
        self._server = uvicorn.Server(config)
        self._socket = sock
        self._stopped = False
        self._stop_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._server.run,
            kwargs={"sockets": [sock]},
            name=f"spelaion-mcp-{bound}-{next(_serial)}",
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
        """Shut the server down and free its port; later calls do nothing.

        Calls still running after a grace of 2 s are cut off: their
        clients get an error, while the sandbox finishes the command.
        """
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
            _stopping.add(self._thread.name)
            try:
                self._server.should_exit = True
                self._thread.join()
            finally:
                _stopping.discard(self._thread.name)
            self._socket.close()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


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
