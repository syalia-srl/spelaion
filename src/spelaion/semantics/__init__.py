"""Semantic analysis — command resolution and expansion planning."""

from spelaion.semantics.resolve import BUILTIN_NAMES, ResolvedCommand, resolve_command

__all__ = [
    "BUILTIN_NAMES",
    "ResolvedCommand",
    "resolve_command",
]
