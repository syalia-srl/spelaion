"""Run in the guest as ``python -m _boot CWD -- ARGS...``.

WASI gives the guest no working directory of its own, so this one changes
to *CWD* and then behaves like the ``python`` command line for ``-c CODE``,
``-m MOD``, ``SCRIPT`` and ``-``, setting ``sys.argv`` as CPython would.
"""

import os
import runpy
import sys
import types

_IGNORED = {"-u", "-B", "-E", "-s", "-S", "-I", "-q", "-O", "-OO"}

_USAGE = "usage: python [-c cmd | -m mod | file | -] [arg] ..."


def _usage(message: str) -> None:
    print(f"{message}\n{_USAGE}", file=sys.stderr)
    sys.exit(2)


def _fresh_main() -> dict[str, object]:
    main = types.ModuleType("__main__")
    main.__dict__["__builtins__"] = __builtins__
    sys.modules["__main__"] = main
    return main.__dict__


def _exec(source: str | bytes, filename: str, file: str | None = None) -> None:
    namespace = _fresh_main()
    if file is not None:
        namespace["__file__"] = file
    exec(compile(source, filename, "exec"), namespace)


def _run(args: list[str]) -> None:
    while args and args[0] in _IGNORED:
        args = args[1:]
    if args and args[0] in ("-V", "--version"):
        print(f"Python {sys.version.split()[0]}")
        return
    if args and args[0] == "-c":
        if len(args) < 2:
            _usage("Argument expected for the -c option")
        sys.argv = ["-c", *args[2:]]
        sys.path[0] = ""
        _exec(args[1], "<string>")
    elif args and args[0] == "-m":
        if len(args) < 2:
            _usage("Argument expected for the -m option")
        sys.argv = [args[1], *args[2:]]
        sys.path[0] = os.getcwd()
        _fresh_main()
        # What `python -m` itself calls: it sets sys.argv[0] and reports a
        # missing module as CPython does.
        runpy._run_module_as_main(args[1])  # type: ignore[attr-defined]
    elif not args or args[0] == "-":
        sys.argv = ["-", *args[1:]] if args else [""]
        sys.path[0] = ""
        _exec(sys.stdin.read(), "<stdin>")
    elif args[0].startswith("-"):
        _usage(f"Unknown option: {args[0]}")
    else:
        script = args[0]
        try:
            with open(script, "rb") as f:
                source = f.read()
        except OSError as e:
            path = os.path.abspath(script)
            print(
                f"python: can't open file {path!r}: [Errno {e.errno}] {e.strerror}",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.argv = list(args)
        sys.path[0] = os.path.dirname(os.path.abspath(script))
        _exec(source, script, script)


def main() -> None:
    cwd, sep, args = sys.argv[1], sys.argv[2], sys.argv[3:]
    assert sep == "--"
    os.chdir(cwd)
    # WASI leaves it empty; runpy names it in "No module named" errors.
    sys.executable = sys.executable or "python"
    try:
        _run(args)
    except SystemExit:
        raise
    except BaseException as e:
        # Drop this file's frames, as CPython shows none of its own.
        tb = e.__traceback__
        ours = (globals(), runpy.__dict__)
        while tb is not None and any(tb.tb_frame.f_globals is g for g in ours):
            tb = tb.tb_next
        sys.excepthook(type(e), e.with_traceback(tb), tb)
        sys.exit(1)


if __name__ == "__main__":
    main()
