"""LangChain tool: plan a shell script and return effects."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    pass


class AgentShPlanTool(BaseTool):
    """Plan a shell script execution and return expected effects."""

    name: str = "agentsh_plan"
    description: str = (
        "Analyze a shell script and return its planned effects without executing it. "
        "Shows what commands would run, what files would be read/written, and any "
        "policy violations."
    )
    engine: Any = None  # ShellEngine

    def _run(self, script: str) -> str:
        """Plan the script and return effects as JSON."""
        result = self.engine.plan(script)

        output: dict[str, Any] = {
            "has_errors": result.has_errors,
            "diagnostics": [str(d) for d in result.diagnostics],
            "steps": [
                {
                    "command": step.command,
                    "resolution": step.resolution,
                    "args": step.args,
                    "effects": [
                        {
                            "kind": e.kind,
                            "description": e.description,
                            "target": e.target,
                        }
                        for e in step.effects
                    ],
                }
                for step in result.plan.steps
            ],
            "effects": [
                {
                    "kind": e.kind,
                    "description": e.description,
                    "target": e.target,
                }
                for e in result.plan.effects
            ],
            "warnings": result.plan.warnings,
        }

        return json.dumps(output, indent=2)
