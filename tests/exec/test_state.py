"""Tests for ShellState runtime state management."""

import pytest

from agentsh.runtime.state import ShellState

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def state() -> ShellState:
    """Return a default ShellState."""
    return ShellState()


# ------------------------------------------------------------------
# Default initialisation
# ------------------------------------------------------------------


class TestDefaults:
    def test_default_cwd(self, state: ShellState) -> None:
        assert state.cwd == "/"

    def test_default_variables_has_ifs(self, state: ShellState) -> None:
        assert state.variables == {"IFS": " \t\n"}

    def test_default_exported_env_empty(self, state: ShellState) -> None:
        assert state.exported_env == {}

    def test_default_functions_empty(self, state: ShellState) -> None:
        assert state.functions == {}

    def test_default_positional_params_empty(self, state: ShellState) -> None:
        assert state.positional_params == []

    def test_default_last_status(self, state: ShellState) -> None:
        assert state.last_status == 0

    def test_default_options(self, state: ShellState) -> None:
        opts = state.options
        assert opts.errexit is False
        assert opts.nounset is False
        assert opts.pipefail is False
        assert opts.xtrace is False
        assert opts.noglob is False


# ------------------------------------------------------------------
# Variable get / set
# ------------------------------------------------------------------


class TestVariables:
    def test_set_and_get(self, state: ShellState) -> None:
        state.set_var("FOO", "bar")
        assert state.get_var("FOO") == "bar"

    def test_get_missing_returns_none(self, state: ShellState) -> None:
        assert state.get_var("MISSING") is None

    def test_get_falls_back_to_exported_env(self, state: ShellState) -> None:
        state.exported_env["LANG"] = "en_US.UTF-8"
        assert state.get_var("LANG") == "en_US.UTF-8"

    def test_variables_shadow_exported(self, state: ShellState) -> None:
        state.exported_env["X"] = "from_env"
        state.set_var("X", "from_var")
        assert state.get_var("X") == "from_var"

    def test_set_var_updates_exported_if_present(self, state: ShellState) -> None:
        state.export_var("PATH", "/usr/bin")
        state.set_var("PATH", "/usr/local/bin")
        assert state.exported_env["PATH"] == "/usr/local/bin"
        assert state.get_var("PATH") == "/usr/local/bin"

    def test_set_var_does_not_auto_export(self, state: ShellState) -> None:
        state.set_var("PRIVATE", "secret")
        assert "PRIVATE" not in state.exported_env


# ------------------------------------------------------------------
# Export
# ------------------------------------------------------------------


class TestExport:
    def test_export_with_value(self, state: ShellState) -> None:
        state.export_var("HOME", "/home/user")
        assert state.get_var("HOME") == "/home/user"
        assert state.exported_env["HOME"] == "/home/user"

    def test_export_existing_variable(self, state: ShellState) -> None:
        state.set_var("FOO", "bar")
        state.export_var("FOO")
        assert state.exported_env["FOO"] == "bar"

    def test_export_missing_variable_exports_empty(self, state: ShellState) -> None:
        state.export_var("UNDEF")
        assert state.exported_env["UNDEF"] == ""

    def test_export_with_value_overrides(self, state: ShellState) -> None:
        state.set_var("X", "old")
        state.export_var("X", "new")
        assert state.get_var("X") == "new"
        assert state.exported_env["X"] == "new"


# ------------------------------------------------------------------
# Scope chain (environment frames)
# ------------------------------------------------------------------


class TestScope:
    def test_push_creates_child(self, state: ShellState) -> None:
        state.set_var("X", "outer")
        state.push_scope()
        assert state.get_var("X") == "outer"  # visible from child

    def test_set_local(self, state: ShellState) -> None:
        state.set_var("X", "outer")
        state.push_scope()
        state.scope.set_local("X", "inner")
        assert state.get_var("X") == "inner"
        state.pop_scope()
        assert state.get_var("X") == "outer"

    def test_new_var_in_child_scope_is_global(self, state: ShellState) -> None:
        """New variables set via set_var in a child scope go to the global frame."""
        state.push_scope()
        state.set_var("GLOBAL_VAR", "val")
        assert state.get_var("GLOBAL_VAR") == "val"
        state.pop_scope()
        # Variable persists in the global frame (bash dynamic scope)
        assert state.get_var("GLOBAL_VAR") == "val"

    def test_local_var_in_child_scope(self, state: ShellState) -> None:
        """Variables set via set_local are scoped to the child frame."""
        state.push_scope()
        state.scope.set_local("LOCAL", "val")
        assert state.get_var("LOCAL") == "val"
        state.pop_scope()
        assert state.get_var("LOCAL") is None

    def test_modify_parent_var(self, state: ShellState) -> None:
        state.set_var("X", "outer")
        state.push_scope()
        state.set_var("X", "modified")  # should modify parent's binding
        state.pop_scope()
        assert state.get_var("X") == "modified"

    def test_flatten(self, state: ShellState) -> None:
        state.set_var("A", "1")
        state.push_scope()
        state.scope.set_local("B", "2")
        flat = state.scope.flatten()
        assert flat["A"] == "1"
        assert flat["B"] == "2"

    def test_snapshot_detaches(self, state: ShellState) -> None:
        state.set_var("X", "original")
        snap = state.scope.snapshot()
        snap.set("X", "changed")
        assert state.get_var("X") == "original"


# ------------------------------------------------------------------
# Copy (subshell isolation)
# ------------------------------------------------------------------


class TestCopy:
    def test_copy_isolates_variables(self, state: ShellState) -> None:
        state.set_var("A", "1")
        child = state.copy()
        child.set_var("A", "2")
        child.set_var("B", "3")
        assert state.get_var("A") == "1"
        assert state.get_var("B") is None

    def test_copy_isolates_exported_env(self, state: ShellState) -> None:
        state.export_var("E", "orig")
        child = state.copy()
        child.exported_env["E"] = "changed"
        assert state.exported_env["E"] == "orig"

    def test_copy_shares_functions(self, state: ShellState) -> None:
        sentinel = object()  # type: ignore[assignment]
        state.functions["myfunc"] = sentinel  # type: ignore[assignment]
        child = state.copy()
        assert child.functions is state.functions
        assert child.functions["myfunc"] is sentinel

    def test_copy_isolates_positional_params(self, state: ShellState) -> None:
        state.positional_params = ["a", "b"]
        child = state.copy()
        child.positional_params.append("c")
        assert state.positional_params == ["a", "b"]

    def test_copy_isolates_options(self, state: ShellState) -> None:
        state.options.errexit = True
        child = state.copy()
        child.options.errexit = False
        assert state.options.errexit is True

    def test_copy_preserves_cwd(self) -> None:
        state = ShellState(cwd="/home/user")
        child = state.copy()
        assert child.cwd == "/home/user"

    def test_copy_preserves_last_status(self) -> None:
        state = ShellState(last_status=42)
        child = state.copy()
        assert child.last_status == 42


# ------------------------------------------------------------------
# Positional parameters
# ------------------------------------------------------------------


class TestPositionalParams:
    def test_set_positional_params(self) -> None:
        state = ShellState(positional_params=["script.sh", "arg1", "arg2"])
        assert state.positional_params == ["script.sh", "arg1", "arg2"]

    def test_positional_params_mutable(self, state: ShellState) -> None:
        state.positional_params.append("first")
        state.positional_params.append("second")
        assert state.positional_params == ["first", "second"]
