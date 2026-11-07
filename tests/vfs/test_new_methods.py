"""Tests for VFS methods: rename, copy_file, copy_tree, walk, rmtree."""

import pytest

from agentsh.vfs.filesystem import VirtualFilesystem

# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def vfs() -> VirtualFilesystem:
    """Return an empty VFS."""
    return VirtualFilesystem()


@pytest.fixture
def seeded_vfs() -> VirtualFilesystem:
    """Return a VFS pre-populated with a small directory tree.

    Layout::

        /home/user/hello.txt          "Hello, world!\n"
        /home/user/notes.txt          "Some notes\n"
        /home/user/project/main.py    b"print('hi')\n"
        /home/user/project/README.md  "# Project\n"
        /etc/config.cfg               "key=value\n"
    """
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
# rename
# ------------------------------------------------------------------


class TestRename:
    def test_rename_file(self, vfs: VirtualFilesystem) -> None:
        """Rename a file to a new name in the same directory."""
        vfs.write("/tmp/old.txt", b"content")
        vfs.rename("/tmp/old.txt", "/tmp/new.txt")

        assert not vfs.exists("/tmp/old.txt")
        assert vfs.exists("/tmp/new.txt")
        assert vfs.read("/tmp/new.txt") == b"content"

    def test_rename_file_to_different_directory(self, vfs: VirtualFilesystem) -> None:
        """Rename (move) a file to a different directory path."""
        vfs.write("/src/file.txt", b"data")
        vfs.mkdir("/dst")
        vfs.rename("/src/file.txt", "/dst/moved.txt")

        assert not vfs.exists("/src/file.txt")
        assert vfs.read("/dst/moved.txt") == b"data"

    def test_rename_into_existing_directory(self, vfs: VirtualFilesystem) -> None:
        """When dst is an existing directory the source is moved inside it."""
        vfs.write("/tmp/file.txt", b"hello")
        vfs.mkdir("/dest")
        vfs.rename("/tmp/file.txt", "/dest")

        assert not vfs.exists("/tmp/file.txt")
        assert vfs.read("/dest/file.txt") == b"hello"

    def test_rename_overwrites_existing_file(self, vfs: VirtualFilesystem) -> None:
        """Renaming onto an existing file replaces it."""
        vfs.write("/a.txt", b"first")
        vfs.write("/b.txt", b"second")
        vfs.rename("/a.txt", "/b.txt")

        assert not vfs.exists("/a.txt")
        assert vfs.read("/b.txt") == b"first"

    def test_rename_nonexistent_raises(self, vfs: VirtualFilesystem) -> None:
        """Renaming a path that does not exist raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            vfs.rename("/nonexistent.txt", "/dst.txt")

    def test_rename_directory(self, vfs: VirtualFilesystem) -> None:
        """Rename an entire directory (with contents)."""
        vfs.write("/project/src/main.py", b"code")
        vfs.write("/project/src/util.py", b"util")
        vfs.rename("/project/src", "/project/lib")

        assert not vfs.exists("/project/src")
        assert vfs.is_dir("/project/lib")
        assert vfs.read("/project/lib/main.py") == b"code"
        assert vfs.read("/project/lib/util.py") == b"util"

    def test_rename_dir_into_existing_dir(self, vfs: VirtualFilesystem) -> None:
        """When dst is an existing directory, the source dir is moved inside it."""
        vfs.write("/src/data/file.txt", b"content")
        vfs.mkdir("/target")
        vfs.rename("/src/data", "/target")

        assert not vfs.exists("/src/data")
        assert vfs.is_dir("/target/data")
        assert vfs.read("/target/data/file.txt") == b"content"

    def test_rename_preserves_content(self, seeded_vfs: VirtualFilesystem) -> None:
        """Content is preserved exactly after rename."""
        original = seeded_vfs.read("/home/user/hello.txt")
        seeded_vfs.rename("/home/user/hello.txt", "/home/user/greeting.txt")
        assert seeded_vfs.read("/home/user/greeting.txt") == original


# ------------------------------------------------------------------
# copy_file
# ------------------------------------------------------------------


class TestCopyFile:
    def test_basic_copy(self, vfs: VirtualFilesystem) -> None:
        """Copy a file to a new path."""
        vfs.write("/src.txt", b"data")
        vfs.copy_file("/src.txt", "/dst.txt")

        assert vfs.read("/src.txt") == b"data"  # source still exists
        assert vfs.read("/dst.txt") == b"data"

    def test_copy_into_existing_directory(self, vfs: VirtualFilesystem) -> None:
        """When dst is an existing directory, the file is copied inside it."""
        vfs.write("/tmp/file.txt", b"content")
        vfs.mkdir("/dest")
        vfs.copy_file("/tmp/file.txt", "/dest")

        assert vfs.read("/dest/file.txt") == b"content"
        assert vfs.read("/tmp/file.txt") == b"content"  # source unchanged

    def test_copy_nonexistent_raises(self, vfs: VirtualFilesystem) -> None:
        """Copying a nonexistent source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            vfs.copy_file("/nonexistent.txt", "/dst.txt")

    def test_copy_directory_raises(self, vfs: VirtualFilesystem) -> None:
        """copy_file on a directory source raises IsADirectoryError."""
        vfs.mkdir("/mydir")
        with pytest.raises(IsADirectoryError):
            vfs.copy_file("/mydir", "/other")

    def test_copy_creates_independent_copy(self, vfs: VirtualFilesystem) -> None:
        """Modifying the copy does not affect the original."""
        vfs.write("/original.txt", b"original")
        vfs.copy_file("/original.txt", "/copy.txt")
        vfs.write("/copy.txt", b"modified")

        assert vfs.read("/original.txt") == b"original"
        assert vfs.read("/copy.txt") == b"modified"

    def test_copy_overwrites_existing_file(self, vfs: VirtualFilesystem) -> None:
        """Copying onto an existing file overwrites its contents."""
        vfs.write("/a.txt", b"aaa")
        vfs.write("/b.txt", b"bbb")
        vfs.copy_file("/a.txt", "/b.txt")

        assert vfs.read("/b.txt") == b"aaa"

    def test_copy_binary_content(self, vfs: VirtualFilesystem) -> None:
        """Binary content is preserved through copy."""
        data = bytes(range(256))
        vfs.write("/bin.dat", data)
        vfs.copy_file("/bin.dat", "/bin_copy.dat")

        assert vfs.read("/bin_copy.dat") == data

    def test_copy_empty_file(self, vfs: VirtualFilesystem) -> None:
        """Copying an empty file works correctly."""
        vfs.write("/empty.txt", b"")
        vfs.copy_file("/empty.txt", "/empty_copy.txt")

        assert vfs.read("/empty_copy.txt") == b""

    def test_copy_creates_parent_dirs(self, vfs: VirtualFilesystem) -> None:
        """copy_file to a path with missing parents creates them (via write)."""
        vfs.write("/src.txt", b"data")
        vfs.copy_file("/src.txt", "/a/b/c/dst.txt")

        assert vfs.read("/a/b/c/dst.txt") == b"data"


