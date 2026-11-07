"""LangChain tool: run a shell script in the virtual environment."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class RunInput(BaseModel):
    """Input schema for the run tool."""

    script: str = Field(description="The shell script to execute")


class AgentShRunTool(StructuredTool):
    """Execute a shell script in a virtual environment."""

    name: str = "agentsh_run"
    description: str = (
        "Execute a shell script in a virtual shell environment. "
        "The environment has a virtual filesystem and supports builtins like "
        "echo, cd, pwd, export, test, and registered agent tools. "
        "Returns stdout, stderr, and exit code."
    )
    args_schema: type[BaseModel] = RunInput
    engine: Any = None  # ShellEngine

    def _run(self, script: str) -> str:  # type: ignore[override]
        """Execute the script and return results as JSON."""
        result = self.engine.run(script)

        output: dict[str, Any] = {
            "exit_code": result.result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "diagnostics": [str(d) for d in result.diagnostics],
        }

        return json.dumps(output, indent=2)
