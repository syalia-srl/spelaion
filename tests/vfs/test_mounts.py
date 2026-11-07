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
