"""Sandbox: an emulated bash over host folders, with edit and write."""

from __future__ import annotations

from pathlib import Path
from types import TracebackType

from spelaion._shell import Shell
from spelaion._types import Limits, Result
from spelaion.vfs.mounts import Mount

_DEFAULT_LIMITS = Limits()


class Sandbox:
    """The three agent tools, ``bash``, ``edit`` and ``write``, over *mounts*.

    Files persist between calls; shell state (variables, functions, the
    working directory) starts afresh from *cwd* and *env* on every call.
    """

    def __init__(
        self,
        mounts: list[Mount],
        *,
        cwd: str = "/",
        env: dict[str, str] | None = None,
        limits: Limits = _DEFAULT_LIMITS,
        python: bool = False,
    ) -> None:
        _check_mounts(mounts)
        self.limits = limits
        self.python = python
        self._shell = Shell(list(mounts), cwd, dict(env or {}), limits)

    def bash(self, command: str) -> Result:
        """Run *command* in a fresh shell."""
        return self._shell.call("bash", {"command": command})

    def edit(self, path: str, old: str, new: str) -> Result:
        """Replace the one occurrence of *old* in *path* with *new*."""
        return self._shell.call("edit", {"path": path, "old": old, "new": new})

    def write(self, path: str, content: str) -> Result:
        """Create or overwrite *path* with *content*."""
        return self._shell.call("write", {"path": path, "content": content})

    def close(self) -> None:
        """Release the sandbox; nothing to release while it runs in process."""

    def __enter__(self) -> Sandbox:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _check_mounts(mounts: list[Mount]) -> None:
    """Every host folder exists, and no host folder lies inside another."""
    hosts: list[tuple[Mount, Path]] = []
    for m in mounts:
        host = Path(m.host).resolve()
        if not host.is_dir():
            raise FileNotFoundError(
                f"mount {m.path}: host folder {m.host} is missing or not a folder"
            )
        hosts.append((m, host))
    for i, (a, ha) in enumerate(hosts):
        for b, hb in hosts[i + 1 :]:
            if ha.is_relative_to(hb) or hb.is_relative_to(ha):
                raise ValueError(
                    f"mounts {a.path} and {b.path} overlap: their host folders "
                    f"{a.host} and {b.host} are the same or nested"
                )
