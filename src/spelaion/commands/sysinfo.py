"""System info commands and virtual no-ops.

arch, hostname, free, uptime, nproc, groups, logname, users, w, who,
last, printenv, time, timeout, nice, renice, chrt, ionice, nohup,
flock, sync, fsync, usleep.
"""

from __future__ import annotations

import datetime
import time
from typing import TYPE_CHECKING

from spelaion.commands._registry import command
from spelaion.commands.sysutil import duration
from spelaion.runtime.result import CommandResult
from spelaion.runtime.state import TimeoutExpired

if TYPE_CHECKING:
    from spelaion.exec.redirs import IOContext
    from spelaion.runtime.state import ShellState
    from spelaion.vfs.base import Filesystem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_sub(argv: list[str], io: IOContext) -> CommandResult:
    """Run a sub-command via the executor, returning its result."""
    from spelaion.exec.redirs import IOContext as _IOCtx

    if io.executor is None:
        io.stderr.write(f"{argv[0]}: cannot execute sub-command without executor\n")
        return CommandResult(exit_code=1)
    sub_io = _IOCtx(executor=io.executor)
    result = io.executor.execute_argv(argv, sub_io)
    out = sub_io.stdout.getvalue()
    if out:
        io.stdout.write(out)
    err = sub_io.stderr.getvalue()
    if err:
        io.stderr.write(err)
    return result


# ---------------------------------------------------------------------------
# System info commands (return virtual/fake data)
# ---------------------------------------------------------------------------


