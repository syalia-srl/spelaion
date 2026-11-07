"""Integration tests for modern search commands: rg, fd, zip."""

from agentsh.api.engine import ShellEngine

# =========================================================================
# rg (ripgrep)
# =========================================================================


class TestRgBasic:
    """Basic rg pattern search."""

    def test_basic_pattern(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/main.py": "import os\nprint('hello')\n",
                "/src/util.py": "def helper():\n    return 42\n",
            }
        )
        result = engine.run("rg hello /src")
        assert "hello" in result.stdout
        assert "main.py" in result.stdout

    def test_no_match_exit_code(self) -> None:
        engine = ShellEngine(initial_files={"/src/main.py": "import os\n"})
        result = engine.run("rg nonexistent /src")
        assert result.result.exit_code == 1

    def test_missing_pattern(self) -> None:
        engine = ShellEngine()
        result = engine.run("rg")
        assert result.result.exit_code == 2

    def test_line_numbers_default_on(self) -> None:
        engine = ShellEngine(initial_files={"/src/main.py": "line1\nline2\nhello\n"})
        result = engine.run("rg hello /src/main.py")
        assert ":3:" in result.stdout

    def test_recursive_by_default(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/src/a.py": "target\n",
                "/project/src/lib/b.py": "target\n",
            }
        )
        result = engine.run("rg target /project")
        assert "a.py" in result.stdout
        assert "b.py" in result.stdout


class TestRgFlags:
    """rg flag behavior."""

    def test_ignore_case(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "Hello World\n"})
        result = engine.run("rg -i hello /f.txt")
        assert "Hello World" in result.stdout

    def test_ignore_case_no_match_without_flag(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "Hello World\n"})
        result = engine.run("rg hello /f.txt")
        assert result.result.exit_code == 1

    def test_files_with_matches(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/a.txt": "foo bar\n",
                "/b.txt": "baz qux\n",
            }
        )
        result = engine.run("rg -l foo /a.txt /b.txt")
        assert "/a.txt" in result.stdout
        assert "/b.txt" not in result.stdout

    def test_count(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "foo\nbar\nfoo baz\n"})
        result = engine.run("rg -c foo /f.txt")
        assert ":2" in result.stdout

    def test_invert_match(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "foo\nbar\nbaz\n"})
        result = engine.run("rg -v foo /f.txt")
        assert "bar" in result.stdout
        assert "baz" in result.stdout
        assert "foo" not in result.stdout.replace("/f.txt", "")

    def test_fixed_strings(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "a.b\na*b\n"})
        result = engine.run("rg -F a.b /f.txt")
        assert "a.b" in result.stdout
        # a*b should NOT match since . is literal
        lines = [
            ln for ln in result.stdout.strip().split("\n") if not ln.endswith("a*b")
        ]
        assert len(lines) >= 1

    def test_word_regexp(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "foo\nfoobar\nbar foo baz\n"})
        result = engine.run("rg -w foo /f.txt")
        assert "foo" in result.stdout
        assert (
            "foobar" not in result.stdout.split("\n")[0] or "bar foo" in result.stdout
        )

    def test_quiet(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "hello\n"})
        result = engine.run("rg -q hello /f.txt")
        assert result.result.exit_code == 0
        assert result.stdout == ""

    def test_only_matching(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "hello world\n"})
        result = engine.run("rg -o hello /f.txt")
        assert "hello" in result.stdout
        assert "world" not in result.stdout

    def test_explicit_pattern_flag(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "hello\n"})
        result = engine.run("rg -e hello /f.txt")
        assert "hello" in result.stdout


