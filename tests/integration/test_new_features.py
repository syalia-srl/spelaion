"""Integration tests for the 6 new bash syntax features.

Phase 1: Parameter expansion operators
Phase 2: Here-documents and here-strings
Phase 3: C-style for loops
Phase 4: Array variables
Phase 5: [[ ]] extended test
Phase 6: Process substitution
"""

from agentsh.api.engine import ShellEngine

# =========================================================================
# Phase 1: Parameter Expansion Operators
# =========================================================================


class TestParamExpansionLength:
    """${#var} — string length."""

    def test_length_of_string(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${#x}")
        assert result.stdout.strip() == "5"

    def test_length_of_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=; echo ${#x}")
        assert result.stdout.strip() == "0"

    def test_length_of_unset(self) -> None:
        engine = ShellEngine()
        result = engine.run("echo ${#x}")
        assert result.stdout.strip() == "0"


class TestParamExpansionSubstring:
    """${var:offset} and ${var:offset:length}."""

    def test_substring_offset(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x:2}")
        assert result.stdout.strip() == "llo"

    def test_substring_offset_length(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x:1:3}")
        assert result.stdout.strip() == "ell"

    def test_substring_from_start(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x:0:3}")
        assert result.stdout.strip() == "hel"

    def test_substring_negative_offset(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x: -2}")
        assert result.stdout.strip() == "lo"


class TestParamExpansionReplace:
    """${var/pattern/replacement} and ${var//pattern/replacement}."""

    def test_replace_first(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x/l/L}")
        assert result.stdout.strip() == "heLlo"

    def test_replace_all(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x//l/L}")
        assert result.stdout.strip() == "heLLo"

    def test_replace_delete(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x/l/}")
        assert result.stdout.strip() == "helo"


class TestParamExpansionCase:
    """${var^}, ${var^^}, ${var,}, ${var,,}."""

    def test_uppercase_first(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x^}")
        assert result.stdout.strip() == "Hello"

    def test_uppercase_all(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=hello; echo ${x^^}")
        assert result.stdout.strip() == "HELLO"

    def test_lowercase_first(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=HELLO; echo ${x,}")
        assert result.stdout.strip() == "hELLO"

    def test_lowercase_all(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=HELLO; echo ${x,,}")
        assert result.stdout.strip() == "hello"


# =========================================================================
# Phase 2: Here-Documents & Here-Strings
# =========================================================================


class TestHereStrings:
    """<<< word."""

    def test_basic_herestring(self) -> None:
        engine = ShellEngine()
        result = engine.run('cat <<< "hello"')
        assert result.stdout.strip() == "hello"

    def test_herestring_with_variable(self) -> None:
        engine = ShellEngine()
        result = engine.run('x=world; cat <<< "hello $x"')
        assert result.stdout.strip() == "hello world"

    def test_herestring_single_word(self) -> None:
        engine = ShellEngine()
        result = engine.run("cat <<< hello")
        assert result.stdout.strip() == "hello"


class TestHereDocuments:
    """<< EOF."""

    def test_basic_heredoc(self) -> None:
        engine = ShellEngine()
        result = engine.run("cat <<EOF\nhello\nworld\nEOF")
        output = result.stdout.strip()
        assert "hello" in output
        assert "world" in output

    def test_heredoc_quoted_delimiter_no_expansion(self) -> None:
        engine = ShellEngine()
        result = engine.run("x=val; cat <<'EOF'\n$x\nEOF")
        assert "$x" in result.stdout


# =========================================================================
# Phase 3: C-Style For Loops
# =========================================================================


class TestCStyleFor:
    """for (( init; cond; update )); do body; done."""

    def test_basic_c_for(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=0; i<5; i++ )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["0", "1", "2", "3", "4"]

    def test_c_for_decrement(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=3; i>0; i-- )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["3", "2", "1"]

    def test_c_for_step(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=0; i<10; i+=3 )); do echo $i; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["0", "3", "6", "9"]

    def test_c_for_empty_body(self) -> None:
        engine = ShellEngine()
        result = engine.run("for (( i=0; i<3; i++ )); do true; done; echo done")
        assert "done" in result.stdout


# =========================================================================
# Phase 4: Array Variables
# =========================================================================


class TestArrayVariables:
    """arr=(a b c), ${arr[0]}, ${arr[@]}, ${#arr[@]}."""

    def test_array_assignment_and_index(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c); echo ${arr[1]}")
        assert result.stdout.strip() == "b"

    def test_array_all_elements(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(hello world); echo ${arr[@]}")
        assert result.stdout.strip() == "hello world"

    def test_array_count(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c d); echo ${#arr[@]}")
        assert result.stdout.strip() == "4"

    def test_array_element_assignment(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(a b c); arr[0]=x; echo ${arr[0]}")
        assert result.stdout.strip() == "x"

    def test_array_iteration(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(one two three); for x in ${arr[@]}; do echo $x; done")
        lines = result.stdout.strip().split("\n")
        assert lines == ["one", "two", "three"]

    def test_array_first_element(self) -> None:
        engine = ShellEngine()
        result = engine.run("arr=(first second); echo ${arr[0]}")
        assert result.stdout.strip() == "first"


# =========================================================================
# Phase 5: [[ ]] Extended Test
# =========================================================================


class TestExtendedTest:
    """[[ expression ]]."""

    def test_glob_match(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "hello" == h* ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_glob_no_match(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "hello" == x* ]] && echo yes || echo no')
        assert result.stdout.strip() == "no"

    def test_regex_match(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "abc123" =~ ^[a-z]+[0-9]+$ ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_regex_no_match(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "abc" =~ ^[0-9]+$ ]] && echo yes || echo no')
        assert result.stdout.strip() == "no"

    def test_not_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ -n "hello" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_empty(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ -z "" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_negation(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ ! -z "hello" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_string_not_equal(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ "a" != "b" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_file_test(self) -> None:
        engine = ShellEngine(initial_files={"/tmp/test.txt": "content"})
        result = engine.run("[[ -f /tmp/test.txt ]] && echo yes || echo no")
        assert result.stdout.strip() == "yes"

    def test_and_operator(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ -n "a" && -n "b" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_or_operator(self) -> None:
        engine = ShellEngine()
        result = engine.run('[[ -z "a" || -n "b" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_bash_rematch(self) -> None:
        engine = ShellEngine()
        result = engine.run(
            '[[ "hello123" =~ ^([a-z]+)([0-9]+)$ ]] && echo ${BASH_REMATCH[1]}'
        )
        assert result.stdout.strip() == "hello"


# =========================================================================
# Phase 6: Process Substitution
# =========================================================================


class TestProcessSubstitution:
    """<(cmd) and >(cmd)."""

    def test_basic_process_substitution(self) -> None:
        engine = ShellEngine()
        result = engine.run("cat <(echo hello)")
        assert result.stdout.strip() == "hello"

    def test_two_process_substitutions(self) -> None:
        engine = ShellEngine()
        result = engine.run("cat <(echo a) <(echo b)")
        # Both process subs produce /dev/fd/N paths that get passed as args
        assert result.result.exit_code == 0

    def test_process_substitution_in_word(self) -> None:
        engine = ShellEngine()
        result = engine.run('wc -l <(echo -e "a\nb\nc")')
        # Just check it doesn't error — output depends on wc implementation
        assert result.result.exit_code == 0 or "/dev/fd/" in result.stdout


# =========================================================================
# Cross-feature integration tests
# =========================================================================


class TestCrossFeature:
    """Tests combining multiple new features."""

    def test_array_with_c_for(self) -> None:
        engine = ShellEngine()
        result = engine.run(
            "arr=(a b c); for (( i=0; i<${#arr[@]}; i++ )); do echo ${arr[$i]}; done"
        )
        lines = result.stdout.strip().split("\n")
        assert lines == ["a", "b", "c"]

    def test_extended_test_with_param_expansion(self) -> None:
        engine = ShellEngine()
        result = engine.run('x=HELLO; [[ "${x,,}" == "hello" ]] && echo yes || echo no')
        assert result.stdout.strip() == "yes"

    def test_herestring_with_param_expansion(self) -> None:
        engine = ShellEngine()
        result = engine.run('x=hello; cat <<< "${x^^}"')
        assert result.stdout.strip() == "HELLO"
