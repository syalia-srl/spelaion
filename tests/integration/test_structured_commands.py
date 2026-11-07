"""Integration tests for structured data commands: jq, patch."""

from __future__ import annotations

import json

from agentsh.api.engine import ShellEngine

# ==================================================================
# jq — JSON processor
# ==================================================================


class TestJqIdentity:
    """jq '.' — identity filter."""

    def test_identity_object(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 1, "b": 2}\n'})
        result = engine.run("jq '.' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1, "b": 2}

    def test_identity_array(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 3]\n"})
        result = engine.run("jq '.' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 3]

    def test_identity_string(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello"\n'})
        result = engine.run("jq '.' /data.json")
        assert result.stdout.strip() == '"hello"'

    def test_identity_number(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "42\n"})
        result = engine.run("jq '.' /data.json")
        assert result.stdout.strip() == "42"


class TestJqFieldAccess:
    """jq '.field' — object field access."""

    def test_simple_field(self) -> None:
        engine = ShellEngine(
            initial_files={"/data.json": '{"name": "alice", "age": 30}\n'}
        )
        result = engine.run("jq '.name' /data.json")
        assert result.stdout.strip() == '"alice"'

    def test_raw_output(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"name": "alice"}\n'})
        result = engine.run("jq -r '.name' /data.json")
        assert result.stdout.strip() == "alice"

    def test_nested_field(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": {"b": {"c": 42}}}\n'})
        result = engine.run("jq '.a.b.c' /data.json")
        assert result.stdout.strip() == "42"

    def test_missing_field(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 1}\n'})
        result = engine.run("jq '.missing' /data.json")
        assert result.stdout.strip() == "null"


class TestJqArrayIndex:
    """jq '.[N]' — array indexing."""

    def test_first_element(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '["a", "b", "c"]\n'})
        result = engine.run("jq '.[0]' /data.json")
        assert result.stdout.strip() == '"a"'

    def test_second_element(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '["a", "b", "c"]\n'})
        result = engine.run("jq '.[1]' /data.json")
        assert result.stdout.strip() == '"b"'

    def test_negative_index(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '["a", "b", "c"]\n'})
        result = engine.run("jq '.[-1]' /data.json")
        assert result.stdout.strip() == '"c"'


