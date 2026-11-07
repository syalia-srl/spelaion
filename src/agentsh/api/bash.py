"""just-bash compatible API — ``Bash`` class with ``run()`` method.

Mirrors the API from Vercel's just-bash TypeScript library, adapted
for Python.  The filesystem is shared across ``run()`` calls; shell
state (variables, functions, aliases) persists between calls.

Usage::

    from agentsh import Bash

    bash = Bash()
    result = bash.run('echo "Hello" > greeting.txt')
    result = bash.run("cat greeting.txt")
    print(result.stdout)  # "Hello\\n"
    print(result.exit_code)  # 0
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO

from agentsh.exec.executor import Executor
from agentsh.exec.redirs import IOContext
from agentsh.parser.frontend import parse_script
from agentsh.parser.normalize import normalize
from agentsh.policy.decisions import PolicyEngine
from agentsh.policy.rules import PolicyConfig
from agentsh.runtime.result import CommandResult
from agentsh.runtime.state import ShellState
from agentsh.tools.registry import ToolRegistry
from agentsh.vfs.filesystem import VirtualFilesystem

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    """Result of a ``Bash.run()`` call."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------


@dataclass
class Limits:
    """Configurable safety limits."""

    max_call_depth: int = 100
    max_loop_iterations: int = 10_000


# ---------------------------------------------------------------------------
# Custom command definition
# ---------------------------------------------------------------------------


@dataclass
class CommandContext:
    """Context passed to custom command handlers."""

    args: list[str]
    stdin: str
    cwd: str
    env: dict[str, str]
    fs: VirtualFilesystem


CommandHandler = Callable[
    [list[str], "CommandContext"],
    "RunResult",
]


@dataclass
class CustomCommand:
    """A user-defined custom command."""

    name: str
    handler: CommandHandler


def define_command(
    name: str,
    handler: CommandHandler,
) -> CustomCommand:
    """Define a custom command for use with :class:`Bash`.

    Example::

        hello = define_command(
            "hello",
            lambda args, ctx: RunResult(
                stdout=f"Hello, {args[0] if args else 'world'}!\\n"
            ),
        )

        bash = Bash(custom_commands=[hello])
        result = bash.run("hello Alice")
    """
    return CustomCommand(name=name, handler=handler)


# ---------------------------------------------------------------------------
# Bash class
# ---------------------------------------------------------------------------


