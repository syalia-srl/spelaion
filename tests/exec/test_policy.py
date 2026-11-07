"""Tests for the policy engine.

Covers:
- Default allow behaviour
- Deny rules
- Allow rules
- Warn rules
- Glob pattern matching
- Path read/write checks
- Tool checks
"""

from __future__ import annotations

import pytest

from agentsh.policy.decisions import PolicyDecision, PolicyEngine
from agentsh.policy.rules import PolicyConfig, PolicyRule

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine() -> PolicyEngine:
    """Engine with no rules — everything defaults to allow."""
    return PolicyEngine()


@pytest.fixture()
def config() -> PolicyConfig:
    return PolicyConfig()


# ---------------------------------------------------------------------------
# Default behaviour
# ---------------------------------------------------------------------------


class TestDefaultAllow:
    """With no rules, every check should return allow."""

    def test_command_default_allow(self, engine: PolicyEngine) -> None:
        decision = engine.check_command("ls")
        assert decision.action == "allow"
        assert decision.rule_pattern == ""

    def test_path_read_default_allow(self, engine: PolicyEngine) -> None:
        decision = engine.check_path_read("/etc/passwd")
        assert decision.action == "allow"

    def test_path_write_default_allow(self, engine: PolicyEngine) -> None:
        decision = engine.check_path_write("/tmp/file.txt")
        assert decision.action == "allow"

    def test_tool_default_allow(self, engine: PolicyEngine) -> None:
        decision = engine.check_tool("web_search")
        assert decision.action == "allow"


# ---------------------------------------------------------------------------
# Deny rules
# ---------------------------------------------------------------------------


class TestDenyRules:
    """Deny rules should block the matching operation."""

    def test_deny_command(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="deny",
                    target="command",
                    pattern="rm",
                    reason="Destructive command",
                ),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("rm")
        assert decision.action == "deny"
        assert decision.reason == "Destructive command"
        assert decision.rule_pattern == "rm"

    def test_deny_does_not_affect_other_commands(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="rm"),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("ls")
        assert decision.action == "allow"

    def test_deny_does_not_cross_target_types(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="rm"),
            ]
        )
        engine = PolicyEngine(config)
        # "rm" is denied as a command, but not as a tool
        decision = engine.check_tool("rm")
        assert decision.action == "allow"


# ---------------------------------------------------------------------------
# Allow rules
# ---------------------------------------------------------------------------


class TestAllowRules:
    """Explicit allow rules should match and return allow."""

    def test_explicit_allow(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="allow",
                    target="command",
                    pattern="safe-cmd",
                    reason="Explicitly permitted",
                ),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("safe-cmd")
        assert decision.action == "allow"
        assert decision.reason == "Explicitly permitted"
        assert decision.rule_pattern == "safe-cmd"


# ---------------------------------------------------------------------------
# Warn rules
# ---------------------------------------------------------------------------


class TestWarnRules:
    """Warn rules should match and return warn action."""

    def test_warn_command(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="warn",
                    target="command",
                    pattern="curl",
                    reason="Network access detected",
                ),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("curl")
        assert decision.action == "warn"
        assert decision.reason == "Network access detected"


# ---------------------------------------------------------------------------
# Pattern matching with wildcards
# ---------------------------------------------------------------------------


class TestPatternMatching:
    """Glob wildcards should work in rule patterns."""

    def test_wildcard_star(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="rm*"),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_command("rm").action == "deny"
        assert engine.check_command("rmdir").action == "deny"
        assert engine.check_command("ls").action == "allow"

    def test_wildcard_question_mark(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="r?"),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_command("rm").action == "deny"
        assert engine.check_command("rv").action == "deny"
        assert engine.check_command("rmv").action == "allow"

    def test_path_glob(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="deny",
                    target="path_write",
                    pattern="/etc/*",
                    reason="Cannot write to /etc",
                ),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_path_write("/etc/passwd").action == "deny"
        assert engine.check_path_write("/tmp/file").action == "allow"

    def test_bracket_pattern(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="[abc]md"),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_command("amd").action == "deny"
        assert engine.check_command("bmd").action == "deny"
        assert engine.check_command("cmd").action == "deny"
        assert engine.check_command("dmd").action == "allow"


# ---------------------------------------------------------------------------
# Path read checks
# ---------------------------------------------------------------------------


