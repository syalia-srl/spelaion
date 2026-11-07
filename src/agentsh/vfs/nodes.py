"""VFS node types for the virtual filesystem."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileNode:
    """A virtual file containing byte content."""

    content: bytes = b""
    executable: bool = False
    mode: int = 0o644
    uid: int = 0
    gid: int = 0


@dataclass
class DirNode:
    """A virtual directory containing named children."""

    children: dict[str, FileNode | DirNode] = field(default_factory=lambda: {})
    mode: int = 0o755
    uid: int = 0
    gid: int = 0
