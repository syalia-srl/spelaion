"""Comprehensive tests for the VirtualFilesystem."""

import pytest

from agentsh.vfs import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return an empty VFS."""
    return VirtualFilesystem()


@pytest.fixture
def seeded_vfs() -> VirtualFilesystem:
    """Return a VFS pre-populated with a small directory tree."""
    return VirtualFilesystem(
        initial_files={
            "/home/user/hello.txt": "Hello, world!\n",
            "/home/user/notes.txt": "Some notes\n",
            "/home/user/project/main.py": b"print('hi')\n",
            "/home/user/project/README.md": "# Project\n",
            "/etc/config.cfg": "key=value\n",
        }
    )


# ------------------------------------------------------------------
# Initial seeding
# ------------------------------------------------------------------


class TestInitialFiles:
    def test_seeded_files_exist(self, seeded_vfs: VirtualFilesystem) -> None:
        assert seeded_vfs.exists("/home/user/hello.txt")
        assert seeded_vfs.exists("/home/user/notes.txt")
        assert seeded_vfs.exists("/home/user/project/main.py")
        assert seeded_vfs.exists("/etc/config.cfg")

    def test_seeded_parent_dirs_created(self, seeded_vfs: VirtualFilesystem) -> None:
        assert seeded_vfs.is_dir("/home")
        assert seeded_vfs.is_dir("/home/user")
        assert seeded_vfs.is_dir("/home/user/project")
        assert seeded_vfs.is_dir("/etc")

    def test_seeded_content_strings_encoded(
        self, seeded_vfs: VirtualFilesystem
    ) -> None:
        assert seeded_vfs.read("/home/user/hello.txt") == b"Hello, world!\n"
        assert seeded_vfs.read("/etc/config.cfg") == b"key=value\n"

    def test_seeded_content_bytes_preserved(
        self, seeded_vfs: VirtualFilesystem
    ) -> None:
        assert seeded_vfs.read("/home/user/project/main.py") == b"print('hi')\n"


# ------------------------------------------------------------------
# Write and read
# ------------------------------------------------------------------


class TestWriteAndRead:
    def test_write_and_read_back(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/tmp/test.txt", b"content")
        assert vfs.read("/tmp/test.txt") == b"content"

    def test_write_overwrites_existing(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/tmp/f.txt", b"first")
        vfs.write("/tmp/f.txt", b"second")
        assert vfs.read("/tmp/f.txt") == b"second"

    def test_write_append(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/tmp/f.txt", b"aaa")
        vfs.write("/tmp/f.txt", b"bbb", append=True)
        assert vfs.read("/tmp/f.txt") == b"aaabbb"

    def test_write_creates_parent_dirs(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/a/b/c/d.txt", b"deep")
        assert vfs.is_dir("/a")
        assert vfs.is_dir("/a/b")
        assert vfs.is_dir("/a/b/c")
        assert vfs.read("/a/b/c/d.txt") == b"deep"

    def test_read_missing_file_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(FileNotFoundError):
            vfs.read("/nonexistent")

    def test_read_directory_raises(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/mydir")
        with pytest.raises(IsADirectoryError):
            vfs.read("/mydir")


# ------------------------------------------------------------------
# Path resolution
# ------------------------------------------------------------------


class TestResolve:
    def test_absolute_path_unchanged(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("/usr/bin/env", "/home") == "/usr/bin/env"

    def test_relative_path_uses_cwd(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("file.txt", "/home/user") == "/home/user/file.txt"

    def test_dot_resolved(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("./file.txt", "/home/user") == "/home/user/file.txt"

    def test_dotdot_resolved(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("../file.txt", "/home/user") == "/home/file.txt"

    def test_multiple_dotdot(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("../../etc/hosts", "/home/user") == "/etc/hosts"

    def test_multiple_slashes_normalized(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("///usr///bin", "/") == "/usr/bin"

    def test_trailing_slash_stripped(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("/usr/bin/", "/") == "/usr/bin"

    def test_dot_in_middle(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("/usr/./bin", "/") == "/usr/bin"

    def test_dotdot_at_root_stays_at_root(self, vfs: VirtualFilesystem) -> None:
        assert vfs.resolve("/../../../foo", "/") == "/foo"


# ------------------------------------------------------------------
# exists / is_file / is_dir
# ------------------------------------------------------------------


class TestExistsAndType:
    def test_root_is_dir(self, vfs: VirtualFilesystem) -> None:
        assert vfs.exists("/")
        assert vfs.is_dir("/")
        assert not vfs.is_file("/")

    def test_file_type(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/f.txt", b"x")
        assert vfs.exists("/f.txt")
        assert vfs.is_file("/f.txt")
        assert not vfs.is_dir("/f.txt")

    def test_dir_type(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/d")
        assert vfs.exists("/d")
        assert vfs.is_dir("/d")
        assert not vfs.is_file("/d")

    def test_nonexistent(self, vfs: VirtualFilesystem) -> None:
        assert not vfs.exists("/nope")
        assert not vfs.is_file("/nope")
        assert not vfs.is_dir("/nope")


# ------------------------------------------------------------------
# mkdir
# ------------------------------------------------------------------


class TestMkdir:
    def test_simple_mkdir(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/mydir")
        assert vfs.is_dir("/mydir")

    def test_mkdir_parents(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/a/b/c", parents=True)
        assert vfs.is_dir("/a")
        assert vfs.is_dir("/a/b")
        assert vfs.is_dir("/a/b/c")

    def test_mkdir_without_parents_raises_if_missing_intermediate(
        self, vfs: VirtualFilesystem
    ) -> None:
        with pytest.raises(FileNotFoundError):
            vfs.mkdir("/a/b/c")

    def test_mkdir_raises_if_exists(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/d")
        with pytest.raises(FileExistsError):
            vfs.mkdir("/d")

    def test_mkdir_root_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(FileExistsError):
            vfs.mkdir("/")


# ------------------------------------------------------------------
# listdir
# ------------------------------------------------------------------


class TestListdir:
    def test_listdir_sorted(self, seeded_vfs: VirtualFilesystem) -> None:
        entries = seeded_vfs.listdir("/home/user")
        assert entries == ["hello.txt", "notes.txt", "project"]

    def test_listdir_root(self, seeded_vfs: VirtualFilesystem) -> None:
        entries = seeded_vfs.listdir("/")
        assert entries == ["etc", "home"]

    def test_listdir_missing_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(FileNotFoundError):
            vfs.listdir("/nope")

    def test_listdir_on_file_raises(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/f.txt", b"data")
        with pytest.raises(NotADirectoryError):
            vfs.listdir("/f.txt")

    def test_listdir_empty_dir(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/empty")
        assert vfs.listdir("/empty") == []


# ------------------------------------------------------------------
# unlink
# ------------------------------------------------------------------


class TestUnlink:
    def test_unlink_file(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/f.txt", b"data")
        vfs.unlink("/f.txt")
        assert not vfs.exists("/f.txt")

    def test_unlink_missing_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(FileNotFoundError):
            vfs.unlink("/nonexistent")

    def test_unlink_dir_raises(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/d")
        with pytest.raises(IsADirectoryError):
            vfs.unlink("/d")


# ------------------------------------------------------------------
# rmdir
# ------------------------------------------------------------------


class TestRmdir:
    def test_rmdir_empty(self, vfs: VirtualFilesystem) -> None:
        vfs.mkdir("/d")
        vfs.rmdir("/d")
        assert not vfs.exists("/d")

    def test_rmdir_nonempty_raises(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/d/f.txt", b"x")
        with pytest.raises(OSError):
            vfs.rmdir("/d")

    def test_rmdir_missing_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(FileNotFoundError):
            vfs.rmdir("/nonexistent")

    def test_rmdir_file_raises(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/f.txt", b"x")
        with pytest.raises(NotADirectoryError):
            vfs.rmdir("/f.txt")

    def test_rmdir_root_raises(self, vfs: VirtualFilesystem) -> None:
        with pytest.raises(OSError):
            vfs.rmdir("/")


# ------------------------------------------------------------------
# glob
# ------------------------------------------------------------------


class TestGlob:
    def test_glob_star_txt(self, seeded_vfs: VirtualFilesystem) -> None:
        result = seeded_vfs.glob("/home/user/*.txt", "/")
        assert result == ["/home/user/hello.txt", "/home/user/notes.txt"]

    def test_glob_all_in_dir(self, seeded_vfs: VirtualFilesystem) -> None:
        result = seeded_vfs.glob("/home/user/project/*", "/")
        assert result == [
            "/home/user/project/README.md",
            "/home/user/project/main.py",
        ]

    def test_glob_relative_pattern(self, seeded_vfs: VirtualFilesystem) -> None:
        result = seeded_vfs.glob("*.txt", "/home/user")
        assert result == ["/home/user/hello.txt", "/home/user/notes.txt"]

    def test_glob_no_matches(self, seeded_vfs: VirtualFilesystem) -> None:
        result = seeded_vfs.glob("/home/user/*.xyz", "/")
        assert result == []

    def test_glob_question_mark(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/tmp/a1.txt", b"")
        vfs.write("/tmp/a2.txt", b"")
        vfs.write("/tmp/ab.txt", b"")
        result = vfs.glob("/tmp/a?.txt", "/")
        assert result == ["/tmp/a1.txt", "/tmp/a2.txt", "/tmp/ab.txt"]

    def test_glob_bracket_pattern(self, vfs: VirtualFilesystem) -> None:
        vfs.write("/tmp/a1.txt", b"")
        vfs.write("/tmp/a2.txt", b"")
        vfs.write("/tmp/a3.txt", b"")
        result = vfs.glob("/tmp/a[12].txt", "/")
        assert result == ["/tmp/a1.txt", "/tmp/a2.txt"]
