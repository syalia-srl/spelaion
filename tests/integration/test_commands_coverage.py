"""Additional integration tests for trivial.py and modern_search.py."""

from agentsh.api.engine import ShellEngine

# ===========================================================================
# trivial.py coverage tests
# ===========================================================================


# ---------------------------------------------------------------------------
# tac: multiple files, error handling
# ---------------------------------------------------------------------------


class TestTacCoverage:
    def test_tac_multiple_files(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/tmp/a.txt": "1\n2\n",
                "/tmp/b.txt": "3\n4\n",
            }
        )
        result = engine.run("tac /tmp/a.txt /tmp/b.txt")
        # tac reverses the concatenated lines
        assert result.result.exit_code == 0
        assert "4" in result.stdout
        assert "1" in result.stdout

    def test_tac_missing_file(self) -> None:
        engine = ShellEngine()
        result = engine.run("tac /no/such/file")
        assert "No such file" in result.stderr


# ---------------------------------------------------------------------------
# sha1sum: error paths
# ---------------------------------------------------------------------------


class TestSha1sumCoverage:
    def test_sha1sum_multiple_files(self) -> None:
        engine = ShellEngine(
            initial_files={
                "/tmp/a.txt": "aaa",
                "/tmp/b.txt": "bbb",
            }
        )
        result = engine.run("sha1sum /tmp/a.txt /tmp/b.txt")
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 2
        assert "/tmp/a.txt" in lines[0]
        assert "/tmp/b.txt" in lines[1]

    def test_sha1sum_directory_skipped(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/dir/file.txt": "content"})
        result = engine.run("sha1sum /tmp/dir")
        assert "Is a directory" in result.stderr


# ---------------------------------------------------------------------------
# shuf: error paths and options
# ---------------------------------------------------------------------------


class TestShufCoverage:
    def test_shuf_n_invalid(self) -> None:
        """shuf -n with invalid count -> lines 99-101."""
        engine = ShellEngine()
        result = engine.run("shuf -n abc -e a b c")
        assert result.result.exit_code == 1
        assert "invalid line count" in result.stderr

    def test_shuf_i_invalid_range(self) -> None:
        """shuf -i with invalid range format -> lines 109-110."""
        engine = ShellEngine()
        result = engine.run("shuf -i notarange")
        assert result.result.exit_code == 1
        assert "invalid input range" in result.stderr

    def test_shuf_i_range_with_n(self) -> None:
        """shuf -i range combined with -n limit."""
        engine = ShellEngine()
        result = engine.run("shuf -i 1-10 -n 3")
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 3
        for line in lines:
            val = int(line)
            assert 1 <= val <= 10

    def test_shuf_e_with_words_and_n(self) -> None:
        """shuf -e with words and -n limit."""
        engine = ShellEngine()
        result = engine.run("shuf -n 2 -e alpha beta gamma delta")
        lines = result.stdout.strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            assert line in ("alpha", "beta", "gamma", "delta")

    def test_shuf_missing_file(self) -> None:
        """shuf with a file that doesn't exist -> line 125."""
        engine = ShellEngine()
        result = engine.run("shuf /no/such/file.txt")
        assert result.result.exit_code != 0
        assert "No such file" in result.stderr


# ---------------------------------------------------------------------------
# file: binary detection, various extensions, error paths
# ---------------------------------------------------------------------------


class TestFileCoverage:
    def test_file_no_args(self) -> None:
        """file with no arguments -> lines 219-220."""
        engine = ShellEngine()
        result = engine.run("file")
        assert result.result.exit_code == 1
        assert "missing operand" in result.stderr

    def test_file_xml_content(self) -> None:
        """file detecting XML content -> line 193."""
        engine = ShellEngine(
            initial_files={"/tmp/doc.dat": "<?xml version='1.0'?>\n<root/>\n"}
        )
        result = engine.run("file /tmp/doc.dat")
        assert "XML document" in result.stdout

    def test_file_zip_magic(self) -> None:
        """file detecting Zip archive via PK magic bytes -> line 195."""
        engine = ShellEngine(
            initial_files={"/tmp/archive.dat": b"PK\x03\x04fakecontent"}
        )
        result = engine.run("file /tmp/archive.dat")
        assert "Zip archive" in result.stdout

    def test_file_gzip_magic(self) -> None:
        """file detecting gzip compressed data -> line 197."""
        engine = ShellEngine(
            initial_files={"/tmp/compressed.dat": b"\x1f\x8b\x08\x00fakedata"}
        )
        result = engine.run("file /tmp/compressed.dat")
        assert "gzip compressed data" in result.stdout

    def test_file_invalid_json_content(self) -> None:
        """file with content starting with { but not valid JSON -> lines 187-188."""
        engine = ShellEngine(initial_files={"/tmp/bad.dat": "{not valid json at all"})
        result = engine.run("file /tmp/bad.dat")
        # Should fallback to ASCII text since { is ASCII
        assert result.result.exit_code == 0
        assert "bad.dat:" in result.stdout

    def test_file_binary_data(self) -> None:
        """file detecting binary data -> lines 207-210."""
        engine = ShellEngine(
            initial_files={"/tmp/binary.dat": b"\x00\x01\x02\x80\x90\xff"}
        )
        result = engine.run("file /tmp/binary.dat")
        assert "data" in result.stdout

    def test_file_ascii_text_no_extension(self) -> None:
        """file detecting ASCII text with no known extension -> lines 207-208."""
        engine = ShellEngine(initial_files={"/tmp/noext": "plain ascii text\n"})
        result = engine.run("file /tmp/noext")
        assert "ASCII text" in result.stdout

    def test_file_go_extension(self) -> None:
        """file detecting Go source by extension."""
        engine = ShellEngine(initial_files={"/tmp/main.go": "package main\n"})
        result = engine.run("file /tmp/main.go")
        assert "Go source" in result.stdout

    def test_file_rust_extension(self) -> None:
        """file detecting Rust source by extension."""
        engine = ShellEngine(initial_files={"/tmp/lib.rs": "fn main() {}\n"})
        result = engine.run("file /tmp/lib.rs")
        assert "Rust source" in result.stdout

    def test_file_java_extension(self) -> None:
        """file detecting Java source by extension."""
        engine = ShellEngine(initial_files={"/tmp/App.java": "class App {}\n"})
        result = engine.run("file /tmp/App.java")
        assert "Java source" in result.stdout

    def test_file_c_extension(self) -> None:
        """file detecting C source by extension."""
        engine = ShellEngine(initial_files={"/tmp/main.c": "int main() {}\n"})
        result = engine.run("file /tmp/main.c")
        assert "C source" in result.stdout

    def test_file_html_extension(self) -> None:
        """file detecting HTML document by extension."""
        engine = ShellEngine(initial_files={"/tmp/page.html": "<h1>Hi</h1>\n"})
        result = engine.run("file /tmp/page.html")
        assert "HTML document" in result.stdout

    def test_file_css_extension(self) -> None:
        """file detecting CSS by extension."""
        engine = ShellEngine(initial_files={"/tmp/style.css": "body { color: red; }\n"})
        result = engine.run("file /tmp/style.css")
        assert "CSS" in result.stdout

    def test_file_sql_extension(self) -> None:
        """file detecting SQL by extension."""
        engine = ShellEngine(initial_files={"/tmp/query.sql": "SELECT * FROM t;\n"})
        result = engine.run("file /tmp/query.sql")
        assert "SQL" in result.stdout

    def test_file_array_json_content(self) -> None:
        """file detecting JSON data from array start."""
        engine = ShellEngine(initial_files={"/tmp/data.dat": "[1, 2, 3]\n"})
        result = engine.run("file /tmp/data.dat")
        assert "JSON data" in result.stdout

    def test_file_invalid_array_json(self) -> None:
        """file with content starting with [ but not valid JSON -> lines 187-188."""
        engine = ShellEngine(initial_files={"/tmp/bad2.dat": "[not valid json"})
        result = engine.run("file /tmp/bad2.dat")
        assert result.result.exit_code == 0


# ---------------------------------------------------------------------------
# column: error paths, -s delimiter
# ---------------------------------------------------------------------------


class TestColumnCoverage:
    def test_column_table_empty_input(self) -> None:
        """column -t with empty file -> line 279."""
        engine = ShellEngine(initial_files={"/tmp/empty.txt": ""})
        result = engine.run("column -t /tmp/empty.txt")
        assert result.result.exit_code == 0

    def test_column_custom_separator(self) -> None:
        """column -t -s with custom separator -> line 261."""
        engine = ShellEngine(initial_files={"/tmp/data.csv": "a|bb|ccc\ndddd|e|ff\n"})
        result = engine.run("column -t -s '|' /tmp/data.csv")
        lines = result.stdout.splitlines()
        assert len(lines) == 2
        # Columns should be aligned
        assert "a" in lines[0]
        assert "dddd" in lines[1]


# ---------------------------------------------------------------------------
# fmt: edge cases
# ---------------------------------------------------------------------------


class TestFmtCoverage:
    def test_fmt_invalid_width(self) -> None:
        """fmt -w with invalid width -> lines 319-321."""
        engine = ShellEngine(initial_files={"/tmp/text.txt": "hello\n"})
        result = engine.run("fmt -w notanumber /tmp/text.txt")
        assert result.result.exit_code == 1
        assert "invalid width" in result.stderr

    def test_fmt_empty_paragraph_in_text(self) -> None:
        """fmt with multiple blank lines between paragraphs -> lines 334-335."""
        text = "First paragraph words here.\n\n\n\nSecond paragraph words here.\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": text})
        result = engine.run("fmt /tmp/text.txt")
        assert "First paragraph" in result.stdout
        assert "Second paragraph" in result.stdout

    def test_fmt_leading_blank_lines(self) -> None:
        """fmt with text that starts with blank lines -> lines 334-335."""
        text = "\n\nActual content here.\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": text})
        result = engine.run("fmt /tmp/text.txt")
        assert "Actual content" in result.stdout

    def test_fmt_trailing_blank_lines(self) -> None:
        """fmt with text ending in multiple newlines -> lines 334-335."""
        text = "Content here.\n\n\n"
        engine = ShellEngine(initial_files={"/tmp/text.txt": text})
        result = engine.run("fmt /tmp/text.txt")
        assert "Content here." in result.stdout

    def test_fmt_stdin(self) -> None:
        """fmt reading from stdin."""
        engine = ShellEngine()
        result = engine.run("echo 'hello world this is a test' | fmt -w 15")
        assert result.result.exit_code == 0


