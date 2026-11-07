"""Sandbox: bash, edit and write over mounts, in process."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from spelaion import Limits, Mount, Result, Sandbox
from spelaion._shell import Shell
from spelaion._truncate import truncate


@pytest.fixture
def ro(tmp_path: Path) -> Path:
    d = tmp_path / "ro"
    d.mkdir()
    return d


@pytest.fixture
def rw(tmp_path: Path) -> Path:
    d = tmp_path / "rw"
    d.mkdir()
    return d


@pytest.fixture
def sb(ro: Path, rw: Path) -> Iterator[Sandbox]:
    with Sandbox(
        [Mount("/project", ro, readonly=True), Mount("/scratch", rw)], cwd="/scratch"
    ) as s:
        yield s


# --- From the brief ---------------------------------------------------------


def test_files_persist_state_resets(sb: Sandbox) -> None:
    assert sb.bash("X=1; f() { :; }; cd /project; echo hi > /scratch/a").exit_code == 0
    r = sb.bash('echo "[$X]"; type f; pwd; cat /scratch/a')
    assert r.stdout.startswith("[]\n") and "/scratch\n" in r.stdout
    assert r.stdout.endswith("hi\n")


def test_edit_unique(sb: Sandbox) -> None:
    sb.write("/scratch/p.yaml", "a: 1\nb: 2\n")
    assert sb.edit("/scratch/p.yaml", "b: 2", "b: 3").exit_code == 0
    assert sb.bash("cat /scratch/p.yaml").stdout == "a: 1\nb: 3\n"


def test_edit_missing(sb: Sandbox) -> None:
    sb.write("/scratch/p", "a")
    r = sb.edit("/scratch/p", "zz", "y")
    assert r.exit_code == 1 and "old text not found in /scratch/p" in r.stderr


def test_edit_ambiguous(sb: Sandbox) -> None:
    sb.write("/scratch/p", "x\nx\n")
    r = sb.edit("/scratch/p", "x", "y")
    assert r.exit_code == 1 and "occurs 2 times" in r.stderr
    assert sb.bash("cat /scratch/p").stdout == "x\nx\n"


def test_write_readonly(sb: Sandbox) -> None:
    r = sb.write("/project/n", "x")
    assert r.exit_code == 1 and "Read-only file system" in r.stderr


def test_truncate_notice() -> None:
    t = truncate("".join(f"{i}\n" for i in range(10_000)), 1_000)
    assert "lines cut; narrow with grep or head]" in t
    assert t.startswith("0\n") and t.endswith("9999\n")


def test_tail_and_head_obsolete_form(sb: Sandbox) -> None:
    assert sb.bash("printf '1\\n2\\n3\\n' | tail -1").stdout == "3\n"
    assert sb.bash("printf '1\\n2\\n' | head -1").stdout == "1\n"


def test_wc_many_files(sb: Sandbox) -> None:
    sb.write("/scratch/a", "1\n")
    sb.write("/scratch/b", "1\n2\n")
    assert sb.bash("wc -l /scratch/a /scratch/b").stdout.split("\n")[:3] == [
        "1 /scratch/a",
        "2 /scratch/b",
        "3 total",
    ]


def test_odd_names_in_edit(sb: Sandbox) -> None:
    sb.write("/scratch/plan 2.yaml", "k: v\n")
    assert sb.edit("/scratch/plan 2.yaml", "v", "w").exit_code == 0


def test_missing_mount_folder(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        Sandbox([Mount("/x", tmp_path / "nope")])


def test_mount_deleted_later(sb: Sandbox, rw: Path) -> None:
    shutil.rmtree(rw)
    r = sb.bash("ls /scratch")
    assert r.exit_code != 0 and "Traceback" not in r.stderr
    assert "No such file or directory" in r.stderr


def test_write_does_not_recreate_deleted_mount(sb: Sandbox, rw: Path) -> None:
    shutil.rmtree(rw)
    for r in (sb.write("/scratch/x", "a"), sb.bash("echo a > /scratch/x")):
        assert r.exit_code == 1 and "No such file or directory" in r.stderr
    assert sb.bash("mkdir -p /scratch/d").exit_code == 1
    assert not rw.exists()


# --- Construction -----------------------------------------------------------


@pytest.mark.parametrize("cwd", ["scratch", "/nowhere", "/scratch/f", "/project/x"])
def test_bad_cwd_rejected(ro: Path, rw: Path, cwd: str) -> None:
    (rw / "f").write_text("x")
    with pytest.raises(ValueError, match="cwd"):
        Sandbox([Mount("/project", ro, readonly=True), Mount("/scratch", rw)], cwd=cwd)


def test_cwd_may_be_a_synthetic_folder(ro: Path, rw: Path) -> None:
    with Sandbox([Mount("/work/a", ro), Mount("/work/b", rw)], cwd="/work") as s:
        assert s.bash("pwd").stdout == "/work\n"


def test_missing_mount_folder_message_names_sandbox_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="/x"):
        Sandbox([Mount("/x", tmp_path / "nope")])


def test_mount_host_is_a_file(tmp_path: Path) -> None:
    (tmp_path / "f").write_text("x")
    with pytest.raises(FileNotFoundError):
        Sandbox([Mount("/x", tmp_path / "f")])


def test_overlapping_mounts_rejected(tmp_path: Path) -> None:
    (tmp_path / "a" / "b").mkdir(parents=True)
    with pytest.raises(ValueError, match="overlap"):
        Sandbox([Mount("/a", tmp_path / "a"), Mount("/b", tmp_path / "a" / "b")])


def test_same_host_folder_twice_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="overlap"):
        Sandbox([Mount("/a", tmp_path), Mount("/b", tmp_path, readonly=True)])


def test_sibling_folders_with_shared_prefix_allowed(tmp_path: Path) -> None:
    (tmp_path / "ab").mkdir()
    (tmp_path / "abc").mkdir()
    Sandbox([Mount("/a", tmp_path / "ab"), Mount("/b", tmp_path / "abc")]).close()


def test_defaults() -> None:
    assert Limits() == Limits(
        timeout_s=30, max_output=30_000, max_disk=50_000_000, memory_mb=1024
    )
    assert Result() == Result(stdout="", stderr="", exit_code=0, timed_out=False)


@pytest.mark.parametrize(
    "bad",
    [
        {"timeout_s": float("inf")},
        {"timeout_s": float("nan")},
        {"timeout_s": 0},
        {"timeout_s": -1},
        {"memory_mb": 0},
        {"memory_mb": 1.5},
        {"max_output": -1},
        {"max_disk": 0},
        {"max_disk": True},
    ],
)
def test_bad_limits_raise(bad: dict[str, object]) -> None:
    with pytest.raises(ValueError, match=next(iter(bad))):
        Limits(**bad)  # pyright: ignore[reportArgumentType]


def test_fractional_timeout_allowed() -> None:
    assert Limits(timeout_s=0.5).timeout_s == 0.5


# --- bash -------------------------------------------------------------------


def test_env_from_constructor(ro: Path, rw: Path) -> None:
    with Sandbox([Mount("/scratch", rw)], cwd="/scratch", env={"GREETING": "hey"}) as s:
        s.bash("GREETING=changed")
        assert s.bash('echo "$GREETING"; pwd').stdout == "hey\n/scratch\n"


def test_syntax_error(sb: Sandbox) -> None:
    r = sb.bash("if then fi (")
    assert r.exit_code == 2 and r.stderr


def test_exit_code_and_exit_builtin(sb: Sandbox) -> None:
    assert sb.bash("false").exit_code == 1
    assert sb.bash("exit 7").exit_code == 7


def test_output_truncated(ro: Path, rw: Path) -> None:
    mounts = [Mount("/scratch", rw)]
    with Sandbox(mounts, limits=Limits(max_output=200)) as s:
        r = s.bash("seq 1 1000; seq 1 1000 >&2")
    assert len(r.stdout) < 300 and "lines cut" in r.stdout
    assert len(r.stderr) < 300 and "lines cut" in r.stderr


def test_disk_cap_applies(rw: Path) -> None:
    (rw / "big").write_text("x" * 8)
    with Sandbox([Mount("/scratch", rw)], limits=Limits(max_disk=10)) as s:
        r = s.bash("echo more > /scratch/small")
    assert r.exit_code != 0 and not (rw / "small").exists()


def test_odd_names_through_shell(sb: Sandbox) -> None:
    sb.write("/scratch/-dash", "d\n")
    sb.write("/scratch/café", "c\n")
    r = sb.bash("cat -- -dash café 'plan 3' 2>/dev/null; ls")
    assert r.stdout.startswith("d\nc\n")
    assert "-dash" in r.stdout and "café" in r.stdout


# --- write ------------------------------------------------------------------


def test_write_relative_to_cwd(sb: Sandbox, rw: Path) -> None:
    assert sb.write("notes.txt", "n\n").exit_code == 0
    assert (rw / "notes.txt").read_text() == "n\n"


def test_write_creates_parents(sb: Sandbox, rw: Path) -> None:
    assert sb.write("/scratch/d/e/f.txt", "x").exit_code == 0
    assert (rw / "d" / "e" / "f.txt").read_text() == "x"


def test_write_overwrites(sb: Sandbox) -> None:
    sb.write("/scratch/p", "long text")
    sb.write("/scratch/p", "s")
    assert sb.bash("cat /scratch/p").stdout == "s"


def test_write_nul_in_path(sb: Sandbox) -> None:
    r = sb.write("/scratch/a\0b", "x")
    assert r.exit_code == 1 and r.stderr and "\0" not in r.stderr


def test_write_outside_mounts(sb: Sandbox) -> None:
    r = sb.write("/etc/passwd", "x")
    assert r.exit_code == 1 and "No such file or directory" in r.stderr


def test_write_escaping_symlink(sb: Sandbox, rw: Path, tmp_path: Path) -> None:
    (rw / "out").symlink_to(tmp_path)
    r = sb.write("/scratch/out/evil", "x")
    assert r.exit_code == 1 and not (tmp_path / "evil").exists()
    assert str(tmp_path) not in r.stderr


def test_write_to_directory(sb: Sandbox) -> None:
    sb.bash("mkdir /scratch/d")
    r = sb.write("/scratch/d", "x")
    assert r.exit_code == 1 and "Is a directory" in r.stderr


def test_write_disk_cap(rw: Path) -> None:
    with Sandbox([Mount("/scratch", rw)], limits=Limits(max_disk=10)) as s:
        assert s.write("/scratch/a", "x" * 8).exit_code == 0
        r = s.write("/scratch/b", "y" * 5)
    assert r.exit_code == 1 and "quota" in r.stderr.lower()
    assert not (rw / "b").exists()


def test_write_odd_names(sb: Sandbox, rw: Path) -> None:
    assert sb.write("/scratch/-n", "a").exit_code == 0
    assert sb.write("/scratch/ñandú.txt", "b").exit_code == 0
    assert (rw / "-n").read_text() == "a" and (rw / "ñandú.txt").read_text() == "b"


# --- edit -------------------------------------------------------------------


def test_edit_shows_context(sb: Sandbox) -> None:
    sb.write("/scratch/p", "".join(f"l{i}\n" for i in range(1, 11)))
    r = sb.edit("/scratch/p", "l5\n", "five\n")
    assert r.stdout == "l2\nl3\nl4\nfive\nl6\nl7\nl8\n"


def test_edit_ambiguous_message_exact(sb: Sandbox) -> None:
    sb.write("/scratch/p", "x x x")
    r = sb.edit("/scratch/p", "x", "y")
    assert r.stderr == (
        "old text occurs 3 times in /scratch/p; "
        "include more surrounding lines to make it unique\n"
    )


def test_edit_relative_path(sb: Sandbox) -> None:
    sb.write("/scratch/p", "a\n")
    assert sb.edit("p", "a", "b").exit_code == 0
    assert sb.bash("cat p").stdout == "b\n"


def test_edit_missing_file(sb: Sandbox) -> None:
    r = sb.edit("/scratch/nope", "a", "b")
    assert r.exit_code == 1 and "No such file or directory" in r.stderr


def test_edit_readonly(sb: Sandbox, ro: Path) -> None:
    (ro / "f").write_text("a\n")
    r = sb.edit("/project/f", "a", "b")
    assert r.exit_code == 1 and "Read-only file system" in r.stderr
    assert (ro / "f").read_text() == "a\n"


def test_edit_nul_in_path(sb: Sandbox) -> None:
    r = sb.edit("/scratch/a\0b", "a", "b")
    assert r.exit_code == 1 and r.stderr


def test_edit_empty_old_text(sb: Sandbox) -> None:
    sb.write("/scratch/p", "a\n")
    r = sb.edit("/scratch/p", "", "b")
    assert r.exit_code == 1


def test_edit_odd_names(sb: Sandbox) -> None:
    sb.write("/scratch/-x ñ", "k: v\n")
    assert sb.edit("/scratch/-x ñ", "v", "w").exit_code == 0
    assert sb.bash("cat -- '/scratch/-x ñ'").stdout == "k: w\n"


# --- head, tail, wc ---------------------------------------------------------


def test_tail_obsolete_form_on_file(sb: Sandbox) -> None:
    sb.write("/scratch/f", "1\n2\n3\n4\n")
    assert sb.bash("tail -2 /scratch/f").stdout == "3\n4\n"


def test_wc_many_files_continues_after_missing(sb: Sandbox) -> None:
    sb.write("/scratch/a", "1\n")
    r = sb.bash("wc -l /scratch/a /scratch/nope")
    assert r.exit_code == 1 and "1 /scratch/a" in r.stdout and "1 total" in r.stdout


def test_wc_single_file_unchanged(sb: Sandbox) -> None:
    sb.write("/scratch/a", "1\n2\n")
    assert sb.bash("wc -l /scratch/a").stdout.split()[0] == "2"


# --- truncate ---------------------------------------------------------------


def test_truncate_short_text_unchanged() -> None:
    assert truncate("abc\n", 10) == "abc\n"


def test_truncate_notice_exact_copy() -> None:
    t = truncate("".join(f"{i}\n" for i in range(10_000)), 1_000)
    head, rest = t.split("[… ", 1)
    n = int(rest.split(" ", 1)[0])
    assert f"[… {n} lines cut; narrow with grep or head]" in t
    kept = head.count("\n") + rest.split("]", 1)[1].count("\n")
    assert kept + n == 10_000 or kept + n == 10_001
    assert len(t) <= 1_000 + 60


def test_truncate_one_long_line() -> None:
    t = truncate("x" * 100_000, 1_000)
    assert len(t) < 1_100 and "cut" in t


# --- Text that is not Unicode, and internal errors ---------------------------


def test_write_lone_surrogate(sb: Sandbox, rw: Path) -> None:
    r = sb.write("/scratch/s", "a\ud800b")
    assert r.exit_code == 1 and "content is not valid Unicode text" in r.stderr
    assert not (rw / "s").exists()
    r = sb.write("/scratch/\ud800", "x")
    assert r.exit_code == 1 and "not valid Unicode text" in r.stderr
    r.stderr.encode("utf-8")


def test_edit_lone_surrogate(sb: Sandbox, rw: Path) -> None:
    sb.write("/scratch/p", "abc")
    r = sb.edit("/scratch/p", "b", "\ud800")
    assert r.exit_code == 1 and "new text is not valid Unicode text" in r.stderr
    assert (rw / "p").read_bytes() == b"abc"
    r = sb.edit("/scratch/\ud800", "b", "c")
    assert r.exit_code == 1 and "not valid Unicode text" in r.stderr
    r.stderr.encode("utf-8")


def test_bash_lone_surrogate(sb: Sandbox) -> None:
    r = sb.bash("echo \ud800")
    assert r.exit_code != 0 and "command is not valid Unicode text" in r.stderr


def test_edit_refuses_non_utf8(sb: Sandbox, rw: Path) -> None:
    data = b"\x89PNG\xff\xfe hello \xe9t\xe9\n"
    (rw / "img").write_bytes(data)
    r = sb.edit("/scratch/img", "hello", "bye")
    assert r.exit_code == 1 and r.stderr == "edit: /scratch/img: not UTF-8 text\n"
    assert (rw / "img").read_bytes() == data


def test_internal_error_logged_not_returned(
    rw: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def boom(*_: object) -> None:
        raise OSError(2, "No such file or directory", "/host/secret/path")

    # The sandbox runs Shell in a child, out of monkeypatch's reach.
    monkeypatch.setattr("spelaion._shell.Executor.execute_node", boom)
    shell = Shell([Mount("/scratch", rw)], "/scratch", {}, Limits())
    with caplog.at_level(logging.ERROR, logger="spelaion"):
        r = shell.call("bash", {"command": "true"})
    assert r.exit_code == 1
    assert r.stderr == (
        "spelaion: internal error: FileNotFoundError: No such file or directory\n"
    )
    assert "Traceback" not in r.stderr
    assert caplog.records and caplog.records[0].exc_info is not None
