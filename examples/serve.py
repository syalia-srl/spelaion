"""Serve a sandbox over MCP until Ctrl-C.

    uv run python examples/serve.py

It prints the server's URL and its bearer token, one per line. The sandbox
sees one folder, /scratch, a temporary folder deleted on exit, and one host
command, ``greet``.
"""

from __future__ import annotations

import secrets
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress

from spelaion import HostContext, Mount, Result, Sandbox


@contextmanager
def serving() -> Iterator[tuple[str, str]]:
    """A served sandbox, as its URL and token; stopped and closed on exit."""
    with (
        tempfile.TemporaryDirectory() as scratch,
        Sandbox([Mount("/scratch", scratch)], cwd="/scratch") as sb,
    ):

        @sb.command
        def greet(ctx: HostContext, args: list[str]) -> Result:  # pyright: ignore[reportUnusedFunction]
            return Result(stdout=f"hello, {' '.join(args) or 'world'}\n")

        token = secrets.token_urlsafe(32)
        server = sb.serve_mcp(token=token)
        try:
            yield server.url, token
        finally:
            server.stop()


def main() -> None:
    with serving() as (url, token):
        print(url)
        print(token, flush=True)
        with suppress(KeyboardInterrupt):
            threading.Event().wait()


if __name__ == "__main__":
    main()
