"""MountFs: host folders mounted at sandbox paths, one resolver for all."""

from __future__ import annotations

import errno
import struct
import zlib
from pathlib import Path

import pytest

from spelaion.exec.executor import Executor
from spelaion.exec.redirs import IOContext
from spelaion.parser.frontend import parse_script
from spelaion.parser.normalize import normalize
from spelaion.policy.decisions import PolicyEngine
from spelaion.policy.rules import PolicyConfig
from spelaion.runtime.state import ShellState
from spelaion.tools.registry import ToolRegistry
from spelaion.vfs.mounts import Mount, MountFs


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
def fs(ro: Path, rw: Path) -> MountFs:
    return MountFs([Mount("/project", ro, readonly=True), Mount("/scratch", rw)])


@pytest.fixture
def fs_capped_100(ro: Path, rw: Path) -> MountFs:
    return MountFs(
        [Mount("/project", ro, readonly=True), Mount("/scratch", rw)], max_disk=100
    )


def run(fs: MountFs, script: str, cwd: str = "/") -> tuple[int, str, str]:
    """Run *script* over *fs* the way ``Bash._do_run`` does."""
    state = ShellState()
    state.cwd = cwd
    executor = Executor(
        state=state,
        vfs=fs,
        tools=ToolRegistry(),
        policy=PolicyEngine(config=PolicyConfig()),
    )
    parsed = parse_script(script)
    assert not parsed.has_errors
    program, _ = normalize(parsed.root_node, script)
    io = IOContext()
    result = executor.execute_node(program, io)
    return result.exit_code, io.stdout.getvalue(), io.stderr.getvalue()