class Bash:
    """A virtual bash environment with an in-memory filesystem.

    Compatible with the `just-bash <https://github.com/vercel-labs/just-bash>`_
    API from Vercel.

    Parameters:
        files: Initial filesystem contents (path -> content).
        env: Initial environment variables.
        cwd: Initial working directory (default ``/``).
        limits: Safety limits for recursion and loops.
        custom_commands: List of :func:`define_command` results.
        policy: Optional policy configuration for allow/deny rules.
    """

    def __init__(
        self,
        *,
        files: dict[str, str | bytes] | None = None,
        env: dict[str, str] | None = None,
        cwd: str = "/",
        limits: Limits | None = None,
        custom_commands: list[CustomCommand] | None = None,
        policy: PolicyConfig | None = None,
    ) -> None:
        self.vfs = VirtualFilesystem(initial_files=files)
        self.tools = ToolRegistry()
        self.state = ShellState()
        self.state.cwd = cwd

        cfg_limits = limits or Limits()
        policy_cfg = policy or PolicyConfig(
            max_recursion_depth=cfg_limits.max_call_depth,
        )
        self.policy_engine = PolicyEngine(config=policy_cfg)
        self._limits = cfg_limits

        # Set environment
        if env:
            for name, value in env.items():
                self.state.set_var(name, value)
                self.state.export_var(name, value)

        # Defaults
        if not self.state.get_var("HOME"):
            self.state.set_var("HOME", "/home/user")
        if not self.state.get_var("PWD"):
            self.state.set_var("PWD", cwd)

        # Register custom commands as agent tools
        if custom_commands:
            for cmd in custom_commands:
                self.tools.register(
                    cmd.name,
                    _CustomCommandTool(cmd, self),
                )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        script: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        stdin: str | None = None,
        args: list[str] | None = None,
    ) -> RunResult:
        """Run a bash script and return the result.

        The filesystem is **shared** across calls — files written in
        one ``run()`` are visible in the next.

        Parameters:
            script: The bash script to run.
            env: Additional environment variables for this run.
            cwd: Override working directory for this run.
            stdin: Text to provide on standard input.
            args: Positional parameters (``$1``, ``$2``, ...).
        """
        return self._do_run(
            script,
            env=env,
            cwd=cwd,
            stdin=stdin,
            args=args,
        )

    # ------------------------------------------------------------------
    # Filesystem access
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> str:
        """Read a file from the virtual filesystem."""
        abs_path = self.vfs.resolve(path, self.state.cwd)
        return self.vfs.read(abs_path).decode("utf-8", errors="replace")

    def write_file(self, path: str, content: str | bytes) -> None:
        """Write a file to the virtual filesystem."""
        abs_path = self.vfs.resolve(path, self.state.cwd)
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.vfs.write(abs_path, data)

    def write_files(self, files: dict[str, str | bytes]) -> None:
        """Write multiple files to the virtual filesystem."""
        for path, content in files.items():
            self.write_file(path, content)

    def file_exists(self, path: str) -> bool:
        """Check if a file exists in the virtual filesystem."""
        abs_path = self.vfs.resolve(path, self.state.cwd)
        return self.vfs.exists(abs_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _do_run(
        self,
        script: str,
        *,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        stdin: str | None = None,
        args: list[str] | None = None,
    ) -> RunResult:
        # Save state for per-run overrides
        saved_params = self.state.positional_params

        if cwd is not None:
            self.state.cwd = cwd
            self.state.set_var("PWD", cwd)
        if env is not None:
            for name, value in env.items():
                self.state.set_var(name, value)
                self.state.export_var(name, value)
        if args is not None:
            self.state.positional_params = args

        # Parse
        parse_result = parse_script(script)
        if parse_result.has_errors:
            if args is not None:
                self.state.positional_params = saved_params
            return RunResult(
                stderr="agentsh: syntax error\n",
                exit_code=2,
            )

        program, _diags = normalize(parse_result.root_node, script)

        # Build executor
        executor = Executor(
            state=self.state,
            vfs=self.vfs,
            tools=self.tools,
            policy=self.policy_engine,
        )

        io = IOContext()
        if stdin is not None:
            io.stdin = StringIO(stdin)

        try:
            result = executor.execute_node(program, io)
        except SystemExit as e:
            result = CommandResult(
                exit_code=e.code if isinstance(e.code, int) else 0,
            )

        stdout = io.stdout.getvalue()
        stderr = io.stderr.getvalue()

        # Restore per-run overrides
        if args is not None:
            self.state.positional_params = saved_params

        return RunResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=result.exit_code,
        )


# ---------------------------------------------------------------------------
# Custom command tool adapter
# ---------------------------------------------------------------------------


class _CustomCommandTool:
    """Adapts a :class:`CustomCommand` to the :class:`AgentTool` protocol."""

    def __init__(self, cmd: CustomCommand, bash: Bash) -> None:
        self._cmd = cmd
        self._bash = bash

    @property
    def name(self) -> str:
        return self._cmd.name

    def invoke(
        self,
        args: list[str],
        stdin: str | None = None,
    ) -> CommandResult:
        ctx = CommandContext(
            args=args,
            stdin=stdin or "",
            cwd=self._bash.state.cwd,
            env=dict(self._bash.state.exported_env),
            fs=self._bash.vfs,
        )
        result = self._cmd.handler(args, ctx)
        return CommandResult(
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )
