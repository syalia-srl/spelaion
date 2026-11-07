"""Virtual filesystem package."""

from spelaion.vfs.filesystem import VirtualFilesystem
from spelaion.vfs.nodes import DirNode, FileNode

__all__ = ["DirNode", "FileNode", "VirtualFilesystem"]
