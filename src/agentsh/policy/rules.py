"""Policy rule and configuration types."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class PolicyRule:
    """A single policy rule that matches against a target by glob pattern.

    Attributes:
        kind: The action to take when the rule matches.
        target: What category of operation this rule applies to.
        pattern: A glob pattern matched via :func:`fnmatch.fnmatch`.
        reason: Human-readable explanation for the rule.
    """

    kind: Literal["allow", "deny", "warn"]
    target: Literal["command", "path_read", "path_write", "tool"]
    pattern: str
    reason: str = ""

    def matches(self, value: str) -> bool:
        """Return True if *value* matches this rule's glob pattern."""
        return fnmatch.fnmatch(value, self.pattern)


@dataclass
class PolicyConfig:
    """Ordered collection of policy rules plus execution limits.

    Rules are evaluated in insertion order; the first matching rule wins.

    Attributes:
        rules: Ordered list of policy rules.
        max_recursion_depth: Maximum recursion depth for function calls.
        max_output_bytes: Maximum bytes of captured stdout/stderr.
    """

    rules: list[PolicyRule] = field(default_factory=lambda: [])
    max_recursion_depth: int = 50
    max_output_bytes: int = 1_000_000  # 1 MB

    def add_rule(self, rule: PolicyRule) -> None:
        """Append a rule to the end of the rule list."""
        self.rules.append(rule)