# ---------------------------------------------------------------------------
# envsubst: ${VAR} form
# ---------------------------------------------------------------------------


class TestEnvsubstCoverage:
    def test_envsubst_braced_and_unbraced(self) -> None:
        """envsubst with both ${VAR} and $VAR forms."""
        engine = ShellEngine()
        result = engine.run("A=hello; B=world; echo '${A} $B' | envsubst")
        assert "hello" in result.stdout
        assert "world" in result.stdout

    def test_envsubst_multiple_vars(self) -> None:
        """envsubst with multiple variables in one line."""
        engine = ShellEngine()
        result = engine.run("X=1; Y=2; echo '$X+$Y=${X}${Y}' | envsubst")
        assert "1+2=12" in result.stdout


# ---------------------------------------------------------------------------
# install: -m mode, -d dir creation, errors
# ---------------------------------------------------------------------------


class TestInstallCoverage:
    def test_install_mode_flag(self) -> None:
        """install with -m mode flag on file copy -> lines 428-430."""
        engine = ShellEngine(initial_files={"/tmp/src.txt": "data"})
        result = engine.run("install -m 755 /tmp/src.txt /tmp/dst.txt")
        assert result.result.exit_code == 0
        r2 = engine.run("cat /tmp/dst.txt")
        assert r2.stdout == "data"

    def test_install_d_with_mode(self) -> None:
        """install -d with -m mode -> lines 399-402."""
        engine = ShellEngine()
        result = engine.run("install -d -m 700 /tmp/mydir")
        assert result.result.exit_code == 0
        r2 = engine.run("test -d /tmp/mydir && echo ok")
        assert "ok" in r2.stdout

    def test_install_invalid_mode(self) -> None:
        """install -m with invalid mode -> lines 387-389."""
        engine = ShellEngine(initial_files={"/tmp/src.txt": "data"})
        result = engine.run("install -m notoctal /tmp/src.txt /tmp/dst.txt")
        assert result.result.exit_code == 1
        assert "invalid mode" in result.stderr

    def test_install_missing_operand(self) -> None:
        """install with only one positional arg -> lines 407-408."""
        engine = ShellEngine()
        result = engine.run("install /tmp/src.txt")
        assert result.result.exit_code == 1
        assert "missing file operand" in result.stderr

    def test_install_copy_to_existing_directory(self) -> None:
        """install source to existing directory -> copy_file detects dir."""
        engine = ShellEngine(
            initial_files={
                "/tmp/src.txt": "data",
                "/tmp/destdir/placeholder": "x",
            }
        )
        result = engine.run("install /tmp/src.txt /tmp/destdir")
        assert result.result.exit_code == 0
        r2 = engine.run("cat /tmp/destdir/src.txt")
        assert r2.stdout == "data"

    def test_install_source_is_directory(self) -> None:
        """install where source is a directory -> lines 423-425."""
        engine = ShellEngine(initial_files={"/tmp/srcdir/file.txt": "data"})
        result = engine.run("install /tmp/srcdir /tmp/dst.txt")
        assert result.result.exit_code == 1
        assert "Is a directory" in result.stderr


