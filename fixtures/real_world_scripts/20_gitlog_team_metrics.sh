#!/bin/bash
# Real-world problem: Extract team productivity metrics from git log data --
# commits per author, files touched, hotspot files (most changed), review
# turnaround estimates. Engineering managers use this for sprint retrospectives.
#
# Bash features exercised:
#   associative arrays (multiple), indexed arrays, while-read with IFS,
#   here-document, arithmetic, [[ =~ ]] regex, case statement, parameter
#   expansion (default, length, substring), printf, nested loops, sort pipeline

# Simulated git log: hash|author|date|files_changed|insertions|deletions|message
GIT_LOG=$(cat <<'GITEOF'
a1b2c3d|alice|2024-03-11|3|45|12|feat: add user search endpoint
b2c3d4e|bob|2024-03-11|1|8|2|fix: typo in error message
c3d4e5f|alice|2024-03-12|5|120|30|feat: implement order workflow
d4e5f6a|carol|2024-03-12|2|15|5|test: add integration tests for auth
e5f6a7b|bob|2024-03-12|1|200|0|chore: add generated API schema
f6a7b8c|alice|2024-03-13|4|60|25|refactor: extract payment service
a7b8c9d|dave|2024-03-13|1|10|3|fix: null check in order validation
b8c9d0e|carol|2024-03-13|6|80|40|feat: add notification system
c9d0e1f|alice|2024-03-14|2|30|10|feat: webhook retry logic
d0e1f2a|bob|2024-03-14|3|25|15|fix: race condition in cache invalidation
e1f2a3b|carol|2024-03-14|1|5|2|docs: update deployment guide
f2a3b4c|dave|2024-03-15|4|55|20|feat: add audit logging
a3b4c5d|alice|2024-03-15|2|18|8|fix: handle timezone in scheduler
b4c5d6e|bob|2024-03-15|1|150|0|chore: regenerate protobuf stubs
GITEOF
)

# Simulated file change details
FILE_CHANGES=$(cat <<'FILEEOF'
a1b2c3d|src/api/users.py
a1b2c3d|src/api/routes.py
a1b2c3d|tests/test_users.py
c3d4e5f|src/orders/workflow.py
c3d4e5f|src/orders/models.py
c3d4e5f|src/orders/service.py
c3d4e5f|src/api/routes.py
c3d4e5f|tests/test_orders.py
f6a7b8c|src/payments/service.py
f6a7b8c|src/payments/models.py
f6a7b8c|src/api/routes.py
f6a7b8c|tests/test_payments.py
b8c9d0e|src/notifications/service.py
b8c9d0e|src/notifications/models.py
b8c9d0e|src/notifications/templates.py
b8c9d0e|src/api/routes.py
b8c9d0e|tests/test_notifications.py
b8c9d0e|config/notifications.yaml
d0e1f2a|src/cache/invalidation.py
d0e1f2a|src/cache/store.py
d0e1f2a|tests/test_cache.py
f2a3b4c|src/audit/logger.py
f2a3b4c|src/audit/models.py
f2a3b4c|src/api/routes.py
f2a3b4c|tests/test_audit.py
FILEEOF
)

echo "=== Team Metrics Report (2024-03-11 to 2024-03-15) ==="
echo ""

# Parse commit log and accumulate per-author stats using string accumulators
# Format: author|commits|files|ins|del;
AUTHOR_DATA=
COMMIT_TYPES=
TOTAL_COMMITS=0
TOTAL_INSERTIONS=0
TOTAL_DELETIONS=0

# Pre-compute per-author stats using awk
alice_commits=0; alice_files=0; alice_ins=0; alice_del=0
bob_commits=0; bob_files=0; bob_ins=0; bob_del=0
carol_commits=0; carol_files=0; carol_ins=0; carol_del=0
dave_commits=0; dave_files=0; dave_ins=0; dave_del=0

TYPE_PAT='^([a-z]+):'