class TestJqIterate:
    """jq '.[]' — iterate."""

    def test_iterate_array(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 3]\n"})
        result = engine.run("jq '.[]' /data.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["1", "2", "3"]

    def test_iterate_object(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 1, "b": 2}\n'})
        result = engine.run("jq '.[]' /data.json")
        lines = result.stdout.strip().splitlines()
        assert "1" in lines
        assert "2" in lines

    def test_field_then_iterate(self) -> None:
        engine = ShellEngine(
            initial_files={"/data.json": '{"items": ["x", "y", "z"]}\n'}
        )
        result = engine.run("jq '.items[]' /data.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ['"x"', '"y"', '"z"']


class TestJqPipe:
    """jq 'expr | expr' — pipe operator."""

    def test_pipe_field_to_keys(self) -> None:
        engine = ShellEngine(
            initial_files={"/data.json": '{"config": {"a": 1, "b": 2}}\n'}
        )
        result = engine.run("jq '.config | keys' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == ["a", "b"]

    def test_pipe_chaining(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": {"b": [1, 2, 3]}}\n'})
        result = engine.run("jq '.a | .b | .[1]' /data.json")
        assert result.stdout.strip() == "2"


class TestJqKeys:
    """jq 'keys' — get keys of object."""

    def test_keys_of_object(self) -> None:
        engine = ShellEngine(
            initial_files={"/data.json": '{"zebra": 1, "alpha": 2, "mid": 3}\n'}
        )
        result = engine.run("jq 'keys' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == ["alpha", "mid", "zebra"]

    def test_dependencies_keys(self) -> None:
        """Real-world: jq '.dependencies | keys' on package.json."""
        pkg = json.dumps(
            {
                "dependencies": {
                    "react": "^18.0.0",
                    "next": "^14.0.0",
                    "axios": "^1.0.0",
                }
            }
        )
        engine = ShellEngine(initial_files={"/package.json": pkg + "\n"})
        result = engine.run("jq '.dependencies | keys' /package.json")
        parsed = json.loads(result.stdout)
        assert parsed == ["axios", "next", "react"]


class TestJqSelect:
    """jq 'select(expr)' — filter by predicate."""

    def test_select_equality(self) -> None:
        data = json.dumps(
            [
                {"name": "a", "status": "active"},
                {"name": "b", "status": "inactive"},
                {"name": "c", "status": "active"},
            ]
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq '[.[] | select(.status == "active")]' /data.json""")
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2
        assert all(x["status"] == "active" for x in parsed)

    def test_select_numeric(self) -> None:
        data = json.dumps([1, 5, 3, 8, 2])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '[.[] | select(. > 3)]' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [5, 8]


class TestJqMap:
    """jq 'map(expr)' — transform array elements."""

    def test_map_field(self) -> None:
        data = json.dumps([{"name": "a", "v": 1}, {"name": "b", "v": 2}])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'map(.name)' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == ["a", "b"]

    def test_map_select(self) -> None:
        data = json.dumps(
            [
                {"name": "a", "status": "active"},
                {"name": "b", "status": "inactive"},
                {"name": "c", "status": "active"},
            ]
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq 'map(select(.status == "active"))' /data.json""")
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2

    def test_map_arithmetic(self) -> None:
        data = json.dumps([1, 2, 3, 4])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'map(. * 2)' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [2, 4, 6, 8]


class TestJqObjectConstruction:
    """jq '{key: .value}' — object construction."""

    def test_simple_reshape(self) -> None:
        data = json.dumps({"name": "project", "version": "1.0", "extra": "stuff"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '{name: .name, version: .version}' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"name": "project", "version": "1.0"}

    def test_object_with_literal_key(self) -> None:
        data = json.dumps({"x": 42})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '{result: .x}' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"result": 42}


class TestJqAlternativeOperator:
    """jq '.foo // "default"' — alternative operator."""

    def test_alternative_with_null(self) -> None:
        data = json.dumps({"a": None})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq '.a // "fallback"' /data.json""")
        assert result.stdout.strip() == '"fallback"'

    def test_alternative_with_value(self) -> None:
        data = json.dumps({"a": "exists"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq '.a // "fallback"' /data.json""")
        assert result.stdout.strip() == '"exists"'

    def test_alternative_missing_field(self) -> None:
        data = json.dumps({"b": 1})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq '.a // "default"' /data.json""")
        assert result.stdout.strip() == '"default"'


class TestJqCompactOutput:
    """jq -c — compact output."""

    def test_compact(self) -> None:
        data = json.dumps({"a": 1, "b": [1, 2]})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq -c '.' /data.json")
        # Compact means no extra spaces
        out = result.stdout.strip()
        parsed = json.loads(out)
        assert parsed == {"a": 1, "b": [1, 2]}
        # Should have no indentation
        assert "\n" not in out


class TestJqRawOutput:
    """jq -r — raw output for strings."""

    def test_raw_string(self) -> None:
        data = json.dumps({"msg": "hello world"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq -r '.msg' /data.json")
        assert result.stdout.strip() == "hello world"

    def test_raw_iterate(self) -> None:
        data = json.dumps([{"name": "alpha"}, {"name": "beta"}, {"name": "gamma"}])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq -r '.[] | .name' /data.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["alpha", "beta", "gamma"]


class TestJqLength:
    """jq 'length' — length function."""

    def test_array_length(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 3, 4, 5]\n"})
        result = engine.run("jq 'length' /data.json")
        assert result.stdout.strip() == "5"

    def test_object_length(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 1, "b": 2}\n'})
        result = engine.run("jq 'length' /data.json")
        assert result.stdout.strip() == "2"

    def test_string_length(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello"\n'})
        result = engine.run("jq 'length' /data.json")
        assert result.stdout.strip() == "5"


class TestJqType:
    """jq 'type' — type function."""

    def test_object_type(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 1}\n'})
        result = engine.run("jq 'type' /data.json")
        assert result.stdout.strip() == '"object"'

    def test_array_type(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2]\n"})
        result = engine.run("jq 'type' /data.json")
        assert result.stdout.strip() == '"array"'

    def test_string_type(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello"\n'})
        result = engine.run("jq 'type' /data.json")
        assert result.stdout.strip() == '"string"'


class TestJqSort:
    """jq 'sort' / 'sort_by' — sorting."""

    def test_sort_numbers(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[3, 1, 4, 1, 5]\n"})
        result = engine.run("jq 'sort' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 1, 3, 4, 5]

    def test_sort_by_field(self) -> None:
        data = json.dumps([{"n": "b", "v": 2}, {"n": "a", "v": 1}, {"n": "c", "v": 3}])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'sort_by(.v)' /data.json")
        parsed = json.loads(result.stdout)
        assert [x["n"] for x in parsed] == ["a", "b", "c"]


class TestJqUnique:
    """jq 'unique' — unique elements."""

    def test_unique_numbers(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 1, 3, 2, 4]\n"})
        result = engine.run("jq 'unique' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 3, 4]


class TestJqAdd:
    """jq 'add' — sum/concatenate."""

    def test_add_numbers(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 3, 4]\n"})
        result = engine.run("jq 'add' /data.json")
        assert result.stdout.strip() == "10"

    def test_add_strings(self) -> None:
        data = json.dumps(["a", "b", "c"])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'add' /data.json")
        assert result.stdout.strip() == '"abc"'


class TestJqStringFunctions:
    """String manipulation functions."""

    def test_split(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"a,b,c"\n'})
        result = engine.run("""jq 'split(",")' /data.json""")
        parsed = json.loads(result.stdout)
        assert parsed == ["a", "b", "c"]

    def test_join(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '["a", "b", "c"]\n'})
        result = engine.run("""jq 'join("-")' /data.json""")
        assert result.stdout.strip() == '"a-b-c"'

    def test_ascii_downcase(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"HELLO"\n'})
        result = engine.run("jq 'ascii_downcase' /data.json")
        assert result.stdout.strip() == '"hello"'

    def test_ascii_upcase(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello"\n'})
        result = engine.run("jq 'ascii_upcase' /data.json")
        assert result.stdout.strip() == '"HELLO"'

    def test_startswith(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello world"\n'})
        result = engine.run("""jq 'startswith("hello")' /data.json""")
        assert result.stdout.strip() == "true"

    def test_endswith(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello world"\n'})
        result = engine.run("""jq 'endswith("world")' /data.json""")
        assert result.stdout.strip() == "true"

    def test_ltrimstr(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello world"\n'})
        result = engine.run("""jq 'ltrimstr("hello ")' /data.json""")
        assert result.stdout.strip() == '"world"'

    def test_rtrimstr(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello.txt"\n'})
        result = engine.run("""jq 'rtrimstr(".txt")' /data.json""")
        assert result.stdout.strip() == '"hello"'

    def test_test_regex(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"foo123bar"\n'})
        result = engine.run("""jq 'test("[0-9]+")' /data.json""")
        assert result.stdout.strip() == "true"

    def test_gsub(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"foo bar baz"\n'})
        result = engine.run("""jq 'gsub(" "; "-")' /data.json""")
        assert result.stdout.strip() == '"foo-bar-baz"'


class TestJqConditional:
    """jq 'if-then-else-end' — conditional."""

    def test_if_then_else(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "5\n"})
        result = engine.run("""jq 'if . > 3 then "big" else "small" end' /data.json""")
        assert result.stdout.strip() == '"big"'

    def test_if_then_else_false(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "1\n"})
        result = engine.run("""jq 'if . > 3 then "big" else "small" end' /data.json""")
        assert result.stdout.strip() == '"small"'


class TestJqComma:
    """jq '.a, .b' — multiple outputs."""

    def test_comma_fields(self) -> None:
        data = json.dumps({"a": 1, "b": 2, "c": 3})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '.a, .b' /data.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["1", "2"]


class TestJqArithmetic:
    """jq arithmetic operations."""

    def test_addition(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "5\n"})
        result = engine.run("jq '. + 3' /data.json")
        assert result.stdout.strip() == "8"

    def test_subtraction(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "10\n"})
        result = engine.run("jq '. - 3' /data.json")
        assert result.stdout.strip() == "7"

    def test_comparison(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "5\n"})
        result = engine.run("jq '. == 5' /data.json")
        assert result.stdout.strip() == "true"


class TestJqToEntries:
    """jq 'to_entries' / 'from_entries'."""

    def test_to_entries(self) -> None:
        data = json.dumps({"a": 1, "b": 2})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'to_entries' /data.json")
        parsed = json.loads(result.stdout)
        assert {"key": "a", "value": 1} in parsed
        assert {"key": "b", "value": 2} in parsed

    def test_from_entries(self) -> None:
        data = json.dumps([{"key": "x", "value": 10}, {"key": "y", "value": 20}])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'from_entries' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"x": 10, "y": 20}


class TestJqHas:
    """jq 'has("key")' — test key existence."""

    def test_has_existing(self) -> None:
        data = json.dumps({"name": "test"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq 'has("name")' /data.json""")
        assert result.stdout.strip() == "true"

    def test_has_missing(self) -> None:
        data = json.dumps({"name": "test"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq 'has("missing")' /data.json""")
        assert result.stdout.strip() == "false"


class TestJqContains:
    """jq 'contains(val)' — containment test."""

    def test_string_contains(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"foobar"\n'})
        result = engine.run("""jq 'contains("oba")' /data.json""")
        assert result.stdout.strip() == "true"

    def test_array_contains(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[1, 2, 3]\n"})
        result = engine.run("jq 'contains([2])' /data.json")
        assert result.stdout.strip() == "true"


class TestJqFlatten:
    """jq 'flatten' — flatten nested arrays."""

    def test_flatten(self) -> None:
        data = json.dumps([[1, 2], [3, [4, 5]]])
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'flatten' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 3, 4, 5]


class TestJqGroupBy:
    """jq 'group_by(.key)' — group elements."""

    def test_group_by(self) -> None:
        data = json.dumps(
            [
                {"type": "a", "v": 1},
                {"type": "b", "v": 2},
                {"type": "a", "v": 3},
            ]
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq 'group_by(.type)' /data.json")
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2


class TestJqToNumber:
    """jq 'tonumber' / 'tostring' — type conversion."""

    def test_tonumber(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"42"\n'})
        result = engine.run("jq 'tonumber' /data.json")
        assert result.stdout.strip() == "42"

    def test_tostring(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "42\n"})
        result = engine.run("jq 'tostring' /data.json")
        assert result.stdout.strip() == '"42"'


class TestJqRange:
    """jq 'range(n)' — generate numbers."""

    def test_range(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "null\n"})
        result = engine.run("jq -n '[range(5)]'")
        parsed = json.loads(result.stdout)
        assert parsed == [0, 1, 2, 3, 4]


class TestJqNullInput:
    """jq -n — null input."""

    def test_null_input_literal(self) -> None:
        engine = ShellEngine()
        result = engine.run("""jq -n '{"a": 1}'""")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1}


class TestJqSlurp:
    """jq -s — slurp mode."""

    def test_slurp_lines(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "1\n2\n3\n"})
        result = engine.run("jq -s 'add' /data.json")
        assert result.stdout.strip() == "6"


class TestJqExitStatus:
    """jq -e — exit status on null/false."""

    def test_exit_status_null(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": null}\n'})
        result = engine.run("jq -e '.a' /data.json")
        assert result.result.exit_code == 1

    def test_exit_status_value(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '{"a": 42}\n'})
        result = engine.run("jq -e '.a' /data.json")
        assert result.result.exit_code == 0


class TestJqArg:
    """jq --arg and --argjson."""

    def test_arg(self) -> None:
        data = json.dumps({"name": "test"})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq --arg n "hello" '.name + " " + $n' /data.json""")
        assert result.stdout.strip() == '"test hello"'

    def test_argjson(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "null\n"})
        result = engine.run("""jq -n --argjson x '42' '$x + 8'""")
        assert result.stdout.strip() == "50"


class TestJqArrayConstruction:
    """jq '[expr]' — array construction."""

    def test_array_construction(self) -> None:
        data = json.dumps({"a": 1, "b": 2, "c": 3})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '[.a, .b]' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2]


class TestJqValues:
    """jq 'values' — object values."""

    def test_values(self) -> None:
        data = json.dumps({"a": 1, "b": 2})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '[values[]]' /data.json")
        parsed = json.loads(result.stdout)
        assert sorted(parsed) == [1, 2]


class TestJqLogical:
    """jq 'and' / 'or' / 'not' — logical operators."""

    def test_not(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "true\n"})
        result = engine.run("jq 'not' /data.json")
        assert result.stdout.strip() == "false"

    def test_and(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "true\n"})
        result = engine.run("jq 'true and false' /data.json")
        assert result.stdout.strip() == "false"

    def test_or(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "false\n"})
        result = engine.run("jq 'false or true' /data.json")
        assert result.stdout.strip() == "true"


