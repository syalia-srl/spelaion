"""Mutable shell state carried through execution.

Uses an **environment frame chain** (inspired by Crafting Interpreters)
for variable scoping.  Each :class:`Scope` holds local bindings and a
pointer to its enclosing scope, giving O(depth) lookups that naturally
support function-local variables and subshell isolation.

The top-level :class:`ShellState` owns the global scope, the function
table, the cwd, and shell options.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentsh.ast.nodes import FunctionDef

from agentsh.runtime.options import ShellOptions


class Scope:
    """A single variable-binding frame with an optional parent link.

    Lookup walks the chain outward until the name is found or the chain
    ends.  Assignment targets the *current* frame unless the name already
    exists in an ancestor (matching Bash's dynamic-scope semantics).
    """

    __slots__ = ("array_bindings", "assoc_bindings", "bindings", "parent")

    def __init__(
        self,
        parent: Scope | None = None,
        bindings: dict[str, str] | None = None,
        array_bindings: dict[str, list[str]] | None = None,
        assoc_bindings: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.bindings: dict[str, str] = bindings if bindings is not None else {}
        self.array_bindings: dict[str, list[str]] = (
            array_bindings if array_bindings is not None else {}
        )
        self.assoc_bindings: dict[str, dict[str, str]] = (
            assoc_bindings if assoc_bindings is not None else {}
        )
        self.parent = parent

    # -- lookup ---------------------------------------------------------------

    def get(self, name: str) -> str | None:
        """Walk the scope chain looking for *name*."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.bindings:
                return scope.bindings[name]
            scope = scope.parent
        return None

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    # -- mutation -------------------------------------------------------------

    def set(self, name: str, value: str) -> None:
        """Set *name* in the nearest scope that already owns it.

        If the name is not found anywhere in the chain, create it in the
        **outermost** (global) frame — matching Bash's dynamic-scope
        semantics where non-local assignments in functions are global.
        """
        scope: Scope | None = self
        outermost = self
        while scope is not None:
            if name in scope.bindings:
                scope.bindings[name] = value
                return
            outermost = scope
            scope = scope.parent
        # New variable → global (outermost) frame
        outermost.bindings[name] = value

    def set_local(self, name: str, value: str) -> None:
        """Force *name* into the current frame (for ``local`` builtin)."""
        self.bindings[name] = value

    def unset(self, name: str) -> None:
        """Remove *name* from the nearest owning scope."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.bindings:
                del scope.bindings[name]
                return
            scope = scope.parent

    # -- array operations -----------------------------------------------------

    def get_array(self, name: str) -> list[str] | None:
        """Walk the scope chain looking for array *name*."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.array_bindings:
                return scope.array_bindings[name]
            scope = scope.parent
        return None

    def set_array(self, name: str, values: list[str]) -> None:
        """Set array *name* in the nearest scope that already owns it, or in *self*."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.array_bindings:
                scope.array_bindings[name] = values
                return
            scope = scope.parent
        self.array_bindings[name] = values

    def get_array_element(self, name: str, index: int) -> str | None:
        """Get a single element from array *name*."""
        arr = self.get_array(name)
        if arr is not None and 0 <= index < len(arr):
            return arr[index]
        return None

    def set_array_element(self, name: str, index: int, value: str) -> None:
        """Set a single element of array *name*, extending if needed."""
        arr = self.get_array(name)
        if arr is None:
            arr = []
            self.array_bindings[name] = arr
        while len(arr) <= index:
            arr.append("")
        arr[index] = value

    def flatten_arrays(self) -> dict[str, list[str]]:
        """Collapse the chain into a single dict of arrays."""
        result: dict[str, list[str]] = {}
        frames: list[Scope] = []
        scope: Scope | None = self
        while scope is not None:
            frames.append(scope)
            scope = scope.parent
        for frame in reversed(frames):
            result.update(frame.array_bindings)
        return result

    # -- associative array operations -----------------------------------------

    def get_assoc(self, name: str) -> dict[str, str] | None:
        """Walk the scope chain looking for associative array *name*."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.assoc_bindings:
                return scope.assoc_bindings[name]
            scope = scope.parent
        return None

    def set_assoc(self, name: str, values: dict[str, str]) -> None:
        """Set assoc array *name* in the nearest owning scope, or *self*."""
        scope: Scope | None = self
        while scope is not None:
            if name in scope.assoc_bindings:
                scope.assoc_bindings[name] = values
                return
            scope = scope.parent
        self.assoc_bindings[name] = values

    def get_assoc_element(self, name: str, key: str) -> str | None:
        """Get a single element from associative array *name*."""
        assoc = self.get_assoc(name)
        if assoc is not None:
            return assoc.get(key)
        return None

    def set_assoc_element(self, name: str, key: str, value: str) -> None:
        """Set a single element of associative array *name*."""
        assoc = self.get_assoc(name)
        if assoc is None:
            assoc = {}
            self.assoc_bindings[name] = assoc
        assoc[key] = value

    def flatten_assoc(self) -> dict[str, dict[str, str]]:
        """Collapse the chain into a single dict of associative arrays."""
        result: dict[str, dict[str, str]] = {}
        frames: list[Scope] = []
        scope: Scope | None = self
        while scope is not None:
            frames.append(scope)
            scope = scope.parent
        for frame in reversed(frames):
            result.update(frame.assoc_bindings)
        return result

    # -- child scope ----------------------------------------------------------

    def push(self, bindings: dict[str, str] | None = None) -> Scope:
        """Create a child scope whose parent is *self*."""
        return Scope(parent=self, bindings=bindings)

    # -- snapshot / isolation -------------------------------------------------

    def flatten(self) -> dict[str, str]:
        """Collapse the chain into a single dict (outermost wins)."""
        result: dict[str, str] = {}
        frames: list[Scope] = []
        scope: Scope | None = self
        while scope is not None:
            frames.append(scope)
            scope = scope.parent
        for frame in reversed(frames):
            result.update(frame.bindings)
        return result

    def snapshot(self) -> Scope:
        """Return a *detached* copy (for subshell isolation)."""
        return Scope(
            parent=None,
            bindings=dict(self.flatten()),
            array_bindings={k: list(v) for k, v in self.flatten_arrays().items()},
            assoc_bindings={k: dict(v) for k, v in self.flatten_assoc().items()},
        )


@dataclass
class ShellState:
    """Runtime state for a single shell session.

    Mirrors the key data a real Bash process keeps: the working
    directory, variables (via a :class:`Scope` chain), exported
    environment, function table, positional parameters, last exit
    status, and ``set`` options.
    """

    cwd: str = "/"
    scope: Scope = field(default_factory=Scope)
    exported_env: dict[str, str] = field(default_factory=lambda: {})
    functions: dict[str, FunctionDef] = field(default_factory=lambda: {})
    positional_params: list[str] = field(default_factory=lambda: [])
    last_status: int = 0
    options: ShellOptions = field(default_factory=ShellOptions)

    def __post_init__(self) -> None:
        """Initialize default shell variables."""
        if self.scope.get("IFS") is None:
            self.scope.set("IFS", " \t\n")

    # -- convenience properties for backward compat ---------------------------

    @property
    def variables(self) -> dict[str, str]:
        """Flat view of all variables (for legacy code paths)."""
        return self.scope.flatten()

    # -- variable access (delegates to scope chain) ---------------------------

    def get_var(self, name: str) -> str | None:
        """Look up variable, checking scope chain then exported env."""
        val = self.scope.get(name)
        if val is not None:
            return val
        return self.exported_env.get(name)

    def set_var(self, name: str, value: str) -> None:
        """Set a variable. If already exported, update the export too."""
        self.scope.set(name, value)
        if name in self.exported_env:
            self.exported_env[name] = value

    def export_var(self, name: str, value: str | None = None) -> None:
        """Mark *name* as exported, optionally assigning *value* first."""
        if value is not None:
            self.scope.set(name, value)
        val = self.scope.get(name) or ""
        self.exported_env[name] = val

    # -- array access (delegates to scope chain) ------------------------------

    def get_array(self, name: str) -> list[str] | None:
        """Look up array variable in scope chain."""
        return self.scope.get_array(name)

    def set_array(self, name: str, values: list[str]) -> None:
        """Set an array variable."""
        self.scope.set_array(name, values)

    def get_array_element(self, name: str, index: int) -> str | None:
        """Get a single element from an array."""
        return self.scope.get_array_element(name, index)

    def set_array_element(self, name: str, index: int, value: str) -> None:
        """Set a single element of an array."""
        self.scope.set_array_element(name, index, value)

    # -- associative array access (delegates to scope chain) ------------------

    def get_assoc(self, name: str) -> dict[str, str] | None:
        """Look up associative array variable in scope chain."""
        return self.scope.get_assoc(name)

    def set_assoc(self, name: str, values: dict[str, str]) -> None:
        """Set an associative array variable."""
        self.scope.set_assoc(name, values)

    def get_assoc_element(self, name: str, key: str) -> str | None:
        """Get a single element from an associative array."""
        return self.scope.get_assoc_element(name, key)

    def set_assoc_element(self, name: str, key: str, value: str) -> None:
        """Set a single element of an associative array."""
        self.scope.set_assoc_element(name, key, value)

    # -- scope management -----------------------------------------------------

    def push_scope(self, bindings: dict[str, str] | None = None) -> None:
        """Enter a new local scope (for function calls)."""
        self.scope = self.scope.push(bindings)

    def pop_scope(self) -> None:
        """Leave the current local scope."""
        if self.scope.parent is not None:
            self.scope = self.scope.parent

    # -- isolation ------------------------------------------------------------

    def copy(self) -> ShellState:
        """Create an isolated copy for subshell execution.

        Variables are snapshot-copied (detached from the parent chain).
        Functions are shared by reference (matching real Bash semantics).
        """
        return ShellState(
            cwd=self.cwd,
            scope=self.scope.snapshot(),
            exported_env=dict(self.exported_env),
            functions=self.functions,  # shared reference
            positional_params=list(self.positional_params),
            last_status=self.last_status,
            options=copy.copy(self.options),
        )
