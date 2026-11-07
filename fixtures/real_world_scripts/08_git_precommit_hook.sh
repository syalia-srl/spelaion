#!/bin/bash
# Real-world problem: Pre-commit hook that validates staged files -- checks
# for debug statements, validates JSON/YAML syntax, enforces naming
# conventions, and reports a pass/fail summary. Blocks commits on failure.
#
# Bash features exercised:
#   arrays, for loop, if/elif/else, [[ =~ ]] regex match, case with glob
#   patterns, string operations (##, %%, substitution), functions, arithmetic,
#   exit codes, here-document for simulated data, pipeline

# Simulated staged files (normally: git diff --cached --name-only)
STAGED_FILES=$(cat <<'FILESEOF'
src/api/user_handler.py
src/api/order_service.py
src/utils/debug_helper.py
config/production.json
config/staging.json
tests/test_users.py
README.md
src/models/User.py
FILESEOF
)

# Simulated file contents (normally read from git staging area)
declare -A FILE_CONTENTS
FILE_CONTENTS[src/api/user_handler.py]='import os
def get_user(user_id):
    print("DEBUG: looking up user")
    return {"id": user_id}
'
FILE_CONTENTS[src/api/order_service.py]='def create_order(data):
    return {"status": "created"}
'
FILE_CONTENTS[config/production.json]='{"database": "prod-db", "port": 5432}'
FILE_CONTENTS[config/staging.json]='{"database": "stage-db", "port": 5432,}'

ERRORS=0
WARNINGS=0
CHECKED=0

echo "=== Pre-commit Checks ==="
echo ""

echo "$STAGED_FILES" | while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    CHECKED=$((CHECKED + 1))
    ext="${file##*.}"

    echo "Checking: ${file}"

    # 1. Naming convention check
    bname=$(basename "$file")
    name_no_ext="${bname%.*}"
    if [[ "$file" == *.py ]] && [[ "$name_no_ext" =~ [A-Z] ]]; then
        if [[ "$name_no_ext" != test_* ]]; then
            echo "  ERROR: ${file} -- Python files must be snake_case"
            ERRORS=$((ERRORS + 1))
        fi
    fi

    # 2. Debug statement check for source files
    case "$ext" in
        py|js|ts)
            content="${FILE_CONTENTS[$file]}"
            if [[ -n "$content" ]]; then
                if [[ "$content" == *'print("DEBUG'* ]]; then
                    echo "  ERROR: Debug print statement found in ${file}"
                    ERRORS=$((ERRORS + 1))
                fi
                if [[ "$content" == *'import pdb'* ]]; then
                    echo "  ERROR: pdb import found in ${file}"
                    ERRORS=$((ERRORS + 1))
                fi
                if [[ "$content" == *'console.log'* ]]; then
                    echo "  ERROR: console.log found in ${file}"
                    ERRORS=$((ERRORS + 1))
                fi
            fi
            ;;
    esac

    # 3. JSON syntax check (simple brace validation)
    if [[ "$ext" == "json" ]]; then
        content="${FILE_CONTENTS[$file]}"
        if [[ -n "$content" ]]; then
            # Check for trailing commas (common JSON error)
            if [[ "$content" == *',}'* ]] || [[ "$content" == *',]'* ]]; then
                echo "  ERROR: Trailing comma in ${file}"
                ERRORS=$((ERRORS + 1))
            fi
        fi
    fi

    # 4. Production config warnings
    if [[ "$file" == config/production* ]]; then
        echo "  WARNING: Modifying production config -- review carefully"
        WARNINGS=$((WARNINGS + 1))
    fi

done

echo ""
echo "=== Summary ==="
echo "Files checked: ${CHECKED}"
echo "Errors: ${ERRORS}"
echo "Warnings: ${WARNINGS}"
echo ""

if [[ $ERRORS -gt 0 ]]; then
    echo "COMMIT BLOCKED: Fix ${ERRORS} error(s) before committing"
    exit 1
else
    echo "All checks passed -- commit allowed"
    exit 0
fi
