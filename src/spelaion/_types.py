"""What a sandbox call returns, and the limits it runs under."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class Attachment:
    """An image a call hands back beside its text."""

    mime: str  # image/png | image/jpeg | image/webp
    data: bytes
    name: str  # sandbox path it came from, or a label


@dataclass
class Result:
    """The outcome of one ``bash``, ``edit`` or ``write`` call."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    attachments: list[Attachment] = field(default_factory=list[Attachment])


@dataclass(frozen=True)
class Limits:
    """Per-sandbox limits."""

    timeout_s: float = 30
    max_output: int = 30_000  # characters, stdout and stderr each
    max_disk: int = 50_000_000  # bytes, all writable mounts together
    memory_mb: int = 1024  # child process data limit

    def __post_init__(self) -> None:
        t = self.timeout_s
        if not math.isfinite(t) or t <= 0:
            raise ValueError(f"timeout_s must be a finite number above 0, not {t!r}")
        for name in ("max_output", "max_disk", "memory_mb"):
            n = getattr(self, name)
            if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
                raise ValueError(f"{name} must be a positive integer, not {n!r}")
