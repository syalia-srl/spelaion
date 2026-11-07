"""Policy decision types and the policy evaluation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agentsh.policy.rules import PolicyConfig


@dataclass(frozen=True)
class PolicyDecision:
    """The outcome of a policy check.

    Attributes:
        action: Whether the operation is allowed, denied, or warned.
        reason: Human-readable explanation for the decision.
        rule_pattern: The glob pattern of the rule that matched, or empty
            string if the default policy was applied.
    """

    action: Literal["allow", "deny", "warn"]
    reason: str
    rule_pattern: str = ""


class PolicyEngine:
    """Evaluates policy rules against operations.

    Rules are evaluated in order; the first matching rule determines the
    decision.  If no rule matches, the default decision is ``allow``.
    """

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _check(
        self,
        target: str,
        value: str,
    ) -> PolicyDecision:
        """Evaluate rules for the given *target* category and *value*."""
        for rule in self.config.rules:
            if rule.target == target and rule.matches(value):
                return PolicyDecision(
                    action=rule.kind,
                    reason=rule.reason or f"Matched rule: {rule.pattern}",
                    rule_pattern=rule.pattern,
                )
        return PolicyDecision(
            action="allow",
            reason="No matching rule (default allow)",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_command(self, command_name: str) -> PolicyDecision:
        """Check if a command is allowed to execute."""
        return self._check("command", command_name)

    def check_path_read(self, path: str) -> PolicyDecision:
        """Check if reading a path is allowed."""
        return self._check("path_read", path)

    def check_path_write(self, path: str) -> PolicyDecision:
        """Check if writing to a path is allowed."""
        return self._check("path_write", path)

    def check_tool(self, tool_name: str) -> PolicyDecision:
        """Check if a tool invocation is allowed."""
        return self._check("tool", tool_name)
