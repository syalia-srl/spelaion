"""Host folders mounted at sandbox paths, behind one resolver.

Every sandbox path becomes a host path in :meth:`MountFs.host_path` and
nowhere else.  Paths outside every mount do not exist; ``/`` and the
folders above a mount point are synthetic directories.
"""

from __future__ import annotations

import contextlib
import errno
import fnmatch
import os
import posixpath
import shutil
import stat
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from spelaion.vfs.nodes import DirNode, FileNode

_GLOB_CHARS = frozenset("*?[")


@dataclass(frozen=True)
class Mount:
    """A host folder visible inside the sandbox at *path*."""

    path: str
    host: str | Path
    readonly: bool = False


@dataclass(frozen=True)
class _Mounted:
    path: str
    host: Path
    readonly: bool


def _error(code: int, path: str) -> OSError:
    # OSError picks the subclass from errno; EROFS has none, and callers
    # catch a refused write as PermissionError.
    cls = PermissionError if code == errno.EROFS else OSError
    return cls(code, os.strerror(code), path)


def _normalize(path: str) -> str:
    """Normalise an absolute path lexically; ``..`` stops at ``/``."""
    norm = posixpath.normpath("/" + path.lstrip("/"))
    # normpath keeps a leading "//", which POSIX leaves implementation-defined.
    return "/" + norm.lstrip("/")


@contextlib.contextmanager
def _as_sandbox(path: str) -> Iterator[None]:
    """Re-raise host ``OSError``s naming *path*, never the host path."""
    try:
        yield
    except OSError as e:
        if e.errno is None:
            raise
        raise _error(e.errno, path) from None


