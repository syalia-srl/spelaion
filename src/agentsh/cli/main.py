"""CLI for agentsh: parse, plan, run shell scripts."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from agentsh.api.engine import ShellEngine


def main(argv: list[str] | None = None) -> int:  # noqa: C901
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="agentsh",
        description="Virtual Bash parser and agent executor",
    )
    parser.add_argument(
        "--seed-fs",
        type=str,
        help="Directory to pre-populate VFS from",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # parse command
    parse_parser = subparsers.add_parser("parse", help="Parse a shell script")
    parse_parser.add_argument("file", help="Script file to parse (or - for stdin)")
    parse_parser.add_argument("--json", action="store_true", help="JSON output")

    # plan command
    plan_parser = subparsers.add_parser("plan", help="Plan script execution")
    plan_parser.add_argument("file", help="Script file to plan (or - for stdin)")

    # run command
    run_parser = subparsers.add_parser("run", help="Execute a shell script")
    run_parser.add_argument("file", help="Script file to run (or - for stdin)")

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    # Read script
    script = _read_script(args.file)
    if script is None:
        print(f"Error: cannot read {args.file}", file=sys.stderr)
        return 1

    # Seed VFS from directory if specified
    initial_files: dict[str, str | bytes] | None = None
    if args.seed_fs:
        initial_files = _seed_from_dir(args.seed_fs)

    engine = ShellEngine(initial_files=initial_files)

    if args.command == "parse":
        result = engine.parse(script)
        if hasattr(args, "json") and args.json:
            from agentsh.langchain_tools.parse_tool import ast_to_dict

            output = {
                "has_errors": result.has_errors,
                "diagnostics": [str(d) for d in result.diagnostics],
                "ast": ast_to_dict(result.ast) if result.ast else None,
            }
            print(json.dumps(output, indent=2))
        else:
            if result.has_errors:
                for d in result.diagnostics:
                    print(f"  {d}", file=sys.stderr)
                return 1
            print(f"Parsed successfully: {type(result.ast).__name__}")
            if result.diagnostics:
                for d in result.diagnostics:
                    print(f"  {d}")
        return 0

    elif args.command == "plan":
        plan_output = engine.plan(script)
        if plan_output.has_errors:
            for d in plan_output.diagnostics:
                print(f"  {d}", file=sys.stderr)
            return 1

        plan_data = {
            "steps": [
                {
                    "command": s.command,
                    "resolution": s.resolution,
                    "args": s.args,
                    "effects": [
                        {"kind": e.kind, "description": e.description}
                        for e in s.effects
                    ],
                }
                for s in plan_output.plan.steps
            ],
            "warnings": plan_output.plan.warnings,
        }
        print(json.dumps(plan_data, indent=2))
        return 0

    elif args.command == "run":
        run_output = engine.run(script)
        if run_output.stdout:
            sys.stdout.write(run_output.stdout)
        if run_output.stderr:
            sys.stderr.write(run_output.stderr)
        return run_output.result.exit_code

    return 1


def _read_script(file_arg: str) -> str | None:
    """Read script from file or stdin."""
    if file_arg == "-":
        return sys.stdin.read()
    try:
        return Path(file_arg).read_text()
    except (OSError, FileNotFoundError):
        return None


def _seed_from_dir(dir_path: str) -> dict[str, str | bytes]:
    """Recursively read a directory into VFS initial files."""
    files: dict[str, str | bytes] = {}
    root = Path(dir_path)
    if not root.is_dir():
        return files

    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root)
            vfs_path = "/" + str(rel)
            with contextlib.suppress(OSError):
                files[vfs_path] = path.read_bytes()

    return files


if __name__ == "__main__":
    sys.exit(main())
