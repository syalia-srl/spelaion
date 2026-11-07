"""Messages between a sandbox and its child, over a multiprocessing Connection.

All are picklable tuples. Before them, the parent sends the child its
``sys.path`` and its startup arguments (see :mod:`spelaion._child`).

- ``("ready",)``, child to parent, once: started, the call clock may run.
- ``("call", kind, payload)``, parent to child; *kind* is ``bash``, ``edit``
  or ``write`` and *payload* holds that call's arguments.
- ``("host", name, args, stdin, cwd, env)``, child to parent: run the host
  command *name* in the parent.
- ``("host_result", result)``, parent to child: the host command's Result.
- ``("done", result)``, child to parent: the call's Result.
"""

from __future__ import annotations

from typing import Any, Literal

from spelaion._types import Result

Call = tuple[Literal["call"], str, dict[str, Any]]
Host = tuple[Literal["host"], str, list[str], str, str, dict[str, str]]
HostResult = tuple[Literal["host_result"], Result]
Done = tuple[Literal["done"], Result]
Ready = tuple[Literal["ready"]]

ToChild = Call | HostResult
ToParent = Host | Done

# Set in the parent's environment, it registers kill_self_for_test in the child.
TEST_HOOKS = "SPELAION_TEST_HOOKS"
