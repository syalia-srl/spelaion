"""Cut long tool output down to its head and tail."""

from __future__ import annotations


def truncate(text: str, limit: int) -> str:
    """Keep about *limit* characters of *text*: its head and its tail.

    The cut falls on line boundaries where the kept halves contain one, and
    a notice in their place says how many lines went.
    """
    if len(text) <= limit:
        return text
    half = limit // 2
    head = text[:half]
    if "\n" in head:
        head = head[: head.rindex("\n") + 1]
    tail = text[len(text) - half :]
    if "\n" in tail[:-1]:
        tail = tail[tail.index("\n") + 1 :]
    cut = text[len(head) : len(text) - len(tail)]
    n = len(cut.splitlines())
    sep = "" if not head or head.endswith("\n") else "\n"
    return f"{head}{sep}[… {n} lines cut; narrow with grep or head]\n{tail}"