# ===========================================================================
# modern_search.py coverage tests
# ===========================================================================


# ---------------------------------------------------------------------------
# rg: various type filters
# ---------------------------------------------------------------------------


class TestRgTypeCoverage:
    def test_rg_type_ts(self) -> None:
        """rg --type ts filters TypeScript files -> line 148."""
        engine = ShellEngine(
            initial_files={
                "/src/app.ts": "target\n",
                "/src/comp.tsx": "target\n",
                "/src/main.py": "target\n",
            }
        )
        result = engine.run("rg --type ts target /src")
        assert "app.ts" in result.stdout
        assert "comp.tsx" in result.stdout
        assert "main.py" not in result.stdout

    def test_rg_type_go(self) -> None:
        """rg --type go filters Go files."""
        engine = ShellEngine(
            initial_files={
                "/src/main.go": "target\n",
                "/src/main.py": "target\n",
            }
        )
        result = engine.run("rg --type go target /src")
        assert "main.go" in result.stdout
        assert "main.py" not in result.stdout

    def test_rg_type_rs(self) -> None:
        """rg --type rs filters Rust files."""
        engine = ShellEngine(
            initial_files={
                "/src/lib.rs": "target\n",
                "/src/main.py": "target\n",
            }
        )
        result = engine.run("rg --type rs target /src")
        assert "lib.rs" in result.stdout
        assert "main.py" not in result.stdout


