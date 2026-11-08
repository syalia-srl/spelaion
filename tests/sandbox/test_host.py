"""Sandbox: host commands, their ctx, attachments and show."""

from __future__ import annotations

import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import HostContext, Limits, Mount, Result, Sandbox
from spelaion._host import MAX_IMAGE

PNG_FIXTURE = Path(__file__).parent / "data" / "pixel.png"
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 16
WEBP = b"RIFF\x10\0\0\0WEBPVP8 " + b"\0" * 8


@pytest.fixture
def rw(tmp_path: Path) -> Path:
    path = tmp_path / "rw"
    path.mkdir()
    return path


@pytest.fixture
def sb(rw: Path) -> Iterator[Sandbox]:
    with Sandbox([Mount("/scratch", rw)], cwd="/scratch") as s:
        yield s


# --- From the brief ---------------------------------------------------------


def test_host_in_pipe(sb: Sandbox) -> None:
    @sb.command("upper")
    def upper(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=ctx.stdin.upper())

    assert sb.bash("echo hi | upper | cat").stdout == "HI\n"


def test_host_sees_real_path(sb: Sandbox, rw: Path) -> None:
    seen: list[Path] = []

    @sb.command("probe")
    def probe(ctx: HostContext, args: list[str]) -> Result:
        seen.append(ctx.path(args[0]))
        return Result()

    sb.bash("cd /scratch && probe a.txt")
    assert seen == [rw.resolve() / "a.txt"]


def test_host_refuses_escape(sb: Sandbox) -> None:
    @sb.command("probe")
    def probe(ctx: HostContext, args: list[str]) -> Result:
        ctx.path(args[0])
        return Result()

    r = sb.bash("probe /etc/passwd")
    assert r.exit_code == 1 and "probe:" in r.stderr
    assert r.stderr == "probe: /etc/passwd: No such file or directory\n"


def test_host_exception_is_a_result(sb: Sandbox) -> None:
    @sb.command("boom")
    def boom(ctx: HostContext, args: list[str]) -> Result:
        raise RuntimeError("bad input")

    r = sb.bash("boom; echo after")
    assert "boom: bad input" in r.stderr and r.stdout == "after\n"
    assert "Traceback" not in r.stderr


