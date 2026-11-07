"""Busybox-style virtual commands — pure in-memory, all VFS."""

# Import all command modules to trigger @command registration.
# pyright: reportUnusedImport=false
from spelaion.commands import (  # noqa: F401
    archive,
    diff_cmd,
    encoding,
    fileio,
    fileops,
    math_cmd,
    modern_search,
    pathutil,
    python_cmd,
    search,
    stream,
    structured,
    sysinfo,
    sysutil,
    textproc,
    textproc2,
    trivial,
)
from spelaion.commands._registry import COMMANDS

__all__ = ["COMMANDS"]