class TestPathRead:
    """Path read checks should evaluate correctly."""

    def test_deny_read_sensitive(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="deny",
                    target="path_read",
                    pattern="/secrets/*",
                    reason="Classified",
                ),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_path_read("/secrets/key.pem").action == "deny"
        assert engine.check_path_read("/public/readme.txt").action == "allow"


# ---------------------------------------------------------------------------
# Path write checks
# ---------------------------------------------------------------------------


class TestPathWrite:
    """Path write checks should evaluate correctly."""

    def test_deny_write_root(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="deny",
                    target="path_write",
                    pattern="/",
                    reason="Cannot write to root",
                ),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_path_write("/").action == "deny"
        assert engine.check_path_write("/home/user/file").action == "allow"


# ---------------------------------------------------------------------------
# Tool checks
# ---------------------------------------------------------------------------


class TestToolChecks:
    """Tool invocation checks should evaluate correctly."""

    def test_deny_tool(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="deny",
                    target="tool",
                    pattern="dangerous_*",
                    reason="Unsafe tool category",
                ),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_tool("dangerous_deploy").action == "deny"
        assert engine.check_tool("safe_deploy").action == "allow"

    def test_warn_tool(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="warn",
                    target="tool",
                    pattern="web_*",
                    reason="Tool accesses the web",
                ),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_tool("web_search")
        assert decision.action == "warn"
        assert decision.reason == "Tool accesses the web"


# ---------------------------------------------------------------------------
# Rule ordering (first match wins)
# ---------------------------------------------------------------------------


class TestRuleOrdering:
    """The first matching rule should win."""

    def test_first_match_wins(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="allow", target="command", pattern="rm", reason="OK"),
                PolicyRule(kind="deny", target="command", pattern="rm", reason="BAD"),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("rm")
        assert decision.action == "allow"
        assert decision.reason == "OK"

    def test_more_specific_first(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(
                    kind="allow",
                    target="command",
                    pattern="rm",
                    reason="rm specifically allowed",
                ),
                PolicyRule(
                    kind="deny",
                    target="command",
                    pattern="*",
                    reason="deny all",
                ),
            ]
        )
        engine = PolicyEngine(config)
        assert engine.check_command("rm").action == "allow"
        assert engine.check_command("ls").action == "deny"


# ---------------------------------------------------------------------------
# PolicyConfig.add_rule
# ---------------------------------------------------------------------------


class TestPolicyConfig:
    """PolicyConfig.add_rule should append rules."""

    def test_add_rule(self, config: PolicyConfig) -> None:
        assert len(config.rules) == 0
        rule = PolicyRule(kind="deny", target="command", pattern="rm")
        config.add_rule(rule)
        assert len(config.rules) == 1
        assert config.rules[0] is rule

    def test_default_limits(self, config: PolicyConfig) -> None:
        assert config.max_recursion_depth == 50
        assert config.max_output_bytes == 1_000_000


# ---------------------------------------------------------------------------
# PolicyRule.matches
# ---------------------------------------------------------------------------


class TestPolicyRuleMatches:
    """PolicyRule.matches should delegate to fnmatch."""

    def test_exact_match(self) -> None:
        rule = PolicyRule(kind="deny", target="command", pattern="rm")
        assert rule.matches("rm") is True
        assert rule.matches("ls") is False

    def test_wildcard_match(self) -> None:
        rule = PolicyRule(kind="deny", target="command", pattern="rm*")
        assert rule.matches("rm") is True
        assert rule.matches("rmdir") is True
        assert rule.matches("ls") is False


# ---------------------------------------------------------------------------
# PolicyDecision immutability
# ---------------------------------------------------------------------------


class TestPolicyDecisionImmutability:
    """PolicyDecision should be frozen."""

    def test_frozen(self) -> None:
        decision = PolicyDecision(action="allow", reason="ok")
        with pytest.raises(AttributeError):
            decision.action = "deny"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Default reason generation
# ---------------------------------------------------------------------------


class TestDefaultReason:
    """When a rule has no explicit reason, a generated one should be used."""

    def test_generated_reason(self) -> None:
        config = PolicyConfig(
            rules=[
                PolicyRule(kind="deny", target="command", pattern="rm"),
            ]
        )
        engine = PolicyEngine(config)
        decision = engine.check_command("rm")
        assert decision.action == "deny"
        assert "rm" in decision.reason
