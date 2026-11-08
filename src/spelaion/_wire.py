"""Messages between a sandbox and its child, over a multiprocessing Connection.

All are picklable tuples. Before them, the parent sends the child its
``sys.path`` and its startup arguments (see :mod:`spelaion._child`).

- ``("ready",)``, child to parent, once: started, the call clock may run.
- ``("call", kind, payload)``, parent to child; *kind* is ``bash``, ``edit``
  or ``write`` and *payload* holds that call's arguments.
- ``("host", name, args, stdin, cwd, env)``, child to parent: run the host
  command *name* in the parent.
- ``("host_result", result)``, parent to child: the host command's Result.
- ``("register", name)``, parent to child, between calls: a host command
  registered after the child started.
- ``("done", result)``, child to parent: the call's Result.

The parent trusts nothing the child sends: it reads each message within
:func:`max_message` bytes and decodes it with :func:`decode`, which loads
no class but Result and Attachment and checks the message's shape.
"""

from __future__ import annotations

import io
import pickle
from typing import Any, Literal, cast

from spelaion import _types
from spelaion._types import Limits, Result

Call = tuple[Literal["call"], str, dict[str, Any]]
Host = tuple[Literal["host"], str, list[str], str, str, dict[str, str]]
HostResult = tuple[Literal["host_result"], Result]
Done = tuple[Literal["done"], Result]
Ready = tuple[Literal["ready"]]
Register = tuple[Literal["register"], str]

ToChild = Call | HostResult | Register
ToParent = Host | Done

# Set in the parent's environment, it registers kill_self_for_test and
# forge_for_test in the child.
TEST_HOOKS = "SPELAION_TEST_HOOKS"


def max_message(limits: Limits) -> int:
    """The largest message, in bytes, the parent reads from the child.

    A ``done`` carries stdout and stderr of up to ``max_output`` characters
    each, and pickle writes a character in up to 4 bytes.
    """
    return 8 * limits.max_output + 1_000_000


class BadMessage(Exception):
    """The child sent a message the parent refuses; the text says what."""


def decode(data: bytes, tags: tuple[str, ...]) -> ToParent | Ready:
    """The child's message in *data*, whose tag must be one of *tags*."""
    try:
        msg = _Unpickler(io.BytesIO(data)).load()
    except Exception as e:
        raise BadMessage("a bad message") from e
    if not isinstance(msg, tuple) or not _well_formed(cast(tuple[Any, ...], msg)):
        raise BadMessage("a bad message")
    if msg[0] not in tags:
        raise BadMessage("a bad message")
    return cast(ToParent | Ready, msg)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str) -> Any:
        if module == "spelaion._types" and name in ("Result", "Attachment"):
            return getattr(_types, name)
        raise pickle.UnpicklingError(f"{module}.{name} is not allowed")


def _well_formed(msg: tuple[Any, ...]) -> bool:
    match msg:
        case ("ready",):
            return True
        case ("done", result):
            return _is_result(result)
        case ("host", str(), list(), str(), str(), dict()):
            args = cast(list[object], msg[2])
            env = cast(dict[object, object], msg[5])
            return all(isinstance(a, str) for a in args) and all(
                isinstance(k, str) and isinstance(v, str) for k, v in env.items()
            )
        case _:
            return False


def _is_result(r: object) -> bool:
    if type(r) is not Result:
        return False
    fields = vars(r)
    return (
        isinstance(fields.get("stdout"), str)
        and isinstance(fields.get("stderr"), str)
        and type(fields.get("exit_code")) is int
        and type(fields.get("timed_out")) is bool
        and fields.get("attachments") == []
    )
