#!/bin/bash
# Real-world problem: Rename source files from CamelCase to snake_case,
# update all import/require references across the codebase. Used during
# style guide adoption or framework migrations.
#
# Bash features exercised:
#   parameter expansion (substitution, case conversion), [[ =~ ]] regex,
#   associative arrays for rename mapping, for loops over array keys,
#   string replacement ${var//old/new}, functions, arrays, here-document

# Simulated project file listing
FILE_LIST=$(cat <<'FILEOF'
src/UserService.py
src/OrderHandler.py
src/PaymentGateway.py
src/utils/HttpClient.py
src/utils/JsonParser.py
tests/TestUserService.py
tests/TestOrderHandler.py
FILEOF
)

# Simulated file contents with imports
declare -A FILE_IMPORTS
FILE_IMPORTS[src/OrderHandler.py]='from UserService import get_user
from utils.HttpClient import make_request'
FILE_IMPORTS[src/PaymentGateway.py]='from OrderHandler import create_order
from utils.JsonParser import parse_response'
FILE_IMPORTS[tests/TestUserService.py]='from UserService import get_user
from UserService import list_users'
FILE_IMPORTS[tests/TestOrderHandler.py]='from OrderHandler import create_order
from UserService import get_user'

# Convert CamelCase to snake_case using character-by-character iteration
to_snake_case() {
    local input
    input="$1"
    local result
    result=
    local len
    len=${#input}
    local i
    i=1
    while [[ $i -le $len ]]; do
        char=$(echo "$input" | cut -c${i})
        if echo "$char" | grep -q '[A-Z]'; then
            if [[ $i -gt 1 ]]; then
                prev=$(echo "$input" | cut -c$((i - 1)))
                if echo "$prev" | grep -q '[a-z]'; then
                    result="${result}_"
                fi
            fi
        fi
        lower=$(echo "$char" | tr 'A-Z' 'a-z')
        result="${result}${lower}"
        i=$((i + 1))
    done
    echo "$result"
}

echo "=== File Migration: CamelCase -> snake_case ==="
echo ""

# Phase 1: Build rename map using direct assignments
# Compute snake_case for each known CamelCase module name
declare -A RENAME_MAP
RENAME_MAP[UserService]=$(to_snake_case "UserService")
RENAME_MAP[OrderHandler]=$(to_snake_case "OrderHandler")
RENAME_MAP[PaymentGateway]=$(to_snake_case "PaymentGateway")
RENAME_MAP[HttpClient]=$(to_snake_case "HttpClient")
RENAME_MAP[JsonParser]=$(to_snake_case "JsonParser")
RENAME_MAP[TestUserService]=$(to_snake_case "TestUserService")
RENAME_MAP[TestOrderHandler]=$(to_snake_case "TestOrderHandler")

RENAME_COUNT=0

echo "--- Phase 1: Computing Renames ---"
echo "$FILE_LIST" | while IFS= read -r filepath; do
    [[ -z "$filepath" ]] && continue
    dir=$(dirname "$filepath")
    bname=$(basename "$filepath")
    name="${bname%.py}"

    new_name="${RENAME_MAP[$name]}"
    if [[ -n "$new_name" ]] && [[ "$new_name" != "$name" ]]; then
        new_path="${dir}/${new_name}.py"
        RENAME_COUNT=$((RENAME_COUNT + 1))
        echo "  ${filepath} -> ${new_path}"
    else
        echo "  ${filepath} (unchanged)"
    fi
done

echo ""
echo "--- Phase 2: Updating Import References ---"

IMPORT_UPDATES=0
for filepath in ${!FILE_IMPORTS[@]}; do
    content="${FILE_IMPORTS[$filepath]}"
    updated="$content"
    changes=0

    for old_name in ${!RENAME_MAP[@]}; do
        new_name="${RENAME_MAP[$old_name]}"
        if [[ "$updated" == *"$old_name"* ]]; then
            updated="${updated//$old_name/$new_name}"
            changes=$((changes + 1))
            IMPORT_UPDATES=$((IMPORT_UPDATES + 1))
        fi
    done

    if [[ $changes -gt 0 ]]; then
        echo "  ${filepath}: ${changes} import(s) updated"
        echo "$updated" | while IFS= read -r line; do
            echo "    ${line}"
        done
    fi
done

echo ""
echo "--- Summary ---"
echo "  Files renamed: ${#RENAME_MAP[@]}"
echo "  Import references updated: ${IMPORT_UPDATES}"
echo "  Rename mappings:"
for old_name in ${!RENAME_MAP[@]}; do
    echo "    ${old_name} -> ${RENAME_MAP[$old_name]}"
done