def _png() -> bytes:
    """A real 1x1 PNG, with bytes that are not valid UTF-8."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x80\x00")
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


# -- resolver ---------------------------------------------------------------


def test_dotdot_cannot_leave_root(fs: MountFs) -> None:
    assert fs.resolve("/scratch/../../etc/passwd", "/") == "/etc/passwd"
    with pytest.raises(FileNotFoundError):
        fs.read("/etc/passwd")


def test_unmounted_path_does_not_exist(fs: MountFs) -> None:
    assert not fs.exists("/etc")


def test_root_lists_mount_points(fs: MountFs) -> None:
    assert sorted(fs.listdir("/")) == ["project", "scratch"]


def test_planted_symlink_out_is_refused(fs: MountFs, rw: Path) -> None:
    (rw / "evil").symlink_to("/etc/hostname")
    with pytest.raises(PermissionError):
        fs.read("/scratch/evil")


def test_symlink_inside_mount_is_followed(fs: MountFs, rw: Path) -> None:
    (rw / "a").write_text("x")
    (rw / "b").symlink_to(rw / "a")
    assert fs.read("/scratch/b") == b"x"


def test_write_to_readonly_mount(fs: MountFs) -> None:
    with pytest.raises(PermissionError) as e:
        fs.write("/project/x", b"1")
    assert e.value.errno == errno.EROFS


def test_disk_cap(fs_capped_100: MountFs) -> None:
    fs_capped_100.write("/scratch/a", b"x" * 60)
    with pytest.raises(OSError) as e:
        fs_capped_100.write("/scratch/b", b"x" * 60)
    assert e.value.errno == errno.EDQUOT


def test_overwrite_counts_new_size_only(fs_capped_100: MountFs) -> None:
    fs_capped_100.write("/scratch/a", b"x" * 60)
    fs_capped_100.write("/scratch/a", b"y" * 90)


def test_odd_names(fs: MountFs) -> None:
    fs.write("/scratch/plan 2 ñ.yaml", b"a")
    fs.write("/scratch/-x", b"b")
    assert sorted(fs.listdir("/scratch")) == ["-x", "plan 2 ñ.yaml"]


def test_errors_carry_errno(fs: MountFs, rw: Path) -> None:
    with pytest.raises(FileNotFoundError) as e:
        fs.host_path("/etc/passwd")
    assert e.value.errno == errno.ENOENT
    (rw / "evil").symlink_to("/etc")
    with pytest.raises(PermissionError) as e2:
        fs.host_path("/scratch/evil/hostname")
    assert e2.value.errno == errno.EACCES


def test_symlinked_dir_out_is_refused_for_write(
    fs: MountFs, rw: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (rw / "door").symlink_to(outside)
    with pytest.raises(PermissionError):
        fs.write("/scratch/door/x", b"1")
    assert not (outside / "x").exists()


def test_write_creates_parents_inside_mount(fs: MountFs, rw: Path) -> None:
    fs.write("/scratch/a/b/c.txt", b"hi")
    assert (rw / "a" / "b" / "c.txt").read_bytes() == b"hi"


def test_write_stops_at_deleted_mount_root(fs: MountFs, rw: Path) -> None:
    rw.rmdir()
    with pytest.raises(FileNotFoundError):
        fs.write("/scratch/a/b.txt", b"hi")
    with pytest.raises(FileNotFoundError):
        fs.mkdir("/scratch/a", parents=True)
    assert not rw.exists()


def test_strict_prefix_of_mount_is_synthetic_dir(ro: Path, rw: Path) -> None:
    fs = MountFs([Mount("/work/project", ro), Mount("/work/scratch", rw)])
    assert fs.is_dir("/work")
    assert sorted(fs.listdir("/")) == ["work"]
    assert sorted(fs.listdir("/work")) == ["project", "scratch"]
    assert not fs.exists("/wor")
    with pytest.raises(FileNotFoundError):
        fs.write("/work/x", b"1")


def test_nested_mount_uses_longest_prefix(ro: Path, rw: Path) -> None:
    fs = MountFs([Mount("/project", ro, readonly=True), Mount("/project/out", rw)])
    fs.write("/project/out/r.txt", b"ok")
    assert (rw / "r.txt").read_bytes() == b"ok"
    assert "out" in fs.listdir("/project")


def test_disk_used_counts_writable_mounts_only(fs: MountFs, ro: Path) -> None:
    (ro / "big").write_bytes(b"x" * 1000)
    fs.write("/scratch/a", b"x" * 7)
    assert fs.disk_used() == 7


def test_get_node_reflects_host(fs: MountFs, rw: Path) -> None:
    (rw / "d").mkdir()
    (rw / "d" / "f").write_bytes(b"abc")
    node = fs.get_node("/scratch/d")
    assert node is not None and not hasattr(node, "content")
    f = fs.get_node("/scratch/d/f")
    assert f is not None and getattr(f, "content", None) == b"abc"


def test_rename_and_unlink_stay_in_mounts(fs: MountFs, rw: Path) -> None:
    fs.write("/scratch/a", b"1")
    fs.rename("/scratch/a", "/scratch/b")
    assert (rw / "b").exists() and not (rw / "a").exists()
    with pytest.raises(PermissionError):
        fs.rename("/scratch/b", "/project/b")
    fs.unlink("/scratch/b")
    assert not (rw / "b").exists()


# -- through the shell ------------------------------------------------------


def test_shell_cat_dotdot_out(fs: MountFs) -> None:
    code, _, err = run(fs, "cat /project/../../etc/passwd")
    assert code == 1
    assert "No such file or directory" in err


def test_shell_redirect_into_readonly(fs: MountFs, ro: Path) -> None:
    code, _, err = run(fs, "echo x > /project/a")
    assert code == 1
    assert "Read-only file system" in err
    assert not (ro / "a").exists()


def test_shell_ln_refused(fs: MountFs, rw: Path) -> None:
    code, _, err = run(fs, "ln -s /etc /scratch/e")
    assert code == 1
    assert "ln: links are not supported in the sandbox" in err
    assert not (rw / "e").exists()


def test_shell_cp_into_readonly(fs: MountFs, rw: Path) -> None:
    (rw / "a").write_text("x")
    code, _, err = run(fs, "cp /scratch/a /project/a")
    assert code == 1
    assert "Read-only file system" in err


def test_shell_planted_symlink(fs: MountFs, rw: Path) -> None:
    (rw / "evil").symlink_to("/etc/hostname")
    code, out, err = run(fs, "cat /scratch/evil")
    assert code == 1
    assert out == ""
    assert "Permission denied" in err


def test_shell_binary_png(fs: MountFs, ro: Path) -> None:
    png = _png()
    (ro / "img.png").write_bytes(png)
    code, out, _ = run(fs, "cat /project/img.png | wc -c")
    assert code == 0
    assert int(out.strip()) > 0
    code, _, err = run(fs, "grep -c IHDR /project/img.png")
    assert code == 0, err
    code, out, _ = run(fs, "cat /project/img.png")
    assert code == 0
    assert "�" in out


def test_shell_odd_names(fs: MountFs, rw: Path) -> None:
    code, _, err = run(
        fs, "echo hi > '/scratch/plan 2 ñ.yaml' && cat -- /scratch/'plan 2 ñ.yaml'"
    )
    assert code == 0, err
    assert (rw / "plan 2 ñ.yaml").read_text() == "hi\n"
    code, out, err = run(fs, "echo z > ./-x && cat -- -x && ls", cwd="/scratch")
    assert code == 0, err
    assert "z\n" in out
    assert "-x" in out


def test_shell_disk_cap(fs_capped_100: MountFs) -> None:
    code, _, err = run(fs_capped_100, "printf '%0200d' 0 > /scratch/big")
    assert code == 1
    assert "quota" in err.lower()


def test_full_disk_can_still_be_cleaned(fs_capped_100: MountFs, rw: Path) -> None:
    (rw / "host-made").write_bytes(b"x" * 150)
    with pytest.raises(OSError) as e:
        fs_capped_100.write("/scratch/a", b"1")
    assert e.value.errno == errno.EDQUOT
    fs_capped_100.unlink("/scratch/host-made")
    fs_capped_100.write("/scratch/a", b"1")


def test_cannot_remove_from_readonly_or_a_mount_point(fs: MountFs, ro: Path) -> None:
    (ro / "keep").write_text("k")
    with pytest.raises(PermissionError):
        fs.unlink("/project/keep")
    with pytest.raises(OSError):
        fs.rmtree("/scratch")
    assert (ro / "keep").exists()


# -- fix round 1 --------------------------------------------------------------


def test_mv_onto_symlink_out_stays_inside(
    fs: MountFs, rw: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (rw / "f").write_text("secret")
    (rw / "evil").symlink_to(outside)
    code, _, _ = run(fs, "mv /scratch/f /scratch/evil")
    assert list(outside.iterdir()) == []
    if code == 0:
        # The link itself was replaced by the file.
        assert not (rw / "evil").is_symlink()
        assert (rw / "evil").read_text() == "secret"


def test_rename_across_host_filesystems(
    fs: MountFs, rw: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def exdev(src: object, dst: object) -> None:
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    (rw / "d").mkdir()
    (rw / "d" / "a").write_text("1")
    (rw / "f").write_text("2")
    monkeypatch.setattr("spelaion.vfs.mounts.os.rename", exdev)
    fs.rename("/scratch/d", "/scratch/e")
    fs.rename("/scratch/f", "/scratch/g")
    assert (rw / "e" / "a").read_text() == "1"
    assert (rw / "g").read_text() == "2"
    assert not (rw / "d").exists()
    assert not (rw / "f").exists()


def test_mv_dir_into_itself_names_no_host_path(fs: MountFs, tmp_path: Path) -> None:
    code, out, err = run(fs, "mkdir /scratch/d && mv /scratch/d /scratch/d/x")
    assert code == 1
    assert "subdirectory of itself" in err
    assert str(tmp_path) not in out + err


def test_errno_less_oserror_becomes_eio(fs: MountFs, rw: Path) -> None:
    from spelaion.vfs.mounts import _as_sandbox

    with pytest.raises(OSError) as e, _as_sandbox("/scratch/x"):
        raise OSError(f"cannot copy {rw}/x")
    assert e.value.errno == errno.EIO
    assert str(rw) not in str(e.value)


def test_ls_lists_past_a_symlink_out(fs: MountFs, rw: Path) -> None:
    (rw / "a").write_text("1")
    (rw / "b").write_text("2")
    (rw / "python").symlink_to("/usr/bin/python3")
    code, out, err = run(fs, "ls -l /scratch")
    assert code == 0, err
    for name in ("a", "b", "python"):
        assert name in out.split()
    code, _, err = run(fs, "cat /scratch/python")
    assert code == 1
    assert "Permission denied" in err


def test_chmod_reaches_the_host(fs: MountFs, rw: Path) -> None:
    (rw / "s.sh").write_text("echo")
    (rw / "s.sh").chmod(0o644)
    code, _, err = run(fs, "chmod 755 /scratch/s.sh && chmod g-x /scratch/s.sh")
    assert code == 0, err
    assert (rw / "s.sh").stat().st_mode & 0o777 == 0o745


def test_chmod_recursive_reaches_the_host(fs: MountFs, rw: Path) -> None:
    (rw / "d").mkdir()
    (rw / "d" / "a").write_text("1")
    code, _, err = run(fs, "chmod -R 700 /scratch/d")
    assert code == 0, err
    assert (rw / "d").stat().st_mode & 0o777 == 0o700
    assert (rw / "d" / "a").stat().st_mode & 0o777 == 0o700


def test_chmod_readonly_mount_refused(fs: MountFs, ro: Path) -> None:
    (ro / "a").write_text("1")
    (ro / "a").chmod(0o644)
    code, _, err = run(fs, "chmod 777 /project/a")
    assert code == 1
    assert "Read-only file system" in err
    assert (ro / "a").stat().st_mode & 0o777 == 0o644


def test_shred_overwrites_the_host_file(fs: MountFs, rw: Path, ro: Path) -> None:
    (rw / "k").write_text("key")
    code, _, err = run(fs, "shred /scratch/k")
    assert code == 0, err
    assert (rw / "k").read_bytes() == b"\x00\x00\x00"
    (ro / "k").write_text("key")
    code, _, err = run(fs, "shred /project/k")
    assert code == 1
    assert (ro / "k").read_text() == "key"


def test_nul_in_path_is_einval(fs: MountFs) -> None:
    for call in (
        lambda: fs.host_path("/scratch/a\0b"),
        lambda: fs.host_path("/scratch/a\0b", write=True),
        lambda: fs.unlink("/scratch/a\0b"),
    ):
        with pytest.raises(OSError) as e:
            call()
        assert e.value.errno == errno.EINVAL


def test_procsub_pipe_lives_in_memory(fs: MountFs, tmp_path: Path) -> None:
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    fs.write("/dev/fd/procsub_1", b"hi\n")
    assert fs.read("/dev/fd/procsub_1") == b"hi\n"
    assert fs.is_file("/dev/fd/procsub_1")
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
    assert fs.listdir("/") == ["project", "scratch"]
    assert not fs.exists("/dev")
    with pytest.raises(FileNotFoundError):
        fs.host_path("/dev/fd/procsub_1")
    fs.clear_pipes()
    assert not fs.exists("/dev/fd/procsub_1")


def test_only_procsub_names_are_pipes(fs: MountFs) -> None:
    with pytest.raises(FileNotFoundError):
        fs.write("/dev/fd/3", b"x")