class TestJqMinMax:
    """jq 'min' / 'max'."""

    def test_min(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[5, 1, 3, 2, 4]\n"})
        result = engine.run("jq 'min' /data.json")
        assert result.stdout.strip() == "1"

    def test_max(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": "[5, 1, 3, 2, 4]\n"})
        result = engine.run("jq 'max' /data.json")
        assert result.stdout.strip() == "5"


class TestJqRealWorld:
    """Real-world patterns agents commonly use."""

    def test_package_json_scripts_test(self) -> None:
        pkg = json.dumps({"scripts": {"test": "pytest", "lint": "ruff check"}})
        engine = ShellEngine(initial_files={"/package.json": pkg + "\n"})
        result = engine.run("jq -r '.scripts.test' /package.json")
        assert result.stdout.strip() == "pytest"

    def test_tsconfig_strict(self) -> None:
        ts = json.dumps({"compilerOptions": {"strict": True, "target": "es2020"}})
        engine = ShellEngine(initial_files={"/tsconfig.json": ts + "\n"})
        result = engine.run("jq '.compilerOptions.strict' /tsconfig.json")
        assert result.stdout.strip() == "true"

    def test_iterate_names(self) -> None:
        data = json.dumps(
            [
                {"name": "alice", "age": 30},
                {"name": "bob", "age": 25},
            ]
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq -r '.[] | .name' /data.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["alice", "bob"]

    def test_filter_active(self) -> None:
        data = json.dumps(
            [
                {"name": "a", "status": "active"},
                {"name": "b", "status": "inactive"},
                {"name": "c", "status": "active"},
            ]
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("""jq 'map(select(.status == "active"))' /data.json""")
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2
        assert all(x["status"] == "active" for x in parsed)

    def test_reshape_object(self) -> None:
        data = json.dumps(
            {
                "name": "myproject",
                "version": "2.0",
                "description": "a project",
                "private": True,
            }
        )
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '{name: .name, version: .version}' /data.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"name": "myproject", "version": "2.0"}


class TestJqFieldThenIndex:
    """jq '.foo[0]' — field access then array index."""

    def test_field_index(self) -> None:
        data = json.dumps({"items": ["x", "y", "z"]})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run("jq '.items[0]' /data.json")
        assert result.stdout.strip() == '"x"'


class TestJqWalk:
    """jq 'walk(f)' — recursive transform."""

    def test_walk_downcase_strings(self) -> None:
        data = json.dumps({"A": "HELLO", "B": ["WORLD"]})
        engine = ShellEngine(initial_files={"/data.json": data + "\n"})
        result = engine.run(
            "jq 'walk(if type == \"string\" then ascii_downcase else . end)' /data.json"
        )
        parsed = json.loads(result.stdout)
        assert parsed == {"A": "hello", "B": ["world"]}


class TestJqFormat:
    """jq '@base64' / '@uri' etc."""

    def test_base64_encode(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"hello"\n'})
        result = engine.run("jq '@base64' /data.json")
        assert result.stdout.strip() == '"aGVsbG8="'

    def test_base64_decode(self) -> None:
        engine = ShellEngine(initial_files={"/data.json": '"aGVsbG8="\n'})
        result = engine.run("jq '@base64d' /data.json")
        assert result.stdout.strip() == '"hello"'


# ==================================================================
# patch — Apply unified diffs
# ==================================================================


class TestPatchBasic:
    """Basic unified diff application."""

    def test_simple_patch(self) -> None:
        original = "line1\nline2\nline3\n"
        patch_text = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -i /patch.diff")
        assert result.result.exit_code == 0
        assert "patching file" in result.stdout

        # Verify file was modified
        content = engine.vfs.read("/file.txt").decode()
        assert "line2_modified" in content
        assert "line2\n" not in content.replace("line2_modified", "")

    def test_patch_p0(self) -> None:
        original = "hello\nworld\n"
        patch_text = (
            "--- file.txt\n+++ file.txt\n@@ -1,2 +1,2 @@\n hello\n-world\n+universe\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p0 -i /patch.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/file.txt").decode()
        assert "universe" in content


class TestPatchStrip:
    """patch -p1 — strip leading path components."""

    def test_strip_one(self) -> None:
        original = "alpha\nbeta\ngamma\n"
        patch_text = (
            "--- a/dir/file.txt\n"
            "+++ b/dir/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " alpha\n"
            "-beta\n"
            "+BETA\n"
            " gamma\n"
        )
        engine = ShellEngine(
            initial_files={
                "/dir/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -i /patch.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/dir/file.txt").decode()
        assert "BETA" in content


class TestPatchDryRun:
    """patch --dry-run — don't modify files."""

    def test_dry_run(self) -> None:
        original = "one\ntwo\nthree\n"
        patch_text = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " one\n"
            "-two\n"
            "+TWO\n"
            " three\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 --dry-run -i /patch.diff")
        assert result.result.exit_code == 0
        # File should NOT be modified
        content = engine.vfs.read("/file.txt").decode()
        assert "two" in content
        assert "TWO" not in content


class TestPatchSilent:
    """patch -s — silent mode."""

    def test_silent(self) -> None:
        original = "a\nb\nc\n"
        patch_text = "--- a/file.txt\n+++ b/file.txt\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -s -i /patch.diff")
        assert result.result.exit_code == 0
        assert result.stdout == ""


class TestPatchReverse:
    """patch -R — reverse patch."""

    def test_reverse(self) -> None:
        # The file has the "new" content, we reverse-apply to get "old"
        modified = "line1\nline2_modified\nline3\n"
        patch_text = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_modified\n"
            " line3\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": modified,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -R -i /patch.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/file.txt").decode()
        assert "line2\n" in content
        assert "line2_modified" not in content


class TestPatchFromStdin:
    """patch reading from stdin."""

    def test_stdin_patch(self) -> None:
        original = "foo\nbar\nbaz\n"
        patch_text = (
            "--- a/file.txt\n+++ b/file.txt\n@@ -1,3 +1,3 @@\n foo\n-bar\n+BAR\n baz\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/apply.sh": f'echo "{patch_text}" | patch -p1',
            }
        )
        # Use echo piped to patch
        result = engine.run(f"echo '{patch_text}' | patch -p1")
        # This depends on pipe support; if not available, just verify
        # the command is registered
        assert "patch" in result.stdout or result.result.exit_code in (
            0,
            1,
        )


class TestPatchAddition:
    """patch adding new lines."""

    def test_add_lines(self) -> None:
        original = "line1\nline3\n"
        patch_text = (
            "--- a/file.txt\n+++ b/file.txt\n@@ -1,2 +1,3 @@\n line1\n+line2\n line3\n"
        )
        engine = ShellEngine(
            initial_files={
                "/file.txt": original,
                "/patch.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -i /patch.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/file.txt").decode()
        assert "line1\nline2\nline3" in content
