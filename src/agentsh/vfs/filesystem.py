"""Virtual filesystem — pure in-memory, no real I/O."""

from __future__ import annotations

import fnmatch
import posixpath
from collections.abc import Iterator

from agentsh.vfs.nodes import DirNode, FileNode


class VirtualFilesystem:
    """A fully in-memory POSIX-like filesystem.

    All paths are stored and manipulated as absolute POSIX paths.
    No real ``os.*`` or ``subprocess`` calls are ever made.
    """

    def __init__(self, initial_files: dict[str, str | bytes] | None = None) -> None:
        self.root = DirNode()
        if initial_files:
            for path, raw_content in initial_files.items():
                data = (
                    raw_content.encode()
                    if isinstance(raw_content, str)
                    else raw_content
                )
                self.write(path, data)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def resolve(self, path: str, cwd: str) -> str:
        """Resolve *path* against *cwd*, returning a normalised absolute path."""
        if not path.startswith("/"):
            path = cwd.rstrip("/") + "/" + path
        return posixpath.normpath(path)

    @staticmethod
    def _split(path: str) -> list[str]:
        """Split an absolute path into component names (excluding root)."""
        # posixpath.normpath guarantees no trailing/double slashes
        parts = path.strip("/").split("/")
        return [p for p in parts if p]

    # ------------------------------------------------------------------
    # Internal node access
    # ------------------------------------------------------------------

    def get_node(self, path: str) -> FileNode | DirNode | None:
        """Walk the tree to find the node at *path*, or return ``None``."""
        path = posixpath.normpath(path)
        if path == "/":
            return self.root
        node: FileNode | DirNode = self.root
        for part in self._split(path):
            if not isinstance(node, DirNode):
                return None
            child = node.children.get(part)
            if child is None:
                return None
            node = child
        return node

    def _get_parent(self, path: str) -> tuple[DirNode, str]:
        """Return ``(parent_dir_node, basename)`` for *path*.

        Raises ``FileNotFoundError`` if any intermediate directory is
        missing or is not a directory.
        """
        path = posixpath.normpath(path)
        parts = self._split(path)
        if not parts:
            raise FileNotFoundError("Cannot get parent of root")
        basename = parts[-1]
        node: FileNode | DirNode = self.root
        for part in parts[:-1]:
            if not isinstance(node, DirNode):
                raise FileNotFoundError(f"Not a directory in path: {part!r}")
            child = node.children.get(part)
            if child is None:
                raise FileNotFoundError(f"No such file or directory: {part!r}")
            node = child
        if not isinstance(node, DirNode):
            raise FileNotFoundError(f"Not a directory: {parts[-2]!r}")
        return node, basename

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self, path: str) -> bytes:
        """Return the content of the file at *path*.

        Raises ``FileNotFoundError`` if *path* does not exist, and
        ``IsADirectoryError`` if it is a directory.
        """
        node = self.get_node(path)
        if node is None:
            raise FileNotFoundError(f"No such file or directory: {path!r}")
        if isinstance(node, DirNode):
            raise IsADirectoryError(f"Is a directory: {path!r}")
        return node.content

    def write(self, path: str, data: bytes, append: bool = False) -> None:
        """Write *data* to the file at *path*.

        Parent directories are created automatically (like ``mkdir -p``).
        If the file already exists and *append* is ``True``, data is
        appended; otherwise the file is overwritten.
        """
        path = posixpath.normpath(path)
        parts = self._split(path)
        if not parts:
            raise IsADirectoryError("Cannot write to root directory")

        # Ensure all parent directories exist.
        node: DirNode = self.root
        for part in parts[:-1]:
            child = node.children.get(part)
            if child is None:
                child = DirNode()
                node.children[part] = child
            elif not isinstance(child, DirNode):
                raise NotADirectoryError(f"Not a directory: {part!r}")
            node = child

        basename = parts[-1]
        existing = node.children.get(basename)
        if isinstance(existing, DirNode):
            raise IsADirectoryError(f"Is a directory: {path!r}")

        if existing is not None and append:
            assert isinstance(existing, FileNode)
            existing.content += data
        elif existing is not None:
            existing.content = data
        else:
            node.children[basename] = FileNode(content=data)

    def exists(self, path: str) -> bool:
        """Return ``True`` if a node exists at *path*."""
        return self.get_node(path) is not None

    def is_dir(self, path: str) -> bool:
        """Return ``True`` if *path* exists and is a directory."""
        return isinstance(self.get_node(path), DirNode)

    def is_file(self, path: str) -> bool:
        """Return ``True`` if *path* exists and is a regular file."""
        return isinstance(self.get_node(path), FileNode)

    def mkdir(self, path: str, parents: bool = False) -> None:
        """Create a directory at *path*.

        If *parents* is ``True``, create intermediate directories as
        needed (like ``mkdir -p``).  Raises ``FileExistsError`` if the
        target already exists.
        """
        path = posixpath.normpath(path)
        parts = self._split(path)
        if not parts:
            raise FileExistsError("Root directory already exists")

        node: DirNode = self.root
        for i, part in enumerate(parts):
            child = node.children.get(part)
            is_last = i == len(parts) - 1

            if child is None:
                if is_last or parents:
                    new_dir = DirNode()
                    node.children[part] = new_dir
                    node = new_dir
                else:
                    raise FileNotFoundError(
                        f"No such file or directory: {'/' + '/'.join(parts[: i + 1])!r}"
                    )
            elif isinstance(child, DirNode):
                if is_last:
                    raise FileExistsError(f"Directory exists: {path!r}")
                node = child
            else:
                # It's a file — can't traverse through it.
                raise NotADirectoryError(
                    f"Not a directory: {'/' + '/'.join(parts[: i + 1])!r}"
                )

    def listdir(self, path: str) -> list[str]:
        """Return a sorted list of names in the directory at *path*."""
        node = self.get_node(path)
        if node is None:
            raise FileNotFoundError(f"No such file or directory: {path!r}")
        if not isinstance(node, DirNode):
            raise NotADirectoryError(f"Not a directory: {path!r}")
        return sorted(node.children.keys())

    def unlink(self, path: str) -> None:
        """Remove the file at *path*.

        Raises ``FileNotFoundError`` if *path* does not exist and
        ``IsADirectoryError`` if it is a directory.
        """
        parent, basename = self._get_parent(path)
        child = parent.children.get(basename)
        if child is None:
            raise FileNotFoundError(f"No such file or directory: {path!r}")
        if isinstance(child, DirNode):
            raise IsADirectoryError(f"Is a directory: {path!r}")
        del parent.children[basename]

    def rmdir(self, path: str) -> None:
        """Remove the empty directory at *path*.

        Raises ``FileNotFoundError`` if *path* does not exist,
        ``NotADirectoryError`` if it is not a directory, and
        ``OSError`` if the directory is not empty.
        """
        path = posixpath.normpath(path)
        if path == "/":
            raise OSError("Cannot remove root directory")
        parent, basename = self._get_parent(path)
        child = parent.children.get(basename)
        if child is None:
            raise FileNotFoundError(f"No such file or directory: {path!r}")
        if not isinstance(child, DirNode):
            raise NotADirectoryError(f"Not a directory: {path!r}")
        if child.children:
            raise OSError(f"Directory not empty: {path!r}")
        del parent.children[basename]

    # ------------------------------------------------------------------
    # Glob
    # ------------------------------------------------------------------

    def _walk(self, node: DirNode, prefix: str) -> Iterator[str]:
        """Yield all absolute paths under *node* (files and dirs)."""
        for name, child in node.children.items():
            child_path = prefix.rstrip("/") + "/" + name
            yield child_path
            if isinstance(child, DirNode):
                yield from self._walk(child, child_path)

    def rename(self, src: str, dst: str) -> None:
        """Move a node from *src* to *dst* within the VFS.

        Raises ``FileNotFoundError`` if *src* does not exist.
        """
        src = posixpath.normpath(src)
        dst = posixpath.normpath(dst)
        src_parent, src_name = self._get_parent(src)
        src_node = src_parent.children.get(src_name)
        if src_node is None:
            raise FileNotFoundError(f"No such file or directory: {src!r}")

        # If dst is an existing directory, move src inside it.
        dst_node = self.get_node(dst)
        if isinstance(dst_node, DirNode):
            dst_node.children[src_name] = src_node
        else:
            dst_parent, dst_name = self._get_parent(dst)
            dst_parent.children[dst_name] = src_node

        del src_parent.children[src_name]

    def copy_file(self, src: str, dst: str) -> None:
        """Copy a file from *src* to *dst*.

        Raises ``FileNotFoundError`` if *src* does not exist and
        ``IsADirectoryError`` if *src* is a directory.
        """
        src = posixpath.normpath(src)
        dst = posixpath.normpath(dst)
        src_node = self.get_node(src)
        if src_node is None:
            raise FileNotFoundError(f"No such file or directory: {src!r}")
        if isinstance(src_node, DirNode):
            raise IsADirectoryError(f"Is a directory: {src!r}")

        # If dst is an existing directory, copy file inside it.
        dst_node = self.get_node(dst)
        if isinstance(dst_node, DirNode):
            basename = posixpath.basename(src)
            self.write(posixpath.join(dst, basename), src_node.content)
        else:
            self.write(dst, src_node.content)

    def copy_tree(self, src: str, dst: str) -> None:
        """Recursively copy a directory tree from *src* to *dst*."""
        src = posixpath.normpath(src)
        dst = posixpath.normpath(dst)
        src_node = self.get_node(src)
        if src_node is None:
            raise FileNotFoundError(f"No such file or directory: {src!r}")
        if isinstance(src_node, FileNode):
            self.copy_file(src, dst)
            return
        # Create destination directory
        if not self.exists(dst):
            self.mkdir(dst, parents=True)
        for name, child in src_node.children.items():
            child_src = src.rstrip("/") + "/" + name
            child_dst = dst.rstrip("/") + "/" + name
            if isinstance(child, DirNode):
                self.copy_tree(child_src, child_dst)
            else:
                self.write(child_dst, child.content)

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Walk a directory tree, yielding ``(dirpath, dirnames, filenames)``.

        Works like ``os.walk`` — top-down traversal.
        """
        top = posixpath.normpath(top)
        node = self.get_node(top)
        if node is None or not isinstance(node, DirNode):
            return
        dirnames: list[str] = []
        filenames: list[str] = []
        for name, child in sorted(node.children.items()):
            if isinstance(child, DirNode):
                dirnames.append(name)
            else:
                filenames.append(name)
        yield top, dirnames, filenames
        for d in dirnames:
            yield from self.walk(top.rstrip("/") + "/" + d)

    def rmtree(self, path: str) -> None:
        """Recursively remove a directory and all its contents."""
        path = posixpath.normpath(path)
        if path == "/":
            raise OSError("Cannot remove root directory")
        parent, basename = self._get_parent(path)
        child = parent.children.get(basename)
        if child is None:
            raise FileNotFoundError(f"No such file or directory: {path!r}")
        del parent.children[basename]

    def glob(self, pattern: str, cwd: str) -> list[str]:
        """Return sorted absolute paths matching an fnmatch *pattern*.

        The pattern is resolved against *cwd* first, then matched
        against all paths in the VFS tree using ``fnmatch``.
        """
        abs_pattern = self.resolve(pattern, cwd)
        all_paths = ["/", *list(self._walk(self.root, "/"))]
        matched = [p for p in all_paths if fnmatch.fnmatch(p, abs_pattern)]
        return sorted(matched)
