#!/bin/bash
# Real-world problem: A lightweight test harness that runs shell commands,
# captures output, compares against expected values, and produces a TAP-style
# report. Used in projects too small for a real test framework.
#
# Bash features exercised:
#   functions, local variables, arrays, arithmetic, string comparison,
#   command substitution, exit codes ($?), [[ ]] with == and !=,
#   here-string (<<<), printf formatting, trap (conceptually)

PASS=0
FAIL=0
TOTAL=0
declare -a FAILURES

assert_eq() {
    local desc="$1"
    local actual="$2"
    local expected="$3"
    TOTAL=$((TOTAL + 1))

    if [[ "$actual" == "$expected" ]]; then
        PASS=$((PASS + 1))
        echo "ok ${TOTAL} - ${desc}"
    else
        FAIL=$((FAIL + 1))
        FAILURES+=("${desc}")
        echo "not ok ${TOTAL} - ${desc}"
        echo "  expected: '${expected}'"
        echo "  actual:   '${actual}'"
    fi
}

assert_contains() {
    local desc="$1"
    local haystack="$2"
    local needle="$3"
    TOTAL=$((TOTAL + 1))

    if [[ "$haystack" == *"$needle"* ]]; then
        PASS=$((PASS + 1))
        echo "ok ${TOTAL} - ${desc}"
    else
        FAIL=$((FAIL + 1))
        FAILURES+=("${desc}")
        echo "not ok ${TOTAL} - ${desc}"
        echo "  '${needle}' not found in output"
    fi
}

assert_exit_code() {
    local desc="$1"
    local cmd="$2"
    local expected_code="$3"
    TOTAL=$((TOTAL + 1))

    eval "$cmd" > /dev/null 2>&1
    local actual_code=$?

    if [[ "$actual_code" -eq "$expected_code" ]]; then
        PASS=$((PASS + 1))
        echo "ok ${TOTAL} - ${desc}"
    else
        FAIL=$((FAIL + 1))
        FAILURES+=("${desc}")
        echo "not ok ${TOTAL} - ${desc}"
        echo "  expected exit code: ${expected_code}"
        echo "  actual exit code:   ${actual_code}"
    fi
}

# --- Run test suite ---
echo "TAP version 13"

# Test arithmetic
RESULT=$(( 6 * 7 ))
assert_eq "basic multiplication" "$RESULT" "42"

# Test string operations
STR="Hello, World!"
assert_eq "string length" "${#STR}" "13"
assert_eq "substring extraction" "${STR:0:5}" "Hello"
assert_eq "lowercase conversion" "${STR,,}" "hello, world!"

# Test variable substitution
FILEPATH="/var/log/syslog.1.gz"
assert_eq "strip extension" "${FILEPATH%.gz}" "/var/log/syslog.1"
assert_eq "basename via ##" "${FILEPATH##*/}" "syslog.1.gz"
assert_eq "dirname via %" "${FILEPATH%/*}" "/var/log"

# Test array operations
declare -a NUMS=(10 20 30 40 50)
assert_eq "array length" "${#NUMS[@]}" "5"
assert_eq "array slice" "${NUMS[*]:1:3}" "20 30 40"

# Test pipeline output
SORTED=$(echo -e "banana\napple\ncherry" | sort | head -1)
assert_eq "sort pipeline" "$SORTED" "apple"

# Test word count
WC=$(echo "one two three four" | wc -w | tr -d ' ')
assert_eq "word count" "$WC" "4"

# Test pattern matching
VERSION="v3.12.1-rc2"
assert_contains "version has rc tag" "$VERSION" "-rc"

# --- Summary ---
echo ""
echo "1..${TOTAL}"
echo "# pass ${PASS}/${TOTAL}"
echo "# fail ${FAIL}/${TOTAL}"

if [[ ${#FAILURES[@]} -gt 0 ]]; then
    echo "# FAILED tests:"
    for f in "${FAILURES[@]}"; do
        echo "#   - ${f}"
    done
fi

if [[ $FAIL -eq 0 ]]; then
    echo "# All tests passed"
fi