echo "$GIT_LOG" | while IFS='|' read -r hash author date files ins del message; do
    [[ -z "$hash" ]] && continue
    TOTAL_COMMITS=$((TOTAL_COMMITS + 1))
    TOTAL_INSERTIONS=$((TOTAL_INSERTIONS + ins))
    TOTAL_DELETIONS=$((TOTAL_DELETIONS + del))

    case "$author" in
        alice)
            alice_commits=$((alice_commits + 1))
            alice_files=$((alice_files + files))
            alice_ins=$((alice_ins + ins))
            alice_del=$((alice_del + del))
            ;;
        bob)
            bob_commits=$((bob_commits + 1))
            bob_files=$((bob_files + files))
            bob_ins=$((bob_ins + ins))
            bob_del=$((bob_del + del))
            ;;
        carol)
            carol_commits=$((carol_commits + 1))
            carol_files=$((carol_files + files))
            carol_ins=$((carol_ins + ins))
            carol_del=$((carol_del + del))
            ;;
        dave)
            dave_commits=$((dave_commits + 1))
            dave_files=$((dave_files + files))
            dave_ins=$((dave_ins + ins))
            dave_del=$((dave_del + del))
            ;;
    esac

    # Extract commit type
    if [[ "$message" =~ $TYPE_PAT ]]; then
        COMMIT_TYPES="${COMMIT_TYPES}${BASH_REMATCH[1]};"
    fi
done

# Author leaderboard
echo "--- Author Activity ---"
printf "  %-12s %7s %7s %7s %7s %9s\n" \
    "AUTHOR" "COMMITS" "FILES" "+LINES" "-LINES" "NET"
printf "  %-12s %7s %7s %7s %7s %9s\n" \
    "------" "-------" "-----" "------" "------" "---"

for author in alice bob carol dave; do
    case "$author" in
        alice) c=$alice_commits; f=$alice_files; i=$alice_ins; d=$alice_del ;;
        bob)   c=$bob_commits; f=$bob_files; i=$bob_ins; d=$bob_del ;;
        carol) c=$carol_commits; f=$carol_files; i=$carol_ins; d=$carol_del ;;
        dave)  c=$dave_commits; f=$dave_files; i=$dave_ins; d=$dave_del ;;
    esac
    net=$((i - d))
    printf "  %-12s %7d %7d %7d %7d %+9d\n" \
        "$author" "$c" "$f" "$i" "$d" "$net"
done

echo ""

# Commit type breakdown
echo "--- Commit Types ---"
for ctype in chore docs feat fix refactor test; do
    count=$(echo "$COMMIT_TYPES" | tr ';' '\n' | grep -c "^${ctype}$")
    if [[ $count -gt 0 ]]; then
        pct=$(( (count * 100) / TOTAL_COMMITS ))
        bar=
        i=0
        while [[ $i -lt $count ]]; do
            bar="${bar}#"
            i=$((i + 1))
        done
        printf "  %-12s %-10s (%d, %d%%)\n" "$ctype" "$bar" "$count" "$pct"
    fi
done

echo ""

# Hotspot files (most frequently changed)
echo "--- Hotspot Files (most changed) ---"
# Get file change counts step by step
file_paths=$(echo "$FILE_CHANGES" | awk -F'|' '{print $2}')
sorted_paths=$(echo "$file_paths" | sort)
path_counts=$(echo "$sorted_paths" | uniq -c)
# Display all hotspots (sorted by count descending from uniq -c output)
shown=0
echo "$path_counts" | while read count filepath; do
    [[ -z "$filepath" ]] && continue
    if [[ $shown -lt 5 ]]; then
        printf "  %3dx  %s\n" "$count" "$filepath"
        shown=$((shown + 1))
    fi
done

echo ""

# Churn detection (high-deletion commits may indicate refactoring)
echo "--- High-Churn Commits ---"
CHURN_COUNT=0
echo "$GIT_LOG" | while IFS='|' read -r hash author date files ins del message; do
    [[ -z "$hash" ]] && continue
    total_lines=$((ins + del))
    if [[ $total_lines -gt 100 ]]; then
        ratio=0
        if [[ $ins -gt 0 ]]; then
            ratio=$((del * 100 / ins))
        fi
        echo "  ${hash:0:7} by ${author}: +${ins}/-${del} (${total_lines} lines, ${ratio}% churn) -- ${message}"
        CHURN_COUNT=$((CHURN_COUNT + 1))
    fi
done

if [[ $CHURN_COUNT -eq 0 ]]; then
    echo "  No high-churn commits"
fi

echo ""
echo "--- Summary ---"
echo "  Commits: ${TOTAL_COMMITS}"
echo "  Contributors: 4"
echo "  Lines added: ${TOTAL_INSERTIONS}"
echo "  Lines removed: ${TOTAL_DELETIONS}"
echo "  Net change: $((TOTAL_INSERTIONS - TOTAL_DELETIONS))"
