"""Additional tests to ensure thorough coverage of new bash syntax features.

Focuses on edge cases and code paths not covered by the main test file.
"""

from agentsh.api.engine import ShellEngine

# =========================================================================
# ArithEvaluator coverage: eval_statement edge cases
# =========================================================================


class TestArithStatementEdgeCases:
    """Cover eval_statement paths: comma, pre-increment, pre-decrement,
    compound div/mod, empty expression, plain expression fallback."""

    def test_comma_separated_expressions(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=0, j=10; i<3; i++, j-- )); do echo $i $j; done")
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "0 10"
        assert lines[1] == "1 9"
        assert lines[2] == "2 8"

    def test_pre_increment(self) -> None:
        engine = ShellEngine()
        result = engine.run("i=5; for (( ; i<8; ++i )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["5", "6", "7"]

    def test_pre_decrement(self) -> None:
        engine = ShellEngine()
        result = engine.run("i=3; for (( ; i>0; --i )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["3", "2", "1"]

    def test_compound_multiply_assign(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=1; i<20; i*=2 )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["1", "2", "4", "8", "16"]

    def test_compound_divide_assign(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=16; i>0; i/=2 )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["16", "8", "4", "2", "1"]

    def test_compound_modulo_assign(self) -> None:
        engine = ShellEngine()
        result = engine.run("i=17; for (( ; i>3; i%=7 )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines[0] == "17"

    def test_compound_subtract_assign(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=10; i>0; i-=3 )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["10", "7", "4", "1"]

    def test_empty_init(self) -> None:
        engine = ShellEngine()
        result = engine.run("i=0; for (( ; i<3; i++ )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["0", "1", "2"]

    def test_post_decrement_in_for(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=5; i>2; i-- )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["5", "4", "3"]


# =========================================================================
# ArithEvaluator coverage: comparison/boolean/ternary in expressions
# =========================================================================


class TestArithExprExtended:
    """Cover comparison operators, logical ops, ternary, bitwise,
    and NOT in arithmetic expressions."""

    def test_comparison_less_than(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 3 < 5 ))")
        assert result.stdout.strip() == "1"

    def test_comparison_greater_equal(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 5 >= 5 ))")
        assert result.stdout.strip() == "1"

    def test_comparison_equal(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 3 == 3 ))")
        assert result.stdout.strip() == "1"

    def test_comparison_not_equal(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 3 != 4 ))")
        assert result.stdout.strip() == "1"

    def test_comparison_less_equal(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 3 <= 3 ))")
        assert result.stdout.strip() == "1"

    def test_comparison_greater_than(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 5 > 3 ))")
        assert result.stdout.strip() == "1"

    def test_logical_and(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 1 && 1 ))")
        assert result.stdout.strip() == "1"

    def test_logical_and_false(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 1 && 0 ))")
        assert result.stdout.strip() == "0"

    def test_logical_or(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 0 || 1 ))")
        assert result.stdout.strip() == "1"

    def test_logical_or_false(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 0 || 0 ))")
        assert result.stdout.strip() == "0"

    def test_logical_not(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( !0 ))")
        assert result.stdout.strip() == "1"

    def test_logical_not_true(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( !1 ))")
        assert result.stdout.strip() == "0"

    def test_ternary_true(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 1 ? 42 : 99 ))")
        assert result.stdout.strip() == "42"

    def test_ternary_false(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 0 ? 42 : 99 ))")
        assert result.stdout.strip() == "99"

    def test_bitwise_and(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 5 & 3 ))")
        assert result.stdout.strip() == "1"

    def test_bitwise_or(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 5 | 3 ))")
        assert result.stdout.strip() == "7"

    def test_bitwise_xor(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 5 ^ 3 ))")
        assert result.stdout.strip() == "6"

    def test_left_shift(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 1 << 3 ))")
        assert result.stdout.strip() == "8"

    def test_right_shift(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 8 >> 2 ))")
        assert result.stdout.strip() == "2"

    def test_power(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo $(( 2 ** 10 ))")
        assert result.stdout.strip() == "1024"


# =========================================================================
# ArithEvaluator coverage: braced expansions in arithmetic context
# =========================================================================


class TestArithBracedExpansions:
    """Cover _expand_braced_expansions: ${#var}, ${arr[n]}."""

    def test_strlen_in_arith(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo $(( ${#x} + 1 ))")
        assert result.stdout.strip() == "6"

    def test_array_element_in_arith(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(10 20 30); echo $(( ${arr[1]} + 5 ))")
        assert result.stdout.strip() == "25"

    def test_array_count_star_in_arith(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c d e); echo $(( ${#arr[*]} ))")
        assert result.stdout.strip() == "5"


# =========================================================================
# BoolEvaluator coverage: grouping, extended test edge cases
# =========================================================================


class TestExtendedTestEdgeCases:
    """Cover grouping with (), string comparisons, logical short-circuit."""

    def test_grouping_with_parens(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ ( -z "" ) && ( -n "x" ) ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_or_short_circuit(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ -z "" || -z "notempty" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_regex_no_match(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "hello" =~ ^[0-9]+$ ]] && echo yes || echo no')
        assert result.stdout.strip() == "no"

    def test_integer_comparison_in_extended(self) -> None:
        engine = ShellEngine()
        result = engine.run("[[ 5 -gt 3 ]] && echo yes || echo no")
        assert result.stdout.strip() == "yes"

    def test_double_negation(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ ! ! -n "x" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_empty_string_is_false(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=; [[ $x ]] && echo yes || echo no")
        assert result.stdout.strip() == "no"

    def test_glob_match_question_mark(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "ab" == a? ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"


# =========================================================================
# WordEvaluator coverage: array subscript with operator, process sub >(cmd)
# =========================================================================


class TestArraySubscriptWithOperator:
    """Cover ${arr[idx]:-default} and similar combined forms."""

    def test_array_element_with_default(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b); echo ${arr[5]:-fallback}")
        assert result.stdout.strip() == "fallback"

    def test_array_element_with_uppercase(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(hello world); echo ${arr[0]^^}")
        assert result.stdout.strip() == "HELLO"

    def test_scalar_as_array_element_zero(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x[0]}")
        assert result.stdout.strip() == "hello"

    def test_array_star_expansion(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c); echo ${arr[*]}")
        assert result.stdout.strip() == "a b c"


class TestProcessSubstitutionOutput:
    """Cover >(cmd) direction."""

    def test_output_process_sub(self) -> None:
        # >(cmd) creates a temp file and returns its path
        engine = ShellEngine()
        result = engine.run("echo >(echo test)")
        # Should output a /dev/fd/N path
        assert "/dev/fd/" in result.stdout


# =========================================================================
# Parameter expansion edge cases
# =========================================================================


class TestParamExpansionEdgeCases:
    """Additional parameter expansion coverage."""

    def test_replace_with_glob(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=foobar; echo ${x/foo/baz}")
        assert result.stdout.strip() == "bazbar"

    def test_replace_all_with_glob(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=abcabc; echo ${x//abc/X}")
        assert result.stdout.strip() == "XX"

    def test_substring_zero_offset(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=abcdef; echo ${x:0}")
        assert result.stdout.strip() == "abcdef"

    def test_substring_beyond_length(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=abc; echo ${x:0:10}")
        assert result.stdout.strip() == "abc"

    def test_uppercase_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=; echo ${x^}")
        assert result.stdout.strip() == ""

    def test_lowercase_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=; echo ${x,}")
        assert result.stdout.strip() == ""

    def test_length_operator_with_array(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(one two three); echo ${#arr[@]}")
        assert result.stdout.strip() == "3"

    def test_replace_no_match(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x/z/Z}")
        assert result.stdout.strip() == "hello"


# =========================================================================
# Here-doc and here-string edge cases
# =========================================================================


class TestHeredocEdgeCases:
    """Additional here-doc coverage."""

    def test_herestring_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run('cat <<< ""')
        assert result.stdout.strip() == ""

    def test_heredoc_multiline(self) -> None:
        engine = ShellEngine()
        result = engine.run("cat <<EOF\nline1\nline2\nline3\nEOF")
        assert "line1" in result.stdout
        assert "line2" in result.stdout
        assert "line3" in result.stdout


# =========================================================================
# State: array storage edge cases
# =========================================================================


class TestArrayStateEdgeCases:
    """Cover array state operations: extend on set_array_element, unset arrays."""

    def test_array_extend_on_set(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(); arr[3]=x; echo ${arr[3]}")
        assert result.stdout.strip() == "x"

    def test_array_overwrite(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c); arr=(x y); echo ${arr[@]}")
        assert result.stdout.strip() == "x y"

    def test_array_count_star(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c); echo ${#arr[*]}")
        assert result.stdout.strip() == "3"


# =========================================================================
# Extended test: string comparison operators and edge cases
# =========================================================================


class TestExtendedTestStringComparisons:
    """Cover [[ ]] string < and > operators and fallback paths."""

    def test_string_less_than(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "abc" < "def" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_string_greater_than(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "xyz" > "abc" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_string_less_than_false(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "z" < "a" ]] && echo yes || echo no')
        assert result.stdout.strip() == "no"

    def test_string_greater_than_false(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "a" > "z" ]] && echo yes || echo no')
        assert result.stdout.strip() == "no"


# =========================================================================
# State: array element out-of-bounds and new-array-via-subscript
# =========================================================================


class TestArrayBoundaryEdgeCases:
    """Cover get_array_element returning None and set_array_element creating arrays."""

    def test_array_out_of_bounds(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b); echo ${arr[99]}")
        assert result.stdout.strip() == ""

    def test_set_element_creates_array(self) -> None:
        engine = ShellEngine()
        result = engine.run("newarr[2]=hello; echo ${newarr[2]}")
        assert result.stdout.strip() == "hello"

    def test_set_element_extends_with_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run(
            "arr=(); arr[3]=x; echo ${arr[0]}-${arr[1]}-${arr[2]}-${arr[3]}"
        )
        assert result.stdout.strip() == "---x"


# =========================================================================
# Param expansion argument with nested $var
# =========================================================================


class TestParamExpansionNestedVars:
    """Cover _expand_arg_string with nested variable references."""

    def test_default_with_variable(self) -> None:
        engine = ShellEngine()
        result = engine.run("fallback=world; echo ${x:-$fallback}")
        assert result.stdout.strip() == "world"

    def test_default_with_braced_variable(self) -> None:
        engine = ShellEngine()
        result = engine.run("fallback=world; echo ${x:-${fallback}}")
        assert result.stdout.strip() == "world"
