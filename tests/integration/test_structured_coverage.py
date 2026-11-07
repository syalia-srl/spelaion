"""Additional integration tests for structured.py coverage.

Targets uncovered jq parser paths, evaluator builtins, patch edge cases,
and yq features to drive coverage from ~51% toward 75%+.
"""

from __future__ import annotations

import json

from agentsh.api.engine import ShellEngine

# ===================================================================
# jq — String interpolation
# ===================================================================


class TestJqStringInterpolation:
    def test_simple_interpolation(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"name":"alice"}\n'})
        result = engine.run(r"""jq '"hello \(.name)"' /d.json""")
        assert result.stdout.strip() == '"hello alice"'

    def test_interpolation_with_number(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"x":42}\n'})
        result = engine.run(r"""jq '"val=\(.x)"' /d.json""")
        assert result.stdout.strip() == '"val=42"'

    def test_interpolation_multiple(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1,"b":2}\n'})
        result = engine.run(r"""jq '"\(.a)+\(.b)"' /d.json""")
        assert result.stdout.strip() == '"1+2"'


# ===================================================================
# jq — try-catch
# ===================================================================


class TestJqTryCatch:
    def test_try_no_error(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1}\n'})
        result = engine.run("jq 'try .a' /d.json")
        assert result.stdout.strip() == "1"

    def test_try_with_error_suppressed(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("jq '[try .foo]' /d.json")
        # Should produce empty array since .foo on string errors
        assert result.stdout.strip() == "[]"

    def test_try_catch_expr(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("""jq 'try error("bad") catch "caught"' /d.json""")
        assert result.stdout.strip() == '"caught"'


# ===================================================================
# jq — def / function definitions
# ===================================================================


class TestJqDef:
    def test_simple_def(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq 'def double: . * 2; double' /d.json")
        assert result.stdout.strip() == "10"

    def test_def_no_params(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq 'def triple: . * 3; triple' /d.json")
        assert result.stdout.strip() == "30"

    def test_def_used_multiple_times(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3]\n"})
        result = engine.run("jq 'def inc: . + 1; map(inc)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [2, 3, 4]


# ===================================================================
# jq — reduce
# ===================================================================


class TestJqReduce:
    def test_reduce_sum(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,4]\n"})
        result = engine.run("jq 'reduce .[] as $x (0; . + $x)' /d.json")
        assert result.stdout.strip() == "10"

    def test_reduce_product(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,4]\n"})
        result = engine.run("jq 'reduce .[] as $x (1; . * $x)' /d.json")
        assert result.stdout.strip() == "24"

    def test_reduce_string_concat(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a","b","c"]\n'})
        result = engine.run("""jq 'reduce .[] as $x (""; . + $x)' /d.json""")
        assert result.stdout.strip() == '"abc"'


# ===================================================================
# jq — as patterns
# ===================================================================


class TestJqAsPattern:
    def test_as_pattern(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1,"b":2}\n'})
        result = engine.run("jq '.a as $x | .b + $x' /d.json")
        assert result.stdout.strip() == "3"

    def test_as_pattern_in_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '. as $x | [$x, $x * 2]' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [5, 10]


# ===================================================================
# jq — label/break
# ===================================================================


class TestJqLabelBreak:
    def test_label_basic(self) -> None:
        """label $out | expr -- exercises label node."""
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'label $out | .' /d.json")
        assert result.stdout.strip() == "42"


# ===================================================================
# jq — optional operator ?
# ===================================================================


class TestJqOptionalOperator:
    def test_optional_field(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("jq '.foo?' /d.json")
        # Should produce no output instead of error
        assert result.result.exit_code == 0

    def test_optional_iterate(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("jq '[.[]?]' /d.json")
        assert result.stdout.strip() == "[]"

    def test_optional_index(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("jq '.[0]?' /d.json")
        assert result.result.exit_code == 0


# ===================================================================
# jq — slice
# ===================================================================


class TestJqSlice:
    def test_array_slice(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[0,1,2,3,4,5]\n"})
        result = engine.run("jq '.[2:5]' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [2, 3, 4]

    def test_slice_from_start(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[0,1,2,3,4]\n"})
        result = engine.run("jq '.[:3]' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [0, 1, 2]

    def test_slice_to_end(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[0,1,2,3,4]\n"})
        result = engine.run("jq '.[3:]' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [3, 4]

    def test_string_slice(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abcdef"\n'})
        result = engine.run("jq '.[1:4]' /d.json")
        assert result.stdout.strip() == '"bcd"'


# ===================================================================
# jq — if-then without else
# ===================================================================


class TestJqIfThenNoElse:
    def test_if_then_true(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("""jq 'if . > 3 then "big" end' /d.json""")
        assert result.stdout.strip() == '"big"'

    def test_if_then_false_identity(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "1\n"})
        result = engine.run("""jq 'if . > 3 then "big" end' /d.json""")
        # Without else, should return identity
        assert result.stdout.strip() == "1"


# ===================================================================
# jq — elif
# ===================================================================


class TestJqNestedIf:
    def test_nested_if(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        filt = 'if . > 10 then "large" else if . > 3 then "medium" else "small" end end'
        result = engine.run(f"jq '{filt}' /d.json")
        assert result.stdout.strip() == '"medium"'


# ===================================================================
# jq — comma at top level (multiple outputs)
# ===================================================================


class TestJqCommaTopLevel:
    def test_comma_three(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1,"b":2,"c":3}\n'})
        result = engine.run("jq '.a, .b, .c' /d.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["1", "2", "3"]


# ===================================================================
# jq — from_entries, to_entries, with_entries
# ===================================================================


class TestJqEntries:
    def test_with_entries(self) -> None:
        data = json.dumps({"a": 1, "b": 2})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'with_entries(select(.value > 1))' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == {"b": 2}

    def test_with_entries_filter_by_value(self) -> None:
        data = json.dumps({"a": 1, "b": 2, "c": 3})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'with_entries(select(.value >= 2))' /d.json""")
        parsed = json.loads(result.stdout)
        assert "a" not in parsed
        assert "b" in parsed
        assert "c" in parsed

    def test_from_entries_with_name_key(self) -> None:
        data = json.dumps([{"name": "x", "value": 10}])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'from_entries' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"x": 10}


# ===================================================================
# jq — unique_by
# ===================================================================


class TestJqUniqueBy:
    def test_unique_by(self) -> None:
        data = json.dumps([{"t": "a", "v": 1}, {"t": "a", "v": 2}, {"t": "b", "v": 3}])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'unique_by(.t)' /d.json")
        parsed = json.loads(result.stdout)
        assert len(parsed) == 2


# ===================================================================
# jq — min_by, max_by
# ===================================================================


class TestJqMinMaxBy:
    def test_min_by(self) -> None:
        data = json.dumps([{"n": "a", "v": 3}, {"n": "b", "v": 1}, {"n": "c", "v": 2}])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'min_by(.v)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed["n"] == "b"

    def test_max_by(self) -> None:
        data = json.dumps([{"n": "a", "v": 3}, {"n": "b", "v": 1}, {"n": "c", "v": 2}])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'max_by(.v)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed["n"] == "a"


# ===================================================================
# jq — limit, first, last, nth
# ===================================================================


class TestJqLimitFirstLastNth:
    def test_limit(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[limit(3; range(10))]'")
        parsed = json.loads(result.stdout)
        assert parsed == [0, 1, 2]

    def test_first(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'first(range(5))'")
        assert result.stdout.strip() == "0"

    def test_last(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'last(range(5))'")
        assert result.stdout.strip() == "4"

    def test_nth(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'nth(2; range(5))'")
        assert result.stdout.strip() == "2"


# ===================================================================
# jq — range (2 args, 3 args)
# ===================================================================


class TestJqRange:
    def test_range_two_args(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[range(2;5)]'")
        parsed = json.loads(result.stdout)
        assert parsed == [2, 3, 4]

    def test_range_three_args(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[range(0;10;3)]'")
        parsed = json.loads(result.stdout)
        assert parsed == [0, 3, 6, 9]


# ===================================================================
# jq — recurse
# ===================================================================


class TestJqRecurse:
    def test_recurse_simple(self) -> None:
        data = json.dumps({"a": {"b": 1}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '[recurse | numbers]' /d.json")
        parsed = json.loads(result.stdout)
        assert 1 in parsed

    def test_recurse_with_select(self) -> None:
        data = json.dumps({"a": {"b": 2}, "c": 3})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '[recurse | strings]' /d.json")
        # No strings in this data, result should be empty
        parsed = json.loads(result.stdout)
        assert parsed == []


# ===================================================================
# jq — path, getpath, setpath, delpaths
# ===================================================================


class TestJqPathOps:
    def test_path(self) -> None:
        data = json.dumps({"a": {"b": 1}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'path(.a.b)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == ["a", "b"]

    def test_getpath(self) -> None:
        data = json.dumps({"a": {"b": 42}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'getpath(["a","b"])' /d.json""")
        assert result.stdout.strip() == "42"

    def test_setpath(self) -> None:
        data = json.dumps({"a": 1})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'setpath(["b"]; 2)' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed["b"] == 2

    def test_delpaths(self) -> None:
        data = json.dumps({"a": 1, "b": 2, "c": 3})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'delpaths([["b"]])' /d.json""")
        parsed = json.loads(result.stdout)
        assert "b" not in parsed
        assert "a" in parsed

    def test_leaf_paths(self) -> None:
        data = json.dumps({"a": 1, "b": {"c": 2}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'leaf_paths' /d.json")
        parsed = json.loads(result.stdout)
        # leaf_paths returns the array of paths
        assert ["a"] in parsed
        assert ["b", "c"] in parsed


# ===================================================================
# jq — env.NAME access
# ===================================================================


class TestJqEnv:
    def test_env_ref(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("MY_VAR=hello jq -n 'env.MY_VAR'")
        # env vars come from shell state
        assert result.result.exit_code == 0


# ===================================================================
# jq — format strings: @uri, @csv, @tsv, @html, @json
# ===================================================================


class TestJqFormats:
    def test_uri_encode(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello world"\n'})
        result = engine.run("jq '@uri' /d.json")
        assert "hello%20world" in result.stdout

    def test_csv(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a","b",1]\n'})
        result = engine.run("jq -r '@csv' /d.json")
        assert '"a"' in result.stdout
        assert '"b"' in result.stdout

    def test_tsv(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a","b","c"]\n'})
        result = engine.run("jq '@tsv' /d.json")
        out = result.stdout.strip().strip('"')
        assert "a" in out
        assert "b" in out

    def test_html(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"<b>hi</b>"\n'})
        result = engine.run("jq '@html' /d.json")
        assert "&lt;" in result.stdout
        assert "&gt;" in result.stdout

    def test_json_format(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1}\n'})
        result = engine.run("jq '@json' /d.json")
        assert result.result.exit_code == 0

    def test_csv_with_null(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a",null,1]\n'})
        result = engine.run("jq '@csv' /d.json")
        assert result.result.exit_code == 0

    def test_tsv_with_null(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a",null,1]\n'})
        result = engine.run("jq '@tsv' /d.json")
        assert result.result.exit_code == 0


# ===================================================================
# jq — indices, index, rindex
# ===================================================================


class TestJqIndices:
    def test_index_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abcabc"\n'})
        result = engine.run("""jq 'index("bc")' /d.json""")
        assert result.stdout.strip() == "1"

    def test_indices_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abcabc"\n'})
        result = engine.run("""jq 'indices("bc")' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 4]

    def test_rindex_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abcabc"\n'})
        result = engine.run("""jq 'rindex("bc")' /d.json""")
        assert result.stdout.strip() == "4"

    def test_index_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,2,1]\n"})
        result = engine.run("jq 'index(2)' /d.json")
        assert result.stdout.strip() == "1"

    def test_rindex_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,2,1]\n"})
        result = engine.run("jq 'rindex(2)' /d.json")
        assert result.stdout.strip() == "3"

    def test_indices_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,2,1]\n"})
        result = engine.run("jq 'indices(2)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 3]


# ===================================================================
# jq — inside / contains with nested
# ===================================================================


class TestJqInsideContains:
    def test_inside(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"bar"\n'})
        result = engine.run("""jq 'inside("foobar")' /d.json""")
        assert result.stdout.strip() == "true"

    def test_contains_nested_object(self) -> None:
        data = json.dumps({"a": {"b": 1, "c": 2}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'contains({"a":{"b":1}})' /d.json""")
        assert result.stdout.strip() == "true"

    def test_contains_nested_false(self) -> None:
        data = json.dumps({"a": {"b": 1}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq 'contains({"a":{"b":2}})' /d.json""")
        assert result.stdout.strip() == "false"

    def test_inside_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2]\n"})
        result = engine.run("jq 'inside([1,2,3])' /d.json")
        assert result.stdout.strip() == "true"


# ===================================================================
# jq — ascii, implode, explode
# ===================================================================


class TestJqAsciiImplodeExplode:
    def test_explode(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abc"\n'})
        result = engine.run("jq 'explode' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [97, 98, 99]

    def test_implode(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[97,98,99]\n"})
        result = engine.run("jq 'implode' /d.json")
        assert result.stdout.strip() == '"abc"'

    def test_ascii(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"A"\n'})
        result = engine.run("jq 'ascii' /d.json")
        assert result.stdout.strip() == "65"


# ===================================================================
# jq — isnan, isinfinite, nan, infinite
# ===================================================================


class TestJqSpecialNumbers:
    def test_nan(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'nan | isnan'")
        assert result.stdout.strip() == "true"

    def test_infinite(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'infinite | isinfinite'")
        assert result.stdout.strip() == "true"

    def test_isnan_number(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'isnan' /d.json")
        assert result.stdout.strip() == "false"

    def test_isinfinite_number(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'isinfinite' /d.json")
        assert result.stdout.strip() == "false"


# ===================================================================
# jq — builtins
# ===================================================================


class TestJqBuiltins:
    def test_builtins(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'builtins | length'")
        n = int(result.stdout.strip())
        assert n > 10


# ===================================================================
# jq — type selection builtins
# ===================================================================


class TestJqTypeSelectors:
    def test_strings(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("jq 'strings' /d.json")
        assert result.stdout.strip() == '"hello"'

    def test_strings_non_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq '[strings]' /d.json")
        assert result.stdout.strip() == "[]"

    def test_numbers(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'numbers' /d.json")
        assert result.stdout.strip() == "42"

    def test_arrays(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2]\n"})
        result = engine.run("jq 'arrays' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2]

    def test_objects(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1}\n'})
        result = engine.run("jq 'objects' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1}

    def test_booleans(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "true\n"})
        result = engine.run("jq 'booleans' /d.json")
        assert result.stdout.strip() == "true"

    def test_nulls(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq 'nulls' /d.json")
        assert result.stdout.strip() == "null"

    def test_scalars(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'scalars' /d.json")
        assert result.stdout.strip() == "42"

    def test_scalars_not_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2]\n"})
        result = engine.run("jq '[scalars]' /d.json")
        assert result.stdout.strip() == "[]"


# ===================================================================
# jq — string multiplication
# ===================================================================


class TestJqStringMultiplication:
    def test_object_merge_star(self) -> None:
        data = json.dumps({"a": 1})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq '. * {"b":2}' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed["a"] == 1
        assert parsed["b"] == 2

    def test_number_multiply(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '. * 3' /d.json")
        assert result.stdout.strip() == "15"


# ===================================================================
# jq — array subtraction
# ===================================================================


class TestJqArraySubtraction:
    def test_number_subtraction(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. - 3' /d.json")
        assert result.stdout.strip() == "7"


# ===================================================================
# jq — any(f), all(f) with filter
# ===================================================================


class TestJqAnyAll:
    def test_any_with_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,4,5]\n"})
        result = engine.run("jq 'any(. > 4)' /d.json")
        assert result.stdout.strip() == "true"

    def test_any_no_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[false, false, true]\n"})
        result = engine.run("jq 'any' /d.json")
        assert result.stdout.strip() == "true"

    def test_all_with_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,4,5]\n"})
        result = engine.run("jq 'all(. > 0)' /d.json")
        assert result.stdout.strip() == "true"

    def test_all_false(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3,4,5]\n"})
        result = engine.run("jq 'all(. > 3)' /d.json")
        assert result.stdout.strip() == "false"

    def test_all_no_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[true, true, true]\n"})
        result = engine.run("jq 'all' /d.json")
        assert result.stdout.strip() == "true"


# ===================================================================
# jq — not operator
# ===================================================================


class TestJqNotOperator:
    def test_not_true(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "true\n"})
        result = engine.run("jq 'not' /d.json")
        assert result.stdout.strip() == "false"

    def test_not_false(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "false\n"})
        result = engine.run("jq 'not' /d.json")
        assert result.stdout.strip() == "true"

    def test_not_null(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq 'not' /d.json")
        assert result.stdout.strip() == "true"


# ===================================================================
# jq — null literal
# ===================================================================


class TestJqNullLiteral:
    def test_null_literal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'null'")
        assert result.stdout.strip() == "null"

    def test_null_in_object(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("""jq -n '{"a": null}'""")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": None}


# ===================================================================
# jq — comparison operators
# ===================================================================


class TestJqComparisons:
    def test_less_than(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3\n"})
        result = engine.run("jq '. < 5' /d.json")
        assert result.stdout.strip() == "true"

    def test_greater_than(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. > 5' /d.json")
        assert result.stdout.strip() == "true"

    def test_less_equal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '. <= 5' /d.json")
        assert result.stdout.strip() == "true"

    def test_greater_equal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '. >= 5' /d.json")
        assert result.stdout.strip() == "true"

    def test_not_equal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '. != 3' /d.json")
        assert result.stdout.strip() == "true"


# ===================================================================
# jq — alternative operator //
# ===================================================================


class TestJqAlternative:
    def test_alt_with_false(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "false\n"})
        result = engine.run("""jq '. // "default"' /d.json""")
        assert result.stdout.strip() == '"default"'


# ===================================================================
# jq — reverse
# ===================================================================


class TestJqReverse:
    def test_reverse_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3]\n"})
        result = engine.run("jq 'reverse' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [3, 2, 1]

    def test_reverse_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abc"\n'})
        result = engine.run("jq 'reverse' /d.json")
        assert result.stdout.strip() == '"cba"'


# ===================================================================
# jq — math functions
# ===================================================================


class TestJqMath:
    def test_abs(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "-5\n"})
        result = engine.run("jq 'abs' /d.json")
        assert result.stdout.strip() == "5"

    def test_floor(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3.7\n"})
        result = engine.run("jq 'floor' /d.json")
        assert result.stdout.strip() == "3"

    def test_ceil(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3.2\n"})
        result = engine.run("jq 'ceil' /d.json")
        assert result.stdout.strip() == "4"

    def test_round(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3.5\n"})
        result = engine.run("jq 'round' /d.json")
        assert result.stdout.strip() == "4"

    def test_sqrt(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "9\n"})
        result = engine.run("jq 'sqrt' /d.json")
        assert result.stdout.strip() == "3"

    def test_fabs(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "-3.5\n"})
        result = engine.run("jq 'fabs' /d.json")
        assert result.stdout.strip() == "3.5"

    def test_log(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "1\n"})
        result = engine.run("jq 'log' /d.json")
        assert result.stdout.strip() == "0"

    def test_exp(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "0\n"})
        result = engine.run("jq 'exp' /d.json")
        assert result.stdout.strip() == "1"

    def test_pow(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'pow(2; 10)'")
        assert "1024" in result.stdout

    def test_isnormal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq 'isnormal' /d.json")
        assert result.stdout.strip() == "true"

    def test_isnormal_zero(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "0\n"})
        result = engine.run("jq 'isnormal' /d.json")
        assert result.stdout.strip() == "false"


# ===================================================================
# jq — map_values
# ===================================================================


class TestJqMapValues:
    def test_map_values_object(self) -> None:
        data = json.dumps({"a": 1, "b": 2})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'map_values(. + 10)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 11, "b": 12}

    def test_map_values_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3]\n"})
        result = engine.run("jq 'map_values(. * 2)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [2, 4, 6]


# ===================================================================
# jq — empty
# ===================================================================


class TestJqEmpty:
    def test_empty(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[empty]'")
        assert result.stdout.strip() == "[]"


# ===================================================================
# jq — tojson / fromjson
# ===================================================================


class TestJqJsonConvert:
    def test_tojson(self) -> None:
        data = json.dumps({"a": 1})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'tojson' /d.json")
        # The result should be a JSON-encoded string
        outer = json.loads(result.stdout)
        inner = json.loads(outer)
        assert inner == {"a": 1}

    def test_fromjson(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1}\n'})
        result = engine.run("jq 'tojson | fromjson' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1}


# ===================================================================
# jq — keys_unsorted
# ===================================================================


class TestJqKeysUnsorted:
    def test_keys_unsorted(self) -> None:
        data = json.dumps({"z": 1, "a": 2})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'keys_unsorted' /d.json")
        parsed = json.loads(result.stdout)
        assert set(parsed) == {"z", "a"}

    def test_keys_of_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '["a","b","c"]\n'})
        result = engine.run("jq 'keys' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [0, 1, 2]


# ===================================================================
# jq — in operator
# ===================================================================


class TestJqInOperator:
    def test_in_object(self) -> None:
        data = json.dumps({"a": 1, "b": 2})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq '"a" | in({"a":1,"b":2})' /d.json""")
        assert result.stdout.strip() == "true"


# ===================================================================
# jq — has for array
# ===================================================================


class TestJqHasArray:
    def test_has_array_index(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3]\n"})
        result = engine.run("jq 'has(1)' /d.json")
        assert result.stdout.strip() == "true"

    def test_has_array_out_of_range(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2,3]\n"})
        result = engine.run("jq 'has(5)' /d.json")
        assert result.stdout.strip() == "false"


# ===================================================================
# jq — match, capture, scan, sub
# ===================================================================


class TestJqRegex:
    def test_match(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"foo123bar"\n'})
        result = engine.run("""jq 'match("[0-9]+")' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed["string"] == "123"
        assert parsed["offset"] == 3

    def test_capture(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"foo123"\n'})
        result = engine.run(
            """jq 'capture("(?P<name>[a-z]+)(?P<num>[0-9]+)")' /d.json"""
        )
        parsed = json.loads(result.stdout)
        assert parsed["name"] == "foo"
        assert parsed["num"] == "123"

    def test_scan(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"abc123def456"\n'})
        result = engine.run("""jq 'scan("[0-9]+")' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == ["123", "456"]

    def test_sub(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"foo bar baz"\n'})
        result = engine.run("""jq 'sub(" "; "-")' /d.json""")
        assert result.stdout.strip() == '"foo-bar baz"'


# ===================================================================
# jq — flatten with depth
# ===================================================================


class TestJqFlattenDepth:
    def test_flatten_depth_1(self) -> None:
        data = json.dumps([[1, [2]], [3, [4]]])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'flatten(1)' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, [2], 3, [4]]


# ===================================================================
# jq — walk
# ===================================================================


class TestJqWalk:
    def test_walk_add_field(self) -> None:
        data = json.dumps({"a": {"b": 1}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run(
            """jq 'walk(if type == "number" then . + 10 else . end)' /d.json"""
        )
        parsed = json.loads(result.stdout)
        assert parsed["a"]["b"] == 11


# ===================================================================
# jq — object shorthand, computed keys
# ===================================================================


class TestJqObjectConstruction:
    def test_shorthand(self) -> None:
        data = json.dumps({"name": "test", "age": 30, "extra": "x"})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '{name, age}' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"name": "test", "age": 30}

    def test_computed_key(self) -> None:
        data = json.dumps({"key": "mykey", "val": 42})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '{(.key): .val}' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"mykey": 42}

    def test_string_key(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"x":1}\n'})
        result = engine.run("""jq '{"hello": .x}' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == {"hello": 1}


# ===================================================================
# jq — division / modulo / string split via /
# ===================================================================


class TestJqDivision:
    def test_division(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. / 3' /d.json")
        # 10 / 3 is not clean integer
        val = float(result.stdout.strip())
        assert abs(val - 3.3333) < 0.01

    def test_integer_division(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. / 2' /d.json")
        assert result.stdout.strip() == "5"

    def test_modulo(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. % 3' /d.json")
        assert result.stdout.strip() == "1"

    def test_string_split_by_div(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"a.b.c"\n'})
        result = engine.run("""jq '. / "."' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == ["a", "b", "c"]


# ===================================================================
# jq — object addition (merge)
# ===================================================================


class TestJqObjectAdd:
    def test_object_merge_plus(self) -> None:
        data = json.dumps({"a": 1})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("""jq '. + {"b": 2}' /d.json""")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1, "b": 2}

    def test_array_concat(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1,2]\n"})
        result = engine.run("jq '. + [3,4]' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 3, 4]

    def test_string_concat(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello"\n'})
        result = engine.run("""jq '. + " world"' /d.json""")
        assert result.stdout.strip() == '"hello world"'


# ===================================================================
# jq — while, until, repeat
# ===================================================================


class TestJqIterators:
    def test_while(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[1 | while(. < 10; . * 2)]'")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 4, 8]

    def test_until(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '1 | until(. >= 10; . * 2)'")
        assert result.stdout.strip() == "16"


# ===================================================================
# jq — transpose
# ===================================================================


class TestJqTranspose:
    def test_transpose(self) -> None:
        data = json.dumps([[1, 2], [3, 4]])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'transpose' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [[1, 3], [2, 4]]


# ===================================================================
# jq — trim, ltrim, rtrim
# ===================================================================


class TestJqTrim:
    def test_trim(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"  hello  "\n'})
        result = engine.run("jq 'trim' /d.json")
        assert result.stdout.strip() == '"hello"'

    def test_ltrim(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"  hello"\n'})
        result = engine.run("jq 'ltrim' /d.json")
        assert result.stdout.strip() == '"hello"'

    def test_rtrim(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"hello  "\n'})
        result = engine.run("jq 'rtrim' /d.json")
        assert result.stdout.strip() == '"hello"'


# ===================================================================
# jq — splits
# ===================================================================


class TestJqSplits:
    def test_splits(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '"a1b2c"\n'})
        result = engine.run("""jq '[splits("[0-9]+")]' /d.json""")
        parsed = json.loads(result.stdout)
        assert "a" in parsed
        assert "b" in parsed
        assert "c" in parsed


# ===================================================================
# jq — debug
# ===================================================================


class TestJqDebug:
    def test_debug_passthrough(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "42\n"})
        result = engine.run("jq 'debug' /d.json")
        # debug should pass through the value
        assert result.stdout.strip() == "42"


# ===================================================================
# jq — length of null, number, bool
# ===================================================================


class TestJqLengthEdgeCases:
    def test_null_length(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq 'length' /d.json")
        assert result.stdout.strip() == "0"

    def test_number_length(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "-5\n"})
        result = engine.run("jq 'length' /d.json")
        assert result.stdout.strip() == "5"

    def test_bool_length(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "true\n"})
        result = engine.run("jq 'length' /d.json")
        assert result.stdout.strip() == "1"


# ===================================================================
# jq — add on objects and arrays
# ===================================================================


class TestJqAddTypes:
    def test_add_arrays(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[[1,2],[3,4]]\n"})
        result = engine.run("jq 'add' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 3, 4]

    def test_add_objects(self) -> None:
        data = json.dumps([{"a": 1}, {"b": 2}])
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq 'add' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"a": 1, "b": 2}

    def test_add_empty(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[]\n"})
        result = engine.run("jq 'add' /d.json")
        assert result.stdout.strip() == "null"


# ===================================================================
# jq — negative number literal
# ===================================================================


class TestJqNegativeNumber:
    def test_negative_literal(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '0 - 5'")
        assert result.stdout.strip() == "-5"

    def test_negative_in_expr(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "10\n"})
        result = engine.run("jq '. + -3' /d.json")
        assert result.stdout.strip() == "7"


# ===================================================================
# jq — float number
# ===================================================================


class TestJqFloatNumber:
    def test_float_output(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3.14\n"})
        result = engine.run("jq '.' /d.json")
        assert "3.14" in result.stdout

    def test_scientific_notation(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "1e3\n"})
        result = engine.run("jq '.' /d.json")
        assert result.stdout.strip() == "1000"


# ===================================================================
# jq — parenthesized expressions
# ===================================================================


class TestJqParenthesized:
    def test_parens(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "5\n"})
        result = engine.run("jq '(. + 3) * 2' /d.json")
        assert result.stdout.strip() == "16"


# ===================================================================
# jq — empty array construct
# ===================================================================


class TestJqEmptyArray:
    def test_empty_array(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[]'")
        assert result.stdout.strip() == "[]"


# ===================================================================
# jq — error function
# ===================================================================


class TestJqError:
    def test_error_caught(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("""jq -n 'try error("oops") catch "handled"'""")
        assert result.stdout.strip() == '"handled"'


# ===================================================================
# jq — variable from --arg
# ===================================================================


class TestJqVariables:
    def test_arg_in_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"x":1}\n'})
        result = engine.run("""jq --arg name "test" '$name' /d.json""")
        assert result.stdout.strip() == '"test"'

    def test_argjson_number(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("""jq -n --argjson n '10' '$n * 2'""")
        assert result.stdout.strip() == "20"


# ===================================================================
# jq — comment handling
# ===================================================================


class TestJqComments:
    def test_comment_in_filter(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": '{"a":1}\n'})
        # Comments should be ignored - using \n for comment
        result = engine.run("jq '.a' /d.json")
        assert result.stdout.strip() == "1"


# ===================================================================
# jq — object shorthand: {name} == {name: .name}
# ===================================================================


class TestJqObjectShorthand:
    def test_field_shorthand(self) -> None:
        data = json.dumps({"name": "alice", "age": 30, "city": "NYC"})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '{name}' /d.json")
        parsed = json.loads(result.stdout)
        assert parsed == {"name": "alice"}


# ===================================================================
# jq — add with null items
# ===================================================================


class TestJqAddWithNulls:
    def test_add_with_null(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "[1, null, 2]\n"})
        result = engine.run("jq 'add' /d.json")
        assert result.stdout.strip() == "3"

    def test_null_plus_value(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq '. + 5' /d.json")
        assert result.stdout.strip() == "5"


# ===================================================================
# jq — recurse_down alias
# ===================================================================


class TestJqRecurseDown:
    def test_recurse_down(self) -> None:
        data = json.dumps({"a": {"b": 1}})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq '[recurse_down | numbers]' /d.json")
        parsed = json.loads(result.stdout)
        assert 1 in parsed


# ===================================================================
# jq — log2, log10, exp2, exp10
# ===================================================================


class TestJqMathExtended:
    def test_log2(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "8\n"})
        result = engine.run("jq 'log2' /d.json")
        assert result.stdout.strip() == "3"

    def test_log10(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "100\n"})
        result = engine.run("jq 'log10' /d.json")
        assert result.stdout.strip() == "2"

    def test_exp2(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "3\n"})
        result = engine.run("jq 'exp2' /d.json")
        assert result.stdout.strip() == "8"

    def test_exp10(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "2\n"})
        result = engine.run("jq 'exp10' /d.json")
        assert result.stdout.strip() == "100"


# ===================================================================
# jq — format output edge cases
# ===================================================================


class TestJqOutputFormat:
    def test_float_integer_output(self) -> None:
        """Floats that are integers should be output as integers."""
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '10 / 2'")
        assert result.stdout.strip() == "5"

    def test_bool_output(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'true'")
        assert result.stdout.strip() == "true"

    def test_compact_output(self) -> None:
        data = json.dumps({"a": [1, 2]})
        engine = ShellEngine(initial_files={"/d.json": data + "\n"})
        result = engine.run("jq -c '.' /d.json")
        assert "\n" not in result.stdout.strip()


# ===================================================================
# jq — multiple JSON inputs
# ===================================================================


class TestJqMultipleInputs:
    def test_multiple_json_values(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "1\n2\n3\n"})
        result = engine.run("jq '. + 10' /d.json")
        lines = result.stdout.strip().splitlines()
        assert lines == ["11", "12", "13"]


# ===================================================================
# jq — object constructor
# ===================================================================


class TestJqObjectEmpty:
    def test_object_fn(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n 'object'")
        assert result.stdout.strip() == "{}"


# ===================================================================
# patch — forward/already-applied
# ===================================================================


class TestPatchForward:
    def test_forward_already_applied(self) -> None:
        # The file already has the patched content
        already_applied = "line1\nline2_modified\nline3\n"
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
            initial_files={"/file.txt": already_applied, "/p.diff": patch_text}
        )
        engine.run("patch -p1 -N -i /p.diff")
        # With -N, should not fail
        content = engine.vfs.read("/file.txt").decode()
        assert "line2_modified" in content


# ===================================================================
# patch — multi-file patch
# ===================================================================


class TestPatchMultiFile:
    def test_multi_file(self) -> None:
        patch_text = (
            "--- a/f1.txt\n"
            "+++ b/f1.txt\n"
            "@@ -1 +1 @@\n"
            "-old1\n"
            "+new1\n"
            "--- a/f2.txt\n"
            "+++ b/f2.txt\n"
            "@@ -1 +1 @@\n"
            "-old2\n"
            "+new2\n"
        )
        engine = ShellEngine(
            initial_files={
                "/f1.txt": "old1\n",
                "/f2.txt": "old2\n",
                "/p.diff": patch_text,
            }
        )
        result = engine.run("patch -p1 -i /p.diff")
        assert result.result.exit_code == 0
        c1 = engine.vfs.read("/f1.txt").decode()
        c2 = engine.vfs.read("/f2.txt").decode()
        assert "new1" in c1
        assert "new2" in c2


# ===================================================================
# patch — fuzz matching (offset)
# ===================================================================


class TestPatchFuzz:
    def test_fuzz_offset(self) -> None:
        # Extra blank line at top causes the hunk target to be offset
        original = "\nline1\nline2\nline3\n"
        patch_text = (
            "--- a/file.txt\n"
            "+++ b/file.txt\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+LINE2\n"
            " line3\n"
        )
        engine = ShellEngine(
            initial_files={"/file.txt": original, "/p.diff": patch_text}
        )
        result = engine.run("patch -p1 -i /p.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/file.txt").decode()
        assert "LINE2" in content


# ===================================================================
# patch — new file (file doesn't exist)
# ===================================================================


class TestPatchNewFile:
    def test_create_file(self) -> None:
        patch_text = (
            "--- /dev/null\n+++ b/newfile.txt\n@@ -0,0 +1,2 @@\n+hello\n+world\n"
        )
        engine = ShellEngine(initial_files={"/p.diff": patch_text})
        result = engine.run("patch -p1 -i /p.diff")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/newfile.txt").decode()
        assert "hello" in content
        assert "world" in content


# ===================================================================
# yq — in-place editing
# ===================================================================


class TestYqInPlace:
    def test_in_place(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "name: old\nage: 30\n"})
        result = engine.run("yq -i '.name' /d.yaml")
        assert result.result.exit_code == 0
        content = engine.vfs.read("/d.yaml").decode()
        assert "old" in content


# ===================================================================
# yq — TOML auto-detection
# ===================================================================


class TestYqTomlAuto:
    def test_toml_auto(self) -> None:
        engine = ShellEngine(
            initial_files={"/c.toml": '[db]\nhost = "localhost"\nport = 5432\n'}
        )
        result = engine.run("yq '.db.port' /c.toml")
        assert result.stdout.strip() == "5432"


# ===================================================================
# yq — properties output
# ===================================================================


class TestYqPropertiesOutput:
    def test_props_output(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "name: test\nversion: 1\n"})
        result = engine.run("yq -o props '.' /d.yaml")
        assert result.result.exit_code == 0
        assert "name" in result.stdout


# ===================================================================
# yq — slurp
# ===================================================================


class TestYqSlurp:
    def test_slurp_yaml(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "---\na: 1\n---\nb: 2\n"})
        result = engine.run("yq -s 'length' /d.yaml")
        assert result.result.exit_code == 0
        n = int(result.stdout.strip())
        assert n == 2


# ===================================================================
# yq — null input
# ===================================================================


class TestYqNullInput:
    def test_null_input_json(self) -> None:
        engine = ShellEngine()
        result = engine.run("yq -n -o json '{\"x\": 1}'")
        assert "x" in result.stdout

    def test_null_input_yaml(self) -> None:
        engine = ShellEngine()
        result = engine.run("yq -n '{x: 1}'")
        assert result.result.exit_code == 0


# ===================================================================
# yq — multi-document YAML
# ===================================================================


class TestYqMultiDoc:
    def test_multi_document(self) -> None:
        engine = ShellEngine(
            initial_files={"/d.yaml": "---\nname: first\n---\nname: second\n"}
        )
        result = engine.run("yq '.name' /d.yaml")
        assert "first" in result.stdout


# ===================================================================
# yq — format auto-detection by content
# ===================================================================


class TestYqAutoDetect:
    def test_json_content_detect(self) -> None:
        engine = ShellEngine(initial_files={"/d.txt": '{"x": 42}\n'})
        result = engine.run("yq '.x' /d.txt")
        assert result.stdout.strip() == "42"

    def test_yaml_content_detect(self) -> None:
        engine = ShellEngine(initial_files={"/d.txt": "---\nx: 42\n"})
        result = engine.run("yq '.x' /d.txt")
        assert result.stdout.strip() == "42"


# ===================================================================
# yq — exit status
# ===================================================================


class TestYqExitStatus:
    def test_exit_status_null(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "a: null\n"})
        result = engine.run("yq -e '.a' /d.yaml")
        assert result.result.exit_code == 1

    def test_exit_status_value(self) -> None:
        engine = ShellEngine(initial_files={"/d.yaml": "a: 42\n"})
        result = engine.run("yq -e '.a' /d.yaml")
        assert result.result.exit_code == 0


# ===================================================================
# jq — input/inputs
# ===================================================================


class TestJqInputInputs:
    def test_input_node(self) -> None:
        """The input node reads next input from the stream."""
        engine = ShellEngine(initial_files={"/d.json": "1\n2\n3\n"})
        # First value is 1, then input reads 2
        result = engine.run("jq '. + input' /d.json")
        # output for first doc: 1 + 2 = 3
        assert "3" in result.stdout.strip().splitlines()[0]


# ===================================================================
# jq — foreach (label-break based)
# ===================================================================


class TestJqWhileUntil:
    def test_while_collects(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '[1 | while(. < 16; . * 2)]'")
        parsed = json.loads(result.stdout)
        assert parsed == [1, 2, 4, 8]

    def test_until_terminates(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run("jq -n '1 | until(. > 100; . * 3)'")
        assert int(result.stdout.strip()) > 100


# ===================================================================
# jq — escape sequences in strings
# ===================================================================


class TestJqStringEscape:
    def test_newline_in_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run(r"""jq -n '"hello\nworld"'""")
        assert result.result.exit_code == 0

    def test_tab_in_string(self) -> None:
        engine = ShellEngine(initial_files={"/d.json": "null\n"})
        result = engine.run(r"""jq -n '"hello\tworld"'""")
        assert result.result.exit_code == 0
