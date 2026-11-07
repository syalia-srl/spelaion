"""Tests for the planner / dry-run mode."""

from agentsh.api.engine import ShellEngine
from agentsh.policy.rules import PolicyConfig, PolicyRule


class TestPlanner:
    def test_plan_simple_command(self) -> None:
        engine = ShellEngine()
        result = engine.plan("echo hello")
        assert not result.has_errors
        assert len(result.plan.steps) == 1
        assert result.plan.steps[0].command == "echo"
        assert result.plan.steps[0].resolution == "builtin"

    def test_plan_unknown_command(self) -> None:
        engine = ShellEngine()
        result = engine.plan("unknown_cmd arg1")
        assert not result.has_errors
        step = result.plan.steps[0]
        assert step.resolution == "not_found"
        assert any(e.kind == "unresolved_command" for e in step.effects)

    def test_plan_redirect(self) -> None:
        engine = ShellEngine()
        result = engine.plan("echo hello > output.txt")
        assert not result.has_errors
        assert any(e.kind == "vfs_write" for e in result.plan.effects)

    def test_plan_assignment(self) -> None:
        engine = ShellEngine()
        result = engine.plan("FOO=bar")
        assert not result.has_errors
        assert any(e.kind == "state_change" for e in result.plan.effects)

    def test_plan_policy_denied(self) -> None:
        policy = PolicyConfig(
            rules=[PolicyRule(kind="deny", target="command", pattern="rm")]
        )
        engine = ShellEngine(policy=policy)
        result = engine.plan("rm -rf /")
        assert any(e.kind == "policy_denied" for e in result.plan.effects)
        assert len(result.plan.warnings) > 0

    def test_plan_syntax_error(self) -> None:
        engine = ShellEngine()
        result = engine.plan("echo (")
        assert result.has_errors