# ---------------------------------------------------------------------------
# rg: flag coverage
# ---------------------------------------------------------------------------


class TestRgFlagsCoverage:
    def test_rg_no_line_number(self) -> None:
        """rg --no-line-number -> line 135."""
        engine = ShellEngine(initial_files={"/f.txt": "aaa\ntarget\nbbb\n"})
        result = engine.run("rg --no-line-number target /f.txt")
        # Output should be file:line without line number
        assert "target" in result.stdout
        # Should not have :2: pattern
        assert ":2:" not in result.stdout

    def test_rg_line_number_explicit(self) -> None:
        """rg -n (explicit line numbers) -> line 133."""
        engine = ShellEngine(initial_files={"/f.txt": "aaa\ntarget\nbbb\n"})
        result = engine.run("rg -n target /f.txt")
        assert ":2:" in result.stdout

    def test_rg_no_heading(self) -> None:
        """rg --no-heading is a no-op -> line 131."""
        engine = ShellEngine(initial_files={"/f.txt": "target\n"})
        result = engine.run("rg --no-heading target /f.txt")
        assert "target" in result.stdout

    def test_rg_color_flag(self) -> None:
        """rg --color=never is a no-op -> line 137."""
        engine = ShellEngine(initial_files={"/f.txt": "target\n"})
        result = engine.run("rg --color=never target /f.txt")
        assert "target" in result.stdout

    def test_rg_invalid_regex(self) -> None:
        """rg with invalid regex pattern -> lines 181-183."""
        engine = ShellEngine(initial_files={"/f.txt": "content\n"})
        result = engine.run("rg '[invalid' /f.txt")
        assert result.result.exit_code == 2
        assert "invalid regex" in result.stderr

    def test_rg_missing_path(self) -> None:
        """rg searching a nonexistent path -> line 198."""
        engine = ShellEngine()
        result = engine.run("rg pattern /no/such/path")
        assert "No such file or directory" in result.stderr

    def test_rg_e_explicit_pattern(self) -> None:
        """rg -e explicit pattern flag -> lines 138-140."""
        engine = ShellEngine(initial_files={"/f.txt": "hello world\n"})
        result = engine.run("rg -e hello -e world /f.txt")
        assert "hello world" in result.stdout

    def test_rg_only_matching_output(self) -> None:
        """rg -o only-matching -> line 127, line 282-284."""
        engine = ShellEngine(initial_files={"/f.txt": "foo bar baz\n"})
        result = engine.run("rg -o bar /f.txt")
        assert "bar" in result.stdout
        # should not include surrounding text
        assert "foo" not in result.stdout
        assert "baz" not in result.stdout

    def test_rg_invert_match(self) -> None:
        """rg -v invert-match."""
        engine = ShellEngine(initial_files={"/f.txt": "aaa\nbbb\nccc\n"})
        result = engine.run("rg -v bbb /f.txt")
        assert "aaa" in result.stdout
        assert "ccc" in result.stdout

    def test_rg_quiet_no_match(self) -> None:
        """rg -q quiet with no match -> exit code 1."""
        engine = ShellEngine(initial_files={"/f.txt": "hello\n"})
        result = engine.run("rg -q nomatch /f.txt")
        assert result.result.exit_code == 1
        assert result.stdout == ""

    def test_rg_fixed_strings(self) -> None:
        """rg -F fixed-strings with regex metacharacters."""
        engine = ShellEngine(initial_files={"/f.txt": "a.b.c\nabc\n"})
        result = engine.run("rg -F a.b.c /f.txt")
        assert "a.b.c" in result.stdout

    def test_rg_glob_filter(self) -> None:
        """rg --glob filtering -> lines 149-151."""
        engine = ShellEngine(
            initial_files={
                "/src/main.py": "target\n",
                "/src/test.js": "target\n",
            }
        )
        result = engine.run("rg --glob '*.py' target /src")
        assert "main.py" in result.stdout
        assert "test.js" not in result.stdout


