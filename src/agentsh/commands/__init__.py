"""Busybox-style virtual commands — pure in-memory, all VFS."""

# Import all command modules to trigger @command registration.
# pyright: reportUnusedImport=false
from agentsh.commands import (  # noqa: F401
    archive,
    diff_cmd,
    encoding,
    fileio,
    fileops,
    math_cmd,
    modern_search,
    pathutil,
    search,
    stream,
    structured,
    sysinfo,
    sysutil,
    textproc,
    textproc2,
    trivial,
)
from agentsh.commands._registry import COMMANDS

__all__ = ["COMMANDS"]