class TestRgTypeFilter:
    """rg --type filtering."""

    def test_type_py(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/main.py": "target\n",
                "/src/main.js": "target\n",
                "/src/readme.md": "target\n",
            }
        )
        result = engine.run("rg --type py target /src")
        assert "main.py" in result.stdout
        assert "main.js" not in result.stdout
        assert "readme.md" not in result.stdout

    def test_type_js_includes_jsx(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/app.jsx": "target\n",
                "/src/app.js": "target\n",
                "/src/app.ts": "target\n",
            }
        )
        result = engine.run("rg -t js target /src")
        assert "app.jsx" in result.stdout
        assert "app.js" in result.stdout
        assert "app.ts" not in result.stdout

    def test_unknown_type(self) -> None:
        engine = ShellEngine()
        result = engine.run("rg --type zzz pattern /")
        assert result.result.exit_code == 1


class TestRgHidden:
    """rg hidden file behavior."""

    def test_skip_hidden_by_default(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/.hidden.py": "target\n",
                "/src/visible.py": "target\n",
            }
        )
        result = engine.run("rg target /src")
        assert "visible.py" in result.stdout
        assert ".hidden.py" not in result.stdout

    def test_include_hidden(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/.hidden.py": "target\n",
                "/src/visible.py": "target\n",
            }
        )
        result = engine.run("rg --hidden target /src")
        assert ".hidden.py" in result.stdout
        assert "visible.py" in result.stdout


class TestRgContext:
    """rg context flags."""

    def test_after_context(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "aaa\ntarget\nbbb\nccc\n"})
        result = engine.run("rg -A 1 target /f.txt")
        assert "target" in result.stdout
        assert "bbb" in result.stdout

    def test_before_context(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "aaa\nbbb\ntarget\nccc\n"})
        result = engine.run("rg -B 1 target /f.txt")
        assert "target" in result.stdout
        assert "bbb" in result.stdout

    def test_context(self) -> None:
        engine = ShellEngine(initial_files={"/f.txt": "aaa\nbbb\ntarget\nccc\nddd\n"})
        result = engine.run("rg -C 1 target /f.txt")
        assert "bbb" in result.stdout
        assert "target" in result.stdout
        assert "ccc" in result.stdout


class TestRgGlob:
    """rg --glob filtering."""

    def test_glob_filter(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/main.py": "target\n",
                "/src/test.py": "target\n",
                "/src/readme.md": "target\n",
            }
        )
        result = engine.run("rg -g '*.py' target /src")
        assert "main.py" in result.stdout
        assert "readme.md" not in result.stdout


class TestRgDefaultCwd:
    """rg defaults to cwd when no path given."""

    def test_default_cwd(self) -> None:
        engine = ShellEngine(initial_files={"/home/user/test.txt": "findme\n"})
        result = engine.run("cd /home/user && rg findme")
        assert "findme" in result.stdout


# =========================================================================
# fd
# =========================================================================


class TestFdBasic:
    """Basic fd filename matching."""

    def test_basic_name_match(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/main.py": "",
                "/project/util.py": "",
                "/project/readme.md": "",
            }
        )
        result = engine.run("fd main /project")
        assert "main.py" in result.stdout
        assert "util.py" not in result.stdout

    def test_match_all(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/a.py": "",
                "/project/b.py": "",
            }
        )
        result = engine.run("fd '' /project")
        assert "a.py" in result.stdout
        assert "b.py" in result.stdout

    def test_no_args_matches_all(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/a.txt": "",
                "/b.txt": "",
            }
        )
        # fd with no pattern defaults to matching everything
        result = engine.run("cd / && fd")
        assert "a.txt" in result.stdout


class TestFdTypeFilter:
    """fd -t type filtering."""

    def test_type_file(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "",
                "/project/src/lib/helper.py": "",
            }
        )
        result = engine.run("fd -t f '' /project")
        assert "main.py" in result.stdout
        # directories should not appear
        lines = result.stdout.strip().split("\n")
        for line in lines:
            assert not line.endswith("src") or "." in line

    def test_type_directory(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "",
                "/project/lib/helper.py": "",
            }
        )
        result = engine.run("fd -t d '' /project")
        assert "src" in result.stdout
        assert "lib" in result.stdout