def test_show_png(sb: Sandbox, rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")
    r = sb.bash("show /scratch/v.png")
    assert r.exit_code == 0
    assert r.attachments[0].mime == "image/png"
    assert r.attachments[0].data == PNG_FIXTURE.read_bytes()
    assert r.attachments[0].name == "/scratch/v.png"


def test_show_refuses_text(sb: Sandbox) -> None:
    sb.write("/scratch/t.txt", "x")
    r = sb.bash("show /scratch/t.txt")
    assert r.exit_code == 1 and not r.attachments
    assert r.stderr == "show: /scratch/t.txt: not a PNG, JPEG or WebP image\n"


def test_host_attach(sb: Sandbox) -> None:
    @sb.command("look")
    def look(ctx: HostContext, args: list[str]) -> Result:
        ctx.attach(PNG_FIXTURE.read_bytes(), "image/png", "look")
        return Result(stdout="rendered\n")

    r = sb.bash("look")
    assert r.stdout == "rendered\n" and len(r.attachments) == 1
    assert r.attachments[0].name == "look"


# --- The decorator ----------------------------------------------------------


def test_bare_decorator_names_from_function(sb: Sandbox) -> None:
    @sb.command
    def oikos_check(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=f"checked {' '.join(args)}\n")

    assert sb.bash("oikos-check a b").stdout == "checked a b\n"
    # The function is returned unchanged, callable on its own.
    assert oikos_check(None, ["x"]).stdout == "checked x\n"  # type: ignore[arg-type]


def test_named_decorator_returns_the_function(sb: Sandbox) -> None:
    def oikos(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=f"{args[0]}\n")

    assert sb.command("oikos")(oikos) is oikos
    assert sb.bash("oikos apply").stdout == "apply\n"


def test_same_name_twice_refused(sb: Sandbox) -> None:
    sb.command("dup")(lambda ctx, args: Result())
    with pytest.raises(ValueError, match="dup"):
        sb.command("dup")(lambda ctx, args: Result())
    with pytest.raises(ValueError, match="show"):
        sb.command("show")(lambda ctx, args: Result())


@pytest.mark.parametrize("name", ["", "-x", "a b", "a/b", "a;b", "$x", "é"])
def test_bad_names_refused(sb: Sandbox, name: str) -> None:
    with pytest.raises(ValueError, match="command name"):
        sb.command(name)


def test_builtin_names_refused(sb: Sandbox) -> None:
    with pytest.raises(ValueError, match="builtin"):
        sb.command("cat")


@pytest.mark.parametrize("name", ["a", "a.b", "a_b", "a-b", "_a", "x9"])
def test_good_names_accepted(sb: Sandbox, name: str) -> None:
    sb.command(name)(lambda ctx, args: Result(stdout="ok\n"))
    assert sb.bash(name).stdout == "ok\n"


# --- Registration and the child ---------------------------------------------


def test_registered_before_and_after_a_call(sb: Sandbox) -> None:
    sb.command("one")(lambda ctx, args: Result(stdout="1\n"))
    assert sb.bash("one").stdout == "1\n"
    sb.command("two")(lambda ctx, args: Result(stdout="2\n"))
    assert sb.bash("one; two").stdout == "1\n2\n"


def test_restarted_child_has_every_command(sb: Sandbox) -> None:
    sb.command("one")(lambda ctx, args: Result(stdout="1\n"))
    sb.bash("true")
    sb.command("two")(lambda ctx, args: Result(stdout="2\n"))
    sb._restart()  # pyright: ignore[reportPrivateUsage]
    assert sb.bash("one; two").stdout == "1\n2\n"


def test_host_sees_live_cwd_and_env(sb: Sandbox, rw: Path) -> None:
    (rw / "sub").mkdir()
    seen: list[tuple[str, dict[str, str], Path]] = []

    @sb.command
    def probe(ctx: HostContext, args: list[str]) -> Result:
        seen.append((ctx.cwd, ctx.env, ctx.path("f")))
        return Result()

    sb.bash("cd /scratch/sub && export X=1 && probe")
    sb.bash("probe")
    assert seen == [
        ("/scratch/sub", {"X": "1"}, rw.resolve() / "sub" / "f"),
        ("/scratch", {}, rw.resolve() / "f"),
    ]


def test_host_in_subshell_sees_its_cwd(sb: Sandbox, rw: Path) -> None:
    (rw / "sub").mkdir()

    @sb.command
    def where(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=ctx.cwd + "\n")

    assert sb.bash("(cd sub && where); where").stdout == "/scratch/sub\n/scratch\n"


def test_args_stdin_and_exit_code(sb: Sandbox) -> None:
    @sb.command
    def count(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=f"{len(ctx.stdin)} {args}\n", stderr="e\n", exit_code=4)

    r = sb.bash("printf abc | count 'a b' c; echo rc=$?")
    assert r.stdout == "3 ['a b', 'c']\nrc=4\n" and r.stderr == "e\n"


def test_remaining_s(rw: Path) -> None:
    with Sandbox([Mount("/scratch", rw)], limits=Limits(timeout_s=5)) as s:
        seen: list[float] = []

        @s.command
        def clock(ctx: HostContext, args: list[str]) -> Result:
            seen.append(ctx.remaining_s)
            time.sleep(0.5)
            return Result()

        s.bash("clock; clock")
    assert 4 < seen[0] <= 5 and seen[1] <= seen[0] - 0.5


# --- Errors -----------------------------------------------------------------


def test_read_only_path_refused(rw: Path, tmp_path: Path) -> None:
    ro = tmp_path / "ro"
    ro.mkdir()
    with Sandbox([Mount("/scratch", rw), Mount("/ro", ro, readonly=True)]) as s:

        @s.command
        def put(ctx: HostContext, args: list[str]) -> Result:
            ctx.path(args[0], write=True).write_text("x")
            return Result()

        r = s.bash("put /ro/a")
        assert (r.exit_code, r.stderr) == (1, "put: /ro/a: Read-only file system\n")
        assert s.bash("put /scratch/a").exit_code == 0
    assert not (ro / "a").exists() and (rw / "a").read_text() == "x"


def test_os_error_never_shows_a_host_path(sb: Sandbox, rw: Path) -> None:
    @sb.command
    def cat_host(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=ctx.path(args[0]).read_text())

    @sb.command
    def outside(ctx: HostContext, args: list[str]) -> Result:
        return Result(stdout=Path("/nonexistent-spelaion/x").read_text())

    r = sb.bash("cat-host missing.txt")
    assert r.stderr == "cat-host: /scratch/missing.txt: No such file or directory\n"
    r = sb.bash("outside")
    assert r.stderr == "outside: No such file or directory\n"
    assert str(rw) not in sb.bash("cat-host missing.txt; outside").stderr


def test_exception_without_message(sb: Sandbox) -> None:
    @sb.command
    def bare(ctx: HostContext, args: list[str]) -> Result:
        raise KeyError

    assert sb.bash("bare").stderr == "bare: KeyError\n"


def test_handler_must_return_a_result(sb: Sandbox) -> None:
    @sb.command
    def nothing(ctx: HostContext, args: list[str]) -> Result:
        return None  # type: ignore[return-value]

    r = sb.bash("nothing; echo after")
    assert r.stdout == "after\n" and "nothing: internal error" in r.stderr


# --- Attachments ------------------------------------------------------------


def test_attachments_do_not_leak(sb: Sandbox, rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")
    assert len(sb.bash("show v.png; show v.png").attachments) == 2
    assert sb.bash("echo hi").attachments == []


def test_attachments_dropped_on_timeout(rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")
    with Sandbox([Mount("/scratch", rw)], cwd="/scratch", limits=Limits(1)) as s:
        r = s.bash("show v.png; printf '%s!\\n' " + "a" * 46 + " | grep -E '(a+)+$'")
        assert r.timed_out and r.attachments == []
        assert s.bash("echo ok").attachments == []


def test_attachment_in_returned_result(sb: Sandbox) -> None:
    from spelaion import Attachment

    @sb.command
    def give(ctx: HostContext, args: list[str]) -> Result:
        return Result(attachments=[Attachment("image/png", b"x", "given")])

    assert [a.name for a in sb.bash("give").attachments] == ["given"]


@pytest.mark.parametrize(("data", "mime"), [(JPEG, "image/jpeg"), (WEBP, "image/webp")])
def test_show_jpeg_and_webp(sb: Sandbox, rw: Path, data: bytes, mime: str) -> None:
    (rw / "img").write_bytes(data)
    r = sb.bash("show img")
    assert r.exit_code == 0 and [a.mime for a in r.attachments] == [mime]
    assert r.attachments[0].name == "/scratch/img"


def test_show_refuses_too_large(sb: Sandbox, rw: Path) -> None:
    (rw / "big.png").write_bytes(PNG_FIXTURE.read_bytes() + b"\0" * MAX_IMAGE)
    r = sb.bash("show big.png")
    assert r.exit_code == 1 and not r.attachments
    assert r.stderr == "show: /scratch/big.png: larger than 5 MB\n"


def test_show_at_the_cap(sb: Sandbox, rw: Path) -> None:
    data = PNG_FIXTURE.read_bytes()
    (rw / "cap.png").write_bytes(data + b"\0" * (MAX_IMAGE - len(data)))
    assert len(sb.bash("show cap.png").attachments) == 1


def test_show_errors(sb: Sandbox, rw: Path) -> None:
    (rw / "d").mkdir()
    r = sb.bash("show")
    assert (r.exit_code, r.stderr) == (2, "show: usage: show FILE...\n")
    r = sb.bash("show nope.png")
    assert r.stderr == "show: /scratch/nope.png: No such file or directory\n"
    r = sb.bash("show d")
    assert r.stderr == "show: /scratch/d: Is a directory\n"
    r = sb.bash("show /etc/passwd")
    assert r.stderr == "show: /etc/passwd: No such file or directory\n"


def test_show_refuses_symlink_out(sb: Sandbox, rw: Path, tmp_path: Path) -> None:
    shutil.copy(PNG_FIXTURE, tmp_path / "out.png")
    (rw / "link.png").symlink_to(tmp_path / "out.png")
    r = sb.bash("show link.png")
    assert r.exit_code == 1 and not r.attachments
    assert r.stderr == "show: /scratch/link.png: Permission denied\n"


def test_attach_refuses_unknown_mime(sb: Sandbox) -> None:
    @sb.command
    def gif(ctx: HostContext, args: list[str]) -> Result:
        ctx.attach(b"GIF89a", "image/gif")
        return Result()

    @sb.command
    def guess(ctx: HostContext, args: list[str]) -> Result:
        ctx.attach(b"plain")
        return Result()

    r = sb.bash("gif; guess")
    assert r.stderr == (
        "gif: image/gif is not image/png, image/jpeg or image/webp\n"
        "guess: image: not a PNG, JPEG or WebP image\n"
    )
    assert r.attachments == []


def test_attach_sandbox_path_and_mime_sniffed(sb: Sandbox, rw: Path) -> None:
    shutil.copy(PNG_FIXTURE, rw / "v.png")

    @sb.command
    def pin(ctx: HostContext, args: list[str]) -> Result:
        ctx.attach(args[0])
        return Result()

    r = sb.bash("pin v.png")
    assert [(a.mime, a.name) for a in r.attachments] == [
        ("image/png", "/scratch/v.png")
    ]
