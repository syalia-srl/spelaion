"""Virtual filesystem package."""

from agentsh.vfs.filesystem import VirtualFilesystem
from agentsh.vfs.nodes import DirNode, FileNode

__all__ = ["DirNode", "FileNode", "VirtualFilesystem"]