# ------------------------------------------------------------------
# copy_tree
# ------------------------------------------------------------------


class TestCopyTree:
    def test_copy_directory_tree(self, vfs: VirtualFilesystem) -> None:
        """Copy an entire directory tree to a new destination."""
        vfs.write("/src/a.txt", b"aaa")
        vfs.write("/src/b.txt", b"bbb")
        vfs.write("/src/sub/c.txt", b"ccc")
        vfs.copy_tree("/src", "/dst")

        assert vfs.is_dir("/dst")
        assert vfs.read("/dst/a.txt") == b"aaa"
        assert vfs.read("/dst/b.txt") == b"bbb"
        assert vfs.read("/dst/sub/c.txt") == b"ccc"

    def test_copy_tree_preserves_source(self, vfs: VirtualFilesystem) -> None:
        """The source tree is left intact after copy_tree."""
        vfs.write("/src/file.txt", b"data")
        vfs.copy_tree("/src", "/dst")

        assert vfs.exists("/src/file.txt")
        assert vfs.read("/src/file.txt") == b"data"

    def test_copy_tree_file_delegates_to_copy_file(
        self, vfs: VirtualFilesystem
    ) -> None:
        """When src is a file, copy_tree delegates to copy_file."""
        vfs.write("/single.txt", b"solo")
        vfs.copy_tree("/single.txt", "/copied.txt")

        assert vfs.read("/copied.txt") == b"solo"
        assert vfs.read("/single.txt") == b"solo"

    def test_copy_tree_nonexistent_raises(self, vfs: VirtualFilesystem) -> None:
        """Copying from a nonexistent source raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            vfs.copy_tree("/nonexistent", "/dst")

    def test_copy_tree_nested_dirs(self, vfs: VirtualFilesystem) -> None:
        """Deeply nested directories are copied correctly."""
        vfs.write("/deep/a/b/c/d.txt", b"deep")
        vfs.write("/deep/a/x.txt", b"shallow")
        vfs.copy_tree("/deep", "/clone")

        assert vfs.read("/clone/a/b/c/d.txt") == b"deep"
        assert vfs.read("/clone/a/x.txt") == b"shallow"
        assert vfs.is_dir("/clone/a/b/c")

    def test_copy_tree_empty_dir(self, vfs: VirtualFilesystem) -> None:
        """Copying an empty directory creates the destination directory."""
        vfs.mkdir("/empty")
        vfs.copy_tree("/empty", "/empty_copy")

        assert vfs.is_dir("/empty_copy")
        assert vfs.listdir("/empty_copy") == []

    def test_copy_tree_independent_of_source(self, vfs: VirtualFilesystem) -> None:
        """Modifications to the copy do not affect the source."""
        vfs.write("/src/file.txt", b"original")
        vfs.copy_tree("/src", "/dst")
        vfs.write("/dst/file.txt", b"modified")

        assert vfs.read("/src/file.txt") == b"original"

    def test_copy_tree_with_mixed_content(self, seeded_vfs: VirtualFilesystem) -> None:
        """Copy a real sub-tree from the seeded VFS."""
        seeded_vfs.copy_tree("/home/user/project", "/backup/project")

        assert seeded_vfs.read("/backup/project/main.py") == b"print('hi')\n"
        assert seeded_vfs.read("/backup/project/README.md") == b"# Project\n"


# ------------------------------------------------------------------
# walk
# ------------------------------------------------------------------


class TestWalk:
    def test_walk_directory_tree(self, seeded_vfs: VirtualFilesystem) -> None:
        """walk yields (dirpath, dirnames, filenames) tuples top-down."""
        results = list(seeded_vfs.walk("/home/user"))

        # First entry is the top directory
        assert results[0][0] == "/home/user"
        assert "project" in results[0][1]
        assert "hello.txt" in results[0][2]
        assert "notes.txt" in results[0][2]

        # Second entry is the subdirectory
        assert results[1][0] == "/home/user/project"
        assert results[1][1] == []  # no subdirs
        assert "main.py" in results[1][2]
        assert "README.md" in results[1][2]

    def test_walk_empty_dir(self, vfs: VirtualFilesystem) -> None:
        """Walking an empty directory yields one entry with empty lists."""
        vfs.mkdir("/empty")
        results = list(vfs.walk("/empty"))

        assert len(results) == 1
        assert results[0] == ("/empty", [], [])

    def test_walk_nonexistent_returns_empty(self, vfs: VirtualFilesystem) -> None:
        """Walking a nonexistent path returns an empty iterator."""
        results = list(vfs.walk("/nonexistent"))
        assert results == []

    def test_walk_file_returns_empty(self, vfs: VirtualFilesystem) -> None:
        """Walking a file (not a directory) returns an empty iterator."""
        vfs.write("/file.txt", b"data")
        results = list(vfs.walk("/file.txt"))
        assert results == []

    def test_walk_sorted_output(self, vfs: VirtualFilesystem) -> None:
        """dirnames and filenames within each entry are sorted."""
        vfs.write("/dir/z.txt", b"")
        vfs.write("/dir/a.txt", b"")
        vfs.write("/dir/m.txt", b"")
        vfs.mkdir("/dir/zdir")
        vfs.mkdir("/dir/adir")

        results = list(vfs.walk("/dir"))
        _dirpath, dirnames, filenames = results[0]

        assert dirnames == ["adir", "zdir"]
        assert filenames == ["a.txt", "m.txt", "z.txt"]

    def test_walk_root(self, seeded_vfs: VirtualFilesystem) -> None:
        """Walking root yields the entire tree."""
        results = list(seeded_vfs.walk("/"))
        dirpaths = [r[0] for r in results]

        assert dirpaths[0] == "/"
        assert "/etc" in dirpaths
        assert "/home" in dirpaths
        assert "/home/user" in dirpaths
        assert "/home/user/project" in dirpaths

    def test_walk_yields_correct_count(self, seeded_vfs: VirtualFilesystem) -> None:
        """The total number of yielded entries matches the number of directories."""
        results = list(seeded_vfs.walk("/"))
        # Directories: /, /etc, /home, /home/user, /home/user/project => 5
        assert len(results) == 5

    def test_walk_nested_dirs(self, vfs: VirtualFilesystem) -> None:
        """Walk deeply nested directories in top-down order."""
        vfs.write("/a/b/c/file.txt", b"")
        results = list(vfs.walk("/a"))

        dirpaths = [r[0] for r in results]
        assert dirpaths == ["/a", "/a/b", "/a/b/c"]

        # The leaf directory has a file but no subdirs
        assert results[2] == ("/a/b/c", [], ["file.txt"])

    def test_walk_is_iterator(self, vfs: VirtualFilesystem) -> None:
        """walk returns an iterator, not a list."""
        vfs.mkdir("/d")
        result = vfs.walk("/d")
        # Should be an iterator (has __next__), not a list
        assert hasattr(result, "__next__")


# ------------------------------------------------------------------
# rmtree
# ------------------------------------------------------------------


class TestRmtree:
    def test_remove_dir_with_files(self, vfs: VirtualFilesystem) -> None:
        """rmtree removes a directory and all its files."""
        vfs.write("/dir/a.txt", b"aaa")
        vfs.write("/dir/b.txt", b"bbb")
        vfs.rmtree("/dir")

        assert not vfs.exists("/dir")
        assert not vfs.exists("/dir/a.txt")
        assert not vfs.exists("/dir/b.txt")

    def test_remove_nested_dirs(self, vfs: VirtualFilesystem) -> None:
        """rmtree removes deeply nested directory structures."""
        vfs.write("/top/mid/bot/file.txt", b"deep")
        vfs.write("/top/mid/other.txt", b"other")
        vfs.write("/top/root.txt", b"root")
        vfs.rmtree("/top")

        assert not vfs.exists("/top")
        assert not vfs.exists("/top/mid")
        assert not vfs.exists("/top/mid/bot")
        assert not vfs.exists("/top/mid/bot/file.txt")

    def test_remove_root_raises(self, vfs: VirtualFilesystem) -> None:
        """Removing the root directory raises OSError."""
        with pytest.raises(OSError):
            vfs.rmtree("/")

    def test_remove_nonexistent_raises(self, vfs: VirtualFilesystem) -> None:
        """Removing a nonexistent path raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            vfs.rmtree("/nonexistent")

    def test_remove_does_not_affect_siblings(self, vfs: VirtualFilesystem) -> None:
        """Removing a directory does not affect sibling entries."""
        vfs.write("/parent/keep/file.txt", b"keep")
        vfs.write("/parent/remove/file.txt", b"remove")
        vfs.rmtree("/parent/remove")

        assert not vfs.exists("/parent/remove")
        assert vfs.read("/parent/keep/file.txt") == b"keep"

    def test_remove_empty_dir(self, vfs: VirtualFilesystem) -> None:
        """rmtree can remove an empty directory."""
        vfs.mkdir("/empty")
        vfs.rmtree("/empty")

        assert not vfs.exists("/empty")

    def test_remove_from_seeded_vfs(self, seeded_vfs: VirtualFilesystem) -> None:
        """rmtree works on a sub-tree within a larger filesystem."""
        seeded_vfs.rmtree("/home/user/project")

        assert not seeded_vfs.exists("/home/user/project")
        assert not seeded_vfs.exists("/home/user/project/main.py")
        # Parent and siblings still exist
        assert seeded_vfs.is_dir("/home/user")
        assert seeded_vfs.exists("/home/user/hello.txt")

    def test_rmtree_single_file_in_dir(self, vfs: VirtualFilesystem) -> None:
        """rmtree removes a directory containing exactly one file."""
        vfs.write("/solo/only.txt", b"alone")
        vfs.rmtree("/solo")

        assert not vfs.exists("/solo")
        assert not vfs.exists("/solo/only.txt")
