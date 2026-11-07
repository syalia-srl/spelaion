"""Semantic analysis — command resolution and expansion planning."""

from agentsh.semantics.resolve import BUILTIN_NAMES, ResolvedCommand, resolve_command

__all__ = [
    "BUILTIN_NAMES",
    "ResolvedCommand",
    "resolve_command",
]