@command("arch")
def cmd_arch(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    arch = state.get_var("SPELAION_ARCH") or "x86_64"
    io.stdout.write(arch + "\n")
    return CommandResult(exit_code=0)


@command("hostname")
def cmd_hostname(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    name = state.get_var("HOSTNAME") or "spelaion"
    # -f flag: in a virtual shell, just return the same name
    io.stdout.write(name + "\n")
    return CommandResult(exit_code=0)


@command("free")
def cmd_free(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    human = "-h" in args
    mega = "-m" in args

    if human:
        total, used, free_, shared, buff, avail = (
            "8.0Gi",
            "2.0Gi",
            "6.0Gi",
            "0.0Gi",
            "0.5Gi",
            "5.5Gi",
        )
        stotal, sused, sfree = "2.0Gi", "0.0Gi", "2.0Gi"
    elif mega:
        total, used, free_, shared, buff, avail = (
            "8192",
            "2048",
            "6144",
            "0",
            "512",
            "5632",
        )
        stotal, sused, sfree = "2048", "0", "2048"
    else:
        # Default: kibibytes
        total, used, free_, shared, buff, avail = (
            "8388608",
            "2097152",
            "6291456",
            "0",
            "524288",
            "5767168",
        )
        stotal, sused, sfree = "2097152", "0", "2097152"

    header = f"{'':15s} {'total':>10s} {'used':>10s} {'free':>10s}"
    header += f" {'shared':>10s} {'buff/cache':>10s} {'available':>10s}"
    mem = f"{'Mem:':15s} {total:>10s} {used:>10s} {free_:>10s}"
    mem += f" {shared:>10s} {buff:>10s} {avail:>10s}"
    swap = f"{'Swap:':15s} {stotal:>10s} {sused:>10s} {sfree:>10s}"

    io.stdout.write(header + "\n" + mem + "\n" + swap + "\n")
    return CommandResult(exit_code=0)


@command("uptime")
def cmd_uptime(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    io.stdout.write("up 0 min, 1 user, load average: 0.00, 0.00, 0.00\n")
    return CommandResult(exit_code=0)


@command("nproc")
def cmd_nproc(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    n = state.get_var("SPELAION_NPROC") or "4"
    io.stdout.write(n + "\n")
    return CommandResult(exit_code=0)


@command("groups")
def cmd_groups(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    user = args[0] if args else (state.get_var("USER") or "root")
    io.stdout.write(user + "\n")
    return CommandResult(exit_code=0)


@command("logname")
def cmd_logname(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    io.stdout.write(user + "\n")
    return CommandResult(exit_code=0)


@command("users")
def cmd_users(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    io.stdout.write(user + "\n")
    return CommandResult(exit_code=0)


@command("w")
def cmd_w(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    now = datetime.datetime.now().strftime("%H:%M:%S")
    io.stdout.write(f" {now} up 0 min, 1 user, load average: 0.00, 0.00, 0.00\n")
    hdr = "USER     TTY      FROM             LOGIN@   IDLE   JCPU   PCPU WHAT"
    io.stdout.write(hdr + "\n")
    line = f"{user:8s} pts/0    -                {now}   0.00s  0.00s  0.00s -"
    io.stdout.write(line + "\n")
    return CommandResult(exit_code=0)


@command("who")
def cmd_who(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    user = state.get_var("USER") or "root"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    io.stdout.write(f"{user} pts/0 {now}\n")
    return CommandResult(exit_code=0)


@command("last")
def cmd_last(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    count = 10
    i = 0
    while i < len(args):
        if args[i] == "-n" and i + 1 < len(args):
            i += 1
            try:
                count = int(args[i])
            except ValueError:
                io.stderr.write(f"last: invalid count '{args[i]}'\n")
                return CommandResult(exit_code=1)
        i += 1

    user = state.get_var("USER") or "root"
    now = datetime.datetime.now().strftime("%a %b %d %H:%M")
    for _ in range(count):
        io.stdout.write(f"{user:8s} pts/0        {now}   still logged in\n")
    return CommandResult(exit_code=0)


@command("printenv")
def cmd_printenv(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    if args:
        exit_code = 0
        for name in args:
            val = state.get_var(name)
            if val is not None:
                io.stdout.write(val + "\n")
            else:
                exit_code = 1
        return CommandResult(exit_code=exit_code)

    # No args: print all exported env
    for name, value in sorted(state.exported_env.items()):
        io.stdout.write(f"{name}={value}\n")
    return CommandResult(exit_code=0)


@command("time")
def cmd_time(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("time: missing command\n")
        return CommandResult(exit_code=1)
    result = _run_sub(args, io)
    io.stderr.write("\nreal\t0m0.000s\nuser\t0m0.000s\nsys\t0m0.000s\n")
    return result


@command("timeout")
def cmd_timeout(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    """Stop COMMAND after DURATION with status 124.

    The shell checks the deadline before each command it runs and inside
    ``sleep``; one long command (a python guest, a big grep) runs on until
    the call's own deadline.
    """
    from spelaion.exec.redirs import IOContext as _IOCtx

    i = 0
    while i < len(args) and args[i].startswith("-") and args[i] != "-":
        if args[i] in ("-s", "-k", "--signal", "--kill-after"):
            i += 1  # the option's value
        i += 1
    limit = duration(args[i]) if i < len(args) else None
    if limit is None:
        io.stderr.write(
            f"timeout: invalid time interval '{args[i]}'\n"
            if i < len(args)
            else "timeout: missing operand\n"
        )
        return CommandResult(exit_code=125)
    cmd_argv = args[i + 1 :]
    if not cmd_argv:
        io.stderr.write("timeout: missing operand\n")
        return CommandResult(exit_code=125)
    if io.executor is None:
        io.stderr.write("timeout: cannot execute sub-command without executor\n")
        return CommandResult(exit_code=125)

    outer = state.deadline
    mine = time.monotonic() + min(limit, 365 * 86400)
    state.deadline = mine if outer is None else min(outer, mine)
    sub_io = _IOCtx(stdin=io.stdin, executor=io.executor)
    try:
        result = io.executor.execute_argv(cmd_argv, sub_io)
    except TimeoutExpired:
        if outer is not None and outer < mine:
            raise  # an enclosing timeout's, which ends first
        result = CommandResult(exit_code=124)
    finally:
        state.deadline = outer
        io.stdout.write(sub_io.stdout.getvalue())
        io.stderr.write(sub_io.stderr.getvalue())
    return result


# ---------------------------------------------------------------------------
# Virtual no-ops
# ---------------------------------------------------------------------------


@command("nice")
def cmd_nice(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    # Skip -n N if present, then run COMMAND...
    i = 0
    if i < len(args) and args[i] == "-n" and i + 1 < len(args):
        i += 2
    cmd_argv = args[i:]
    if not cmd_argv:
        # No command: just print 0 (current niceness)
        io.stdout.write("0\n")
        return CommandResult(exit_code=0)
    return _run_sub(cmd_argv, io)


@command("renice")
def cmd_renice(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("chrt")
def cmd_chrt(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("ionice")
def cmd_ionice(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("nohup")
def cmd_nohup(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    if not args:
        io.stderr.write("nohup: missing command\n")
        return CommandResult(exit_code=1)
    return _run_sub(args, io)


@command("flock")
def cmd_flock(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    # Skip optional -x/-s, FILE, then run COMMAND...
    i = 0
    while i < len(args) and args[i].startswith("-"):
        i += 1
    # Next arg is FILE (skip it)
    if i < len(args):
        i += 1
    cmd_argv = args[i:]
    if not cmd_argv:
        # No command: just return success (flock can be used without command)
        return CommandResult(exit_code=0)
    return _run_sub(cmd_argv, io)


@command("sync")
def cmd_sync(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("fsync")
def cmd_fsync(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("usleep")
def cmd_usleep(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("clear")
def cmd_clear(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    return CommandResult(exit_code=0)


@command("kill")
def cmd_kill(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    # Virtual: no processes to kill. Accept -SIGNAL and PID args silently.
    return CommandResult(exit_code=0)


@command("getopt")
def cmd_getopt(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    """Minimal getopt: parse -o OPTSTRING -- ARGS."""
    optstring = ""
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-o" and i + 1 < len(args):
            i += 1
            optstring = args[i]
        elif args[i] == "--":
            rest = list(args[i + 1 :])
            break
        else:
            rest.append(args[i])
        i += 1

    out_parts: list[str] = []
    positional: list[str] = []
    j = 0
    while j < len(rest):
        a = rest[j]
        if a.startswith("-") and len(a) > 1 and a[1] != "-":
            for ch in a[1:]:
                idx = optstring.find(ch)
                if idx >= 0:
                    if idx + 1 < len(optstring) and optstring[idx + 1] == ":":
                        j += 1
                        val = rest[j] if j < len(rest) else ""
                        out_parts.append(f"-{ch}")
                        out_parts.append(f"'{val}'")
                    else:
                        out_parts.append(f"-{ch}")
                else:
                    io.stderr.write(f"getopt: unrecognized option '-{ch}'\n")
                    return CommandResult(exit_code=1)
        elif a == "--":
            positional.extend(rest[j + 1 :])
            break
        else:
            positional.append(a)
        j += 1

    out_parts.append("--")
    for p in positional:
        out_parts.append(f"'{p}'")
    io.stdout.write(" ".join(out_parts) + "\n")
    return CommandResult(exit_code=0)


@command("tty")
def cmd_tty(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    io.stdout.write("not a tty\n")
    return CommandResult(exit_code=1)


@command("ps")
def cmd_ps(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    io.stdout.write("  PID TTY          TIME CMD\n")
    io.stdout.write("    1 pts/0    00:00:00 spelaion\n")
    return CommandResult(exit_code=0)


@command("top")
def cmd_top(
    args: list[str], state: ShellState, vfs: Filesystem, io: IOContext
) -> CommandResult:
    # Non-interactive: print one snapshot and exit
    io.stdout.write("top - virtual (spelaion)\n")
    io.stdout.write("Tasks:   1 total,   1 running\n")
    io.stdout.write("  PID USER      PR  NI  VIRT   RES COMMAND\n")
    io.stdout.write("    1 root      20   0     0     0 spelaion\n")
    return CommandResult(exit_code=0)