# ---------------------------------------------------------------------------
# rg: context separator
# ---------------------------------------------------------------------------


class TestRgContextCoverage:
    def test_rg_context_separator(self) -> None:
        """rg context with separator between groups -> line 240."""
        engine = ShellEngine(
            initial_files={"/f.txt": "aaa\ntarget1\nbbb\nccc\nddd\ntarget2\neee\n"}
        )
        result = engine.run("rg -A 0 -B 0 target /f.txt")
        assert "target1" in result.stdout
        assert "target2" in result.stdout

    def test_rg_context_gap_separator(self) -> None:
        """rg -C with non-contiguous matches produces -- separator -> line 240."""
        engine = ShellEngine(
            initial_files={
                "/f.txt": ("line1\nmatch1\nline3\nline4\nline5\nline6\nmatch2\nline8\n")
            }
        )
        result = engine.run("rg -C 1 match /f.txt")
        assert "match1" in result.stdout
        assert "match2" in result.stdout
        assert "--\n" in result.stdout


# ---------------------------------------------------------------------------
# fd: --full-path, --exec, -d max-depth, regex, error paths
# ---------------------------------------------------------------------------


class TestFdCoverage:
    def test_fd_max_depth_dir(self) -> None:
        """fd -d max-depth filtering for directories -> lines 322-325, 374."""
        engine = ShellEngine(
            initial_files={
                "/project/top.py": "",
                "/project/a/mid.py": "",
                "/project/a/b/deep.py": "",
            }
        )
        result = engine.run("fd -t d -d 1 '' /project")
        assert "a" in result.stdout
        # nested b should not appear at depth 1
        lines = result.stdout.strip().splitlines()
        assert not any(line.strip() == "b" for line in lines if "/" not in line.strip())

    def test_fd_max_depth_files(self) -> None:
        """fd -d max-depth filtering for files -> line 395."""
        engine = ShellEngine(
            initial_files={
                "/project/top.py": "",
                "/project/a/mid.py": "",
                "/project/a/b/deep.py": "",
            }
        )
        result = engine.run("fd -t f -d 1 '' /project")
        assert "top.py" in result.stdout
        assert "mid.py" not in result.stdout
        assert "deep.py" not in result.stdout

    def test_fd_full_path_match(self) -> None:
        """fd --full-path -> line 327, line 404."""
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "",
                "/project/lib/main.py": "",
            }
        )
        result = engine.run("fd --full-path 'src.*main' /project")
        assert "src/main.py" in result.stdout
        lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
        assert len(lines) == 1

    def test_fd_exec(self) -> None:
        """fd --exec runs command for each match -> lines 329-334, 431-441."""
        engine = ShellEngine(
            initial_files={
                "/project/a.txt": "hello\n",
                "/project/b.txt": "world\n",
            }
        )
        result = engine.run("cd /project && fd -t f '' . --exec echo {}")
        # Should echo display path for each file
        assert "a.txt" in result.stdout or "b.txt" in result.stdout

    def test_fd_invalid_regex(self) -> None:
        """fd with invalid regex -> lines 351-353."""
        engine = ShellEngine(initial_files={"/project/a.txt": ""})
        result = engine.run("fd '[invalid' /project")
        assert result.result.exit_code == 1
        assert "invalid regex" in result.stderr

    def test_fd_nonexistent_path(self) -> None:
        """fd with nonexistent path -> lines 358-359."""
        engine = ShellEngine()
        result = engine.run("fd pattern /no/such/path")
        assert "No such file or directory" in result.stderr

    def test_fd_no_ignore(self) -> None:
        """fd -I (no-ignore) flag is accepted -> line 322."""
        engine = ShellEngine(initial_files={"/project/a.txt": ""})
        result = engine.run("fd -I '' /project")
        assert "a.txt" in result.stdout

    def test_fd_hidden_dir_filtering(self) -> None:
        """fd skipping hidden directories -> line 376."""
        engine = ShellEngine(
            initial_files={
                "/src/.hidden/secret.py": "content\n",
                "/src/visible/main.py": "content\n",
            }
        )
        result = engine.run("fd -t f '' /src")
        assert "main.py" in result.stdout
        assert "secret.py" not in result.stdout


# ---------------------------------------------------------------------------
# zip: -r recursive, -j junk paths, error handling
# ---------------------------------------------------------------------------


class TestZipCoverage:
    def test_zip_recursive_junk_paths(self) -> None:
        """zip -r -j recursive with junk paths -> line 495."""
        engine = ShellEngine(
            initial_files={
                "/project/src/main.py": "print('hello')\n",
                "/project/src/lib/util.py": "def f(): pass\n",
            }
        )
        result = engine.run("zip -r -j /out.zip /project/src && unzip -l /out.zip")
        assert result.result.exit_code == 0
        # Files should be stored without directory paths
        assert "main.py" in result.stdout
        assert "util.py" in result.stdout

    def test_zip_single_file_junk_paths(self) -> None:
        """zip -j with a single file."""
        engine = ShellEngine(initial_files={"/deep/path/to/file.txt": "content\n"})
        result = engine.run(
            "zip -j /out.zip /deep/path/to/file.txt && unzip -l /out.zip"
        )
        assert result.result.exit_code == 0
        assert "file.txt" in result.stdout
