"""Integration tests for trivial utility commands."""

import re

from agentsh.api.engine import ShellEngine

# ---------------------------------------------------------------------------
# tac
# ---------------------------------------------------------------------------


class TestTac:
    def test_reverse_lines(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/data.txt": "a\nb\nc\n"})
        result = engine.run("tac /tmp/data.txt")
        assert result.stdout == "c\nb\na\n"

    def test_reverse_stdin_via_pipe(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/abc.txt": "x\ny\nz\n"})
        result = engine.run("cat /tmp/abc.txt | tac")
        assert result.stdout == "z\ny\nx\n"

    def test_reverse_single_line(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/one.txt": "only\n"})
        result = engine.run("tac /tmp/one.txt")
        assert result.stdout == "only\n"


# ---------------------------------------------------------------------------
# sha1sum
# ---------------------------------------------------------------------------


class TestSha1sum:
    def test_sha1_of_file(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/hello.txt": "hello\n"})
        result = engine.run("sha1sum /tmp/hello.txt")
        # sha1 of b"hello\n" is f572d396fae9206628714fb2ce00f72e94f2258f
        assert "f572d396fae9206628714fb2ce00f72e94f2258f" in result.stdout
        assert "/tmp/hello.txt" in result.stdout

    def test_sha1_of_stdin(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo -n abc | sha1sum")
        # sha1 of b"abc" is a9993e364706816aba3e25717850c26c9cd0d89d
        assert "a9993e364706816aba3e25717850c26c9cd0d89d" in result.stdout

    def test_sha1_missing_file(self) -> None:
        engine = ShellEngine()
        result = engine.run("sha1sum /no/such/file")
        assert "No such file" in result.stderr


# ---------------------------------------------------------------------------
# uuidgen
# ---------------------------------------------------------------------------


class TestUuidgen:
    def test_generates_uuid(self) -> None:
        engine = ShellEngine()
        result = engine.run("uuidgen")
        line = result.stdout.strip()
        # UUID v4 format: 8-4-4-4-12 hex chars
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            line,
        )

    def test_generates_different_uuids(self) -> None:
        engine = ShellEngine()
        r1 = engine.run("uuidgen")
        r2 = engine.run("uuidgen")
        assert r1.stdout.strip() != r2.stdout.strip()

    def test_flag_r(self) -> None:
        engine = ShellEngine()
        result = engine.run("uuidgen -r")
        line = result.stdout.strip()
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            line,
        )


# ---------------------------------------------------------------------------
# shuf
# ---------------------------------------------------------------------------


class TestShuf:
    def test_shuffle_file(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/nums.txt": "1\n2\n3\n4\n5\n"})
        result = engine.run("shuf /tmp/nums.txt")
        lines = result.stdout.strip().splitlines()
        assert sorted(lines) == ["1", "2", "3", "4", "5"]

    def test_shuffle_n(self) -> None:
        engine = ShellEngine(
            initial_files={"/tmp/nums.txt": "1\n2\n3\n4\n5\n6\n7\n8\n9\n10\n"}
        )
        result = engine.run("shuf -n 3 /tmp/nums.txt")
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 3

    def test_shuffle_echo(self) -> None:
        engine = ShellEngine()
        result = engine.run("shuf -e alpha beta gamma")
        lines = result.stdout.strip().splitlines()
        assert sorted(lines) == ["alpha", "beta", "gamma"]

    def test_shuffle_range(self) -> None:
        engine = ShellEngine()
        result = engine.run("shuf -i 1-5")
        lines = result.stdout.strip().splitlines()
        assert sorted(lines, key=int) == ["1", "2", "3", "4", "5"]


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------


class TestFileCommand:
    def test_empty_file(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/empty": ""})
        result = engine.run("file /tmp/empty")
        assert "empty" in result.stdout

    def test_shebang(self) -> None:
        engine = ShellEngine(
            initial_files={"/tmp/script": "#!/usr/bin/env python3\nprint('hi')\n"}
        )
        result = engine.run("file /tmp/script")
        assert "script" in result.stdout
        assert "python3" in result.stdout

    def test_json_detection(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/data.json": '{"key": "value"}\n'})
        result = engine.run("file /tmp/data.json")
        assert "JSON data" in result.stdout

    def test_python_extension(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/code.py": "x = 1\n"})
        result = engine.run("file /tmp/code.py")
        assert "Python script" in result.stdout

    def test_yaml_content(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/config.txt": "---\nfoo: bar\n"})
        result = engine.run("file /tmp/config.txt")
        assert "YAML data" in result.stdout

    def test_directory(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/dir/file": "x"})
        result = engine.run("file /tmp/dir")
        assert "directory" in result.stdout

    def test_missing_file(self) -> None:
        engine = ShellEngine()
        result = engine.run("file /no/such")
        assert "No such file" in result.stderr


# ---------------------------------------------------------------------------
# column
# ---------------------------------------------------------------------------


class TestColumn:
    def test_passthrough_no_flag(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/data.txt": "hello world\n"})
        result = engine.run("column /tmp/data.txt")
        assert result.stdout == "hello world\n"

    def test_table_mode(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/data.txt": "a bb\nccc d\n"})
        result = engine.run("column -t /tmp/data.txt")
        lines = result.stdout.splitlines()
        assert len(lines) == 2
        # Columns should be aligned
        assert "a" in lines[0]
        assert "bb" in lines[0]

    def test_custom_separator(self) -> None:
        engine = ShellEngine(
            initial_files={"/tmp/csv.txt": "one:two:three\na:bb:ccc\n"}
        )
        result = engine.run("column -t -s : /tmp/csv.txt")
        lines = result.stdout.splitlines()
        assert len(lines) == 2
        # Check alignment — first column should be padded
        assert lines[0].startswith("one")
        assert lines[1].startswith("a  ")


# ---------------------------------------------------------------------------
# fmt
# ---------------------------------------------------------------------------


class TestFmt:
    def test_reformat_paragraph(self) -> None:
        long_line = "word " * 30 + "\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": long_line})
        result = engine.run("fmt -w 40 /tmp/text.txt")
        for line in result.stdout.splitlines():
            assert len(line) <= 40

    def test_preserves_paragraph_break(self) -> None:
        text = "First paragraph.\n\nSecond paragraph.\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": text})
        result = engine.run("fmt /tmp/text.txt")
        assert "First paragraph." in result.stdout
        assert "Second paragraph." in result.stdout

    def test_default_width(self) -> None:
        long_line = "word " * 50 + "\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": long_line})
        result = engine.run("fmt /tmp/text.txt")
        for line in result.stdout.splitlines():
            assert len(line) <= 75


# ---------------------------------------------------------------------------
# envsubst
# ---------------------------------------------------------------------------


class TestEnvsubst:
    def test_substitute_dollar_var(self) -> None:
        engine = ShellEngine()
        result = engine.run("NAME=world; echo 'Hello $NAME' | envsubst")
        assert "Hello world" in result.stdout

    def test_substitute_braced_var(self) -> None:
        engine = ShellEngine()
        result = engine.run("FOO=bar; echo '${FOO}_baz' | envsubst")
        assert "bar_baz" in result.stdout

    def test_unset_var_becomes_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo 'hi $MISSING there' | envsubst")
        assert "hi  there" in result.stdout


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------


class TestInstall:
    def test_copy_file(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/src.txt": "data"})
        result = engine.run("install /tmp/src.txt /tmp/dst.txt")
        assert result.result.exit_code == 0
        r2 = engine.run("cat /tmp/dst.txt")
        assert r2.stdout == "data"

    def test_create_directory(self) -> None:
        engine = ShellEngine()
        result = engine.run("install -d /tmp/a/b/c")
        assert result.result.exit_code == 0
        r2 = engine.run("test -d /tmp/a/b/c && echo ok")
        assert "ok" in r2.stdout

    def test_missing_source(self) -> None:
        engine = ShellEngine()
        result = engine.run("install /no/such /tmp/dest")
        assert result.result.exit_code != 0
        assert "No such file" in result.stderr