class TestFdExtension:
    """fd -e extension filtering."""

    def test_extension_filter(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/main.py": "",
                "/src/main.js": "",
                "/src/readme.md": "",
            }
        )
        result = engine.run("fd -e py '' /src")
        assert "main.py" in result.stdout
        assert "main.js" not in result.stdout


class TestFdMaxDepth:
    """fd --max-depth filtering."""

    def test_max_depth(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/top.py": "",
                "/project/src/mid.py": "",
                "/project/src/lib/deep.py": "",
            }
        )
        result = engine.run("fd -d 1 '' /project")
        assert "top.py" in result.stdout
        assert "src" in result.stdout
        assert "mid.py" not in result.stdout
        assert "deep.py" not in result.stdout


class TestFdHidden:
    """fd hidden file behavior."""

    def test_skip_hidden_by_default(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/.hidden": "",
                "/src/visible.py": "",
            }
        )
        result = engine.run("fd '' /src")
        assert "visible.py" in result.stdout
        assert ".hidden" not in result.stdout

    def test_include_hidden(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/src/.hidden": "",
                "/src/visible.py": "",
            }
        )
        result = engine.run("fd -H '' /src")
        assert ".hidden" in result.stdout
        assert "visible.py" in result.stdout


class TestFdFullPath:
    """fd --full-path matching."""

    def test_full_path_match(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "",
                "/project/lib/main.py": "",
            }
        )
        result = engine.run("fd --full-path src/main /project")
        assert "src/main.py" in result.stdout
        # lib/main.py should not match since pattern is "src/main"
        lines = result.stdout.strip().split("\n")
        assert len(lines) == 1


# =========================================================================
# zip
# =========================================================================


class TestZipBasic:
    """Basic zip creation."""

    def test_create_zip(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/data/a.txt": "hello\n",
                "/data/b.txt": "world\n",
            }
        )
        result = engine.run("zip /out.zip /data/a.txt /data/b.txt && unzip -l /out.zip")
        assert result.result.exit_code == 0
        assert "a.txt" in result.stdout
        assert "b.txt" in result.stdout

    def test_zip_missing_archive_name(self) -> None:
        engine = ShellEngine()
        result = engine.run("zip")
        assert result.result.exit_code == 1

    def test_zip_missing_files(self) -> None:
        engine = ShellEngine()
        result = engine.run("zip archive.zip")
        assert result.result.exit_code == 1

    def test_zip_nonexistent_file(self) -> None:
        engine = ShellEngine()
        result = engine.run("zip /out.zip /no/such/file")
        assert result.result.exit_code == 1


class TestZipRecursive:
    """zip -r recursive mode."""

    def test_recursive_zip(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "print('hello')\n",
                "/project/src/lib/util.py": "def f(): pass\n",
            }
        )
        result = engine.run("zip -r /out.zip /project/src && unzip -l /out.zip")
        assert result.result.exit_code == 0
        assert "main.py" in result.stdout
        assert "util.py" in result.stdout

    def test_dir_without_r_flag(self) -> None:
        engine = ShellEngine(initial_files={"/project/src/main.py": "hello\n"})
        result = engine.run("zip /out.zip /project/src")
        # Should warn about directory without -r
        assert "is a directory" in result.stderr


class TestZipJunkPaths:
    """zip -j junk paths mode."""

    def test_junk_paths(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/deep/nested/dir/file.txt": "content\n",
            }
        )
        result = engine.run(
            "zip -j /out.zip /deep/nested/dir/file.txt && unzip -l /out.zip"
        )
        assert result.result.exit_code == 0
        assert "file.txt" in result.stdout


class TestZipRoundTrip:
    """zip + unzip round trip."""

    def test_roundtrip(self) -> None:
        engine = ShellEngine(initial_files={"/src/hello.txt": "hello world\n"})
        result = engine.run(
            "zip /archive.zip /src/hello.txt && "
            "unzip -d /out /archive.zip && "
            "cat /out/src/hello.txt"
        )
        assert result.stdout.strip().endswith("hello world")
