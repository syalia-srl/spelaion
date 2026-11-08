"""Host commands: what a handler receives, and the built-in ``show``.

Host commands run in the sandbox's own process, the product's, not in the
child; see :meth:`spelaion.Sandbox.command`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from spelaion._types import Attachment, Result
from spelaion.vfs.mounts import MountFs

MAX_IMAGE = 5 * 2**20  # bytes, one attachment
MAX_ATTACHMENTS = 8  # per call
MAX_ATTACHED = 20 * 2**20  # bytes, all of a call's attachments

_MIMES = ("image/png", "image/jpeg", "image/webp")


@dataclass
class HostContext:
    """What a host command receives beside its arguments.

    *cwd* and *env* are the calling shell's, after any ``cd`` or ``export``
    in the same call. *remaining_s* is the time left before the call's
    deadline; a command that runs past it still finishes here, but the call
    returns the timeout result (exit 124) instead of its output.
    """

    stdin: str
    cwd: str
    env: dict[str, str]
    remaining_s: float
    _fs: MountFs = field(repr=False, compare=False)
    _attachments: list[Attachment] = field(
        default_factory=list[Attachment], repr=False, compare=False
    )
    # The errors path() and attach() raised: they name sandbox paths.
    _raised: list[OSError] = field(
        default_factory=list[OSError], repr=False, compare=False
    )

    def path(self, p: str, *, write: bool = False) -> Path:
        """The host path behind sandbox path *p*, relative to *cwd*.

        Raises FileNotFoundError outside every mount, PermissionError for a
        symlink that leaves its mount or, with *write*, a read-only mount.

        Call it with ``write=True`` before writing: the returned path writes
        into a read-only mount too, since handlers are trusted. The check is
        made now; a writer outside this call could still swap a component of
        the path for a symlink before the handler opens it.
        """
        try:
            return self._fs.host_path(self._fs.resolve(p, self.cwd), write=write)
        except OSError as e:
            self._raised.append(e)
            raise

    def attach(
        self, data: bytes | str, mime: str | None = None, name: str = ""
    ) -> None:
        """Hand an image back with the call's result.

        *data* is the image, or a sandbox path to read it from. *mime* is
        found from the data when not given. PNG, JPEG and WebP only, up to
        5 MB each, 8 images and 20 MB a call; anything else raises ValueError.
        """
        if isinstance(data, str):
            shown = self._fs.resolve(data, self.cwd)
            host = self.path(data)
            try:
                with host.open("rb") as f:
                    data = f.read(MAX_IMAGE + 1)
            except OSError as e:
                err = OSError(e.errno, e.strerror, shown)
                self._raised.append(err)
                raise err from None
            name = name or shown
        else:
            shown = name or "image"
        if len(data) > MAX_IMAGE:
            raise ValueError(f"{shown}: larger than 5 MB")
        if mime is None:
            mime = _sniff(data)
            if mime is None:
                raise ValueError(f"{shown}: not a PNG, JPEG or WebP image")
        elif mime not in _MIMES:
            raise ValueError(f"{mime} is not image/png, image/jpeg or image/webp")
        add_attachment(self._attachments, Attachment(mime=mime, data=data, name=name))


HostHandler = Callable[[HostContext, list[str]], Result]


def add_attachment(attachments: list[Attachment], attachment: Attachment) -> None:
    """Add *attachment* to a call's *attachments*, within the call's bounds."""
    if len(attachments) >= MAX_ATTACHMENTS:
        raise ValueError("too many images in one call")
    if sum(len(a.data) for a in attachments) + len(attachment.data) > MAX_ATTACHED:
        raise ValueError("images too large for one call")
    attachments.append(attachment)


def show(ctx: HostContext, args: list[str]) -> Result:
    """``show FILE...``: attach each image so the model can see it."""
    if not args:
        return Result(stderr="show: usage: show FILE...\n", exit_code=2)
    for arg in args:
        ctx.attach(arg)
    return Result()


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