class MountFs:
    """A :class:`~spelaion.vfs.base.Filesystem` over real host folders."""

    def __init__(self, mounts: list[Mount], *, max_disk: int | None = None) -> None:
        self._mounts = sorted(
            (
                _Mounted(_normalize(m.path), Path(m.host).resolve(), m.readonly)
                for m in mounts
            ),
            key=lambda m: len(m.path),
            reverse=True,
        )
        self._max_disk = max_disk

    # ------------------------------------------------------------------
    # The resolver
    # ------------------------------------------------------------------

    def resolve(self, path: str, cwd: str) -> str:
        """Make *path* absolute against *cwd* and normalise it lexically."""
        if not path.startswith("/"):
            path = cwd.rstrip("/") + "/" + path
        return _normalize(path)

    def _find(self, path: str) -> _Mounted | None:
        for m in self._mounts:
            if path == m.path or path.startswith(m.path.rstrip("/") + "/"):
                return m
        return None

    def host_path(self, path: str, *, write: bool = False) -> Path:
        """Return the host path behind sandbox *path*, or raise.

        1. Normalise lexically, so ``..`` cannot climb above ``/``.
        2. Take the longest mount point that prefixes it (``ENOENT`` if none).
        3. Follow symlinks and refuse a result outside the mount (``EACCES``).
        4. For a write, refuse a read-only mount (``EROFS``) and a full
           disk (``EDQUOT``).
        """
        path = _normalize(path)
        mount = self._find(path)
        if mount is None:
            raise _error(errno.ENOENT, path)
        rel = posixpath.relpath(path, mount.path)
        host = (mount.host / rel).resolve()
        if not host.is_relative_to(mount.host):
            raise _error(errno.EACCES, path)
        if write:
            if mount.readonly:
                raise _error(errno.EROFS, path)
            if self._max_disk is not None and self.disk_used() > self._max_disk:
                raise _error(errno.EDQUOT, path)
        return host

    def disk_used(self) -> int:
        """Total bytes of regular files under the writable mounts."""
        roots = [m.host for m in self._mounts if not m.readonly]
        roots = [
            r for r in roots if not any(r != o and r.is_relative_to(o) for o in roots)
        ]
        total = 0
        for root in roots:
            for dirpath, _, filenames in os.walk(root):
                for name in filenames:
                    with contextlib.suppress(OSError):
                        st = os.lstat(os.path.join(dirpath, name))
                        if stat.S_ISREG(st.st_mode):
                            total += st.st_size
        return total

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _mount_children(self, path: str) -> set[str]:
        """Names of mount points directly or indirectly below *path*."""
        prefix = path.rstrip("/") + "/"
        return {
            m.path[len(prefix) :].split("/")[0]
            for m in self._mounts
            if m.path.startswith(prefix)
        }

    def _kind(self, path: str) -> str | None:
        """``"dir"``, ``"file"`` or ``None`` for sandbox *path*."""
        path = _normalize(path)
        if self._find(path) is not None:
            try:
                host = self.host_path(path)
            except OSError:
                host = None
            if host is not None and host.is_dir():
                return "dir"
            if host is not None and host.exists():
                return "file"
        if path == "/" or self._mount_children(path):
            return "dir"
        return None

    def _entry(self, path: str) -> Path:
        """Host path of the entry *path* itself, its last symlink unfollowed.

        For removing and renaming: the parent goes through the resolver,
        a read-only mount is refused, and a mount point cannot be removed.
        The disk cap does not apply, so a full disk can still be cleaned.
        """
        path = _normalize(path)
        mount = self._find(path)
        if mount is None:
            raise _error(errno.ENOENT, path)
        if path == mount.path:
            raise _error(errno.EBUSY, path)
        parent = self.host_path(posixpath.dirname(path))
        if mount.readonly:
            raise _error(errno.EROFS, path)
        return parent / posixpath.basename(path)

    # ------------------------------------------------------------------
    # Filesystem
    # ------------------------------------------------------------------

    def get_node(self, path: str) -> FileNode | DirNode | None:
        """Build a node from the host entry; directories list one level."""
        path = _normalize(path)
        kind = self._kind(path)
        if kind is None:
            return None
        if kind == "file":
            host = self.host_path(path)
            with _as_sandbox(path):
                mode = host.stat().st_mode & 0o7777
                return FileNode(
                    content=host.read_bytes(), executable=bool(mode & 0o111), mode=mode
                )
        children: dict[str, FileNode | DirNode] = {}
        for name in self.listdir(path):
            child = path.rstrip("/") + "/" + name
            children[name] = DirNode() if self._kind(child) == "dir" else FileNode()
        return DirNode(children=children)

    def read(self, path: str) -> bytes:
        path = _normalize(path)
        host = self.host_path(path)
        if host.is_dir():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
        with _as_sandbox(path):
            return host.read_bytes()

    def write(self, path: str, data: bytes, append: bool = False) -> None:
        """Write *data*, creating missing parents inside the mount."""
        path = _normalize(path)
        host = self.host_path(path, write=True)
        if host.is_dir():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
        if self._max_disk is not None:
            old = 0 if append or not host.is_file() else host.stat().st_size
            if self.disk_used() - old + len(data) > self._max_disk:
                raise _error(errno.EDQUOT, path)
        with _as_sandbox(path):
            host.parent.mkdir(parents=True, exist_ok=True)
            with host.open("ab" if append else "wb") as f:
                f.write(data)

    def exists(self, path: str) -> bool:
        return self._kind(path) is not None

    def is_dir(self, path: str) -> bool:
        return self._kind(path) == "dir"

    def is_file(self, path: str) -> bool:
        return self._kind(path) == "file"

    def mkdir(self, path: str, parents: bool = False) -> None:
        path = _normalize(path)
        if self._kind(path) == "dir":
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), path)
        host = self.host_path(path, write=True)
        with _as_sandbox(path):
            host.mkdir(parents=parents)

    def listdir(self, path: str) -> list[str]:
        path = _normalize(path)
        kind = self._kind(path)
        if kind is None:
            raise _error(errno.ENOENT, path)
        if kind == "file":
            raise _error(errno.ENOTDIR, path)
        names = self._mount_children(path)
        if self._find(path) is not None:
            with contextlib.suppress(OSError):
                host = self.host_path(path)
                with _as_sandbox(path):
                    names.update(os.listdir(host))
        return sorted(names)

    def unlink(self, path: str) -> None:
        path = _normalize(path)
        entry = self._entry(path)
        if entry.is_dir() and not entry.is_symlink():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), path)
        with _as_sandbox(path):
            entry.unlink()

    def rmdir(self, path: str) -> None:
        path = _normalize(path)
        entry = self._entry(path)
        with _as_sandbox(path):
            entry.rmdir()

    def rename(self, src: str, dst: str) -> None:
        src = _normalize(src)
        dst = _normalize(dst)
        src_entry = self._entry(src)
        if self.is_dir(dst):
            dst = dst.rstrip("/") + "/" + posixpath.basename(src)
        dst_entry = self._entry(dst)
        with _as_sandbox(src):
            shutil.move(src_entry, dst_entry)

    def copy_file(self, src: str, dst: str) -> None:
        src = _normalize(src)
        dst = _normalize(dst)
        data = self.read(src)
        if self.is_dir(dst):
            dst = dst.rstrip("/") + "/" + posixpath.basename(src)
        self.write(dst, data)

    def copy_tree(self, src: str, dst: str) -> None:
        src = _normalize(src)
        dst = _normalize(dst)
        kind = self._kind(src)
        if kind is None:
            raise _error(errno.ENOENT, src)
        if kind == "file":
            self.copy_file(src, dst)
            return
        if not self.exists(dst):
            self.mkdir(dst, parents=True)
        for dirpath, dirnames, filenames in self.walk(src):
            target = dst + dirpath[len(src) :]
            for d in dirnames:
                if not self.exists(target + "/" + d):
                    self.mkdir(target + "/" + d, parents=True)
            for f in filenames:
                self.write(target + "/" + f, self.read(dirpath + "/" + f))

    def walk(self, top: str) -> Iterator[tuple[str, list[str], list[str]]]:
        """Like ``os.walk``: top-down, symlinked folders listed, not entered."""
        top = _normalize(top)
        if self._kind(top) != "dir":
            return
        dirnames: list[str] = []
        filenames: list[str] = []
        descend: list[str] = []
        for name in self.listdir(top):
            child = top.rstrip("/") + "/" + name
            if self._kind(child) == "dir":
                dirnames.append(name)
                if not self._is_symlink(child):
                    descend.append(name)
            else:
                filenames.append(name)
        yield top, dirnames, filenames
        for d in descend:
            yield from self.walk(top.rstrip("/") + "/" + d)

    def _is_symlink(self, path: str) -> bool:
        mount = self._find(path)
        if mount is None or path == mount.path:
            return False
        try:
            parent = self.host_path(posixpath.dirname(path))
        except OSError:
            return False
        return (parent / posixpath.basename(path)).is_symlink()

    def rmtree(self, path: str) -> None:
        path = _normalize(path)
        entry = self._entry(path)
        with _as_sandbox(path):
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    def glob(self, pattern: str, cwd: str) -> list[str]:
        """Sorted absolute paths matching *pattern*, walked from its fixed prefix."""
        abs_pattern = self.resolve(pattern, cwd)
        fixed: list[str] = []
        for part in abs_pattern.strip("/").split("/"):
            if _GLOB_CHARS & set(part):
                break
            fixed.append(part)
        base = "/" + "/".join(fixed)
        candidates = [base] if self.exists(base) else []
        for dirpath, dirnames, filenames in self.walk(base):
            candidates.extend(
                dirpath.rstrip("/") + "/" + n for n in dirnames + filenames
            )
        return sorted(p for p in candidates if fnmatch.fnmatch(p, abs_pattern))
