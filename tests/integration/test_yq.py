"""Integration tests for the yq command."""

from agentsh.api.engine import ShellEngine


class TestYqYamlBasic:
    """Basic YAML input processing."""

    def test_identity(self) -> None:
        engine = ShellEngine(initial_files={"/data.yaml": "name: hello\nage: 30\n"})
        result = engine.run("yq '.' /data.yaml")
        assert "name: hello" in result.stdout
        assert "age: 30" in result.stdout

    def test_field_access(self) -> None:
        engine = ShellEngine(initial_files={"/data.yaml": "name: hello\nage: 30\n"})
        result = engine.run("yq '.name' /data.yaml")
        assert result.stdout.strip() == "hello"

    def test_nested_field(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "server:\n  host: localhost\n  port: 8080\n"}
        )
        result = engine.run("yq '.server.port' /d.yaml")
        assert result.stdout.strip() == "8080"

    def test_array_index(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "items:\n  - alpha\n  - beta\n  - gamma\n"}
        )
        result = engine.run("yq '.items[1]' /d.yaml")
        assert result.stdout.strip() == "beta"

    def test_array_iterate(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "items:\n  - a\n  - b\n  - c\n"})
        result = engine.run("yq '.items[]' /d.yaml")
        assert "a" in result.stdout
        assert "b" in result.stdout
        assert "c" in result.stdout

    def test_keys(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "x: 1\ny: 2\nz: 3\n"})
        result = engine.run("yq 'keys' /d.yaml")
        assert "x" in result.stdout
        assert "y" in result.stdout
        assert "z" in result.stdout

    def test_select(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "- name: a\n  ok: true\n- name: b\n  ok: false\n"}
        )
        result = engine.run("yq '.[] | select(.ok == true) | .name' /d.yaml")
        assert result.stdout.strip() == "a"

    def test_length(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "items:\n  - 1\n  - 2\n  - 3\n"})
        result = engine.run("yq '.items | length' /d.yaml")
        assert result.stdout.strip() == "3"


class TestYqOutputFormats:
    """Output format flags."""

    def test_output_json(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "name: hello\nage: 30\n"})
        result = engine.run("yq -o json '.' /d.yaml")
        assert '"name"' in result.stdout
        assert '"hello"' in result.stdout

    def test_tojson_shorthand(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "x: 1\n"})
        result = engine.run("yq -oj '.' /d.yaml")
        assert '"x"' in result.stdout

    def test_raw_output(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "msg: hello world\n"})
        result = engine.run("yq -r '.msg' /d.yaml")
        assert result.stdout.strip() == "hello world"

    def test_compact_yaml(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "x: 1\ny: 2\n"})
        result = engine.run("yq -c '.' /d.yaml")
        assert result.result.exit_code == 0


class TestYqJsonInput:
    """JSON input auto-detection."""

    def test_json_auto_detect(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"name": "test"}\n'})
        result = engine.run("yq '.name' /d.json")
        assert result.stdout.strip() == "test"

    def test_json_explicit_format(self) -> None:
        engine = ShellEngine(initial_files={"/d.txt": '{"x": 42}\n'})
        result = engine.run("yq -p json '.x' /d.txt")
        assert result.stdout.strip() == "42"


class TestYqTomlInput:
    """TOML input processing."""

    def test_toml_by_extension(self) -> None:
        engine = ShellEngine(
            initial_files={"/cfg.toml": '[server]\nhost = "localhost"\nport = 8080\n'}
        )
        result = engine.run("yq '.server.port' /cfg.toml")
        assert result.stdout.strip() == "8080"

    def test_toml_explicit_format(self) -> None:
        engine = ShellEngine(
            initial_files={"/cfg.txt": 'name = "test"\nversion = "1.0"\n'}
        )
        result = engine.run("yq -p toml '.name' /cfg.txt")
        assert result.stdout.strip() == "test"


class TestYqPipe:
    """Pipe and filter operations."""

    def test_pipe_and_map(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "users:\n  - name: alice\n  - name: bob\n"}
        )
        result = engine.run("yq '.users | map(.name)' /d.yaml")
        assert "alice" in result.stdout
        assert "bob" in result.stdout

    def test_object_construction(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "first: John\nlast: Doe\nage: 30\n"}
        )
        result = engine.run("yq -o json '{name: .first, surname: .last}' /d.yaml")
        assert "John" in result.stdout
        assert "surname" in result.stdout

    def test_stdin(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo 'name: test' | yq '.name'")
        assert result.stdout.strip() == "test"

    def test_null_input(self) -> None:
        engine = ShellEngine()
        result = engine.run("yq -n '{hello: \"world\"}' -o json")
        assert "hello" in result.stdout
        assert "world" in result.stdout
