#!/bin/bash
# Real-world problem: Run a batch of data processing jobs with bounded
# concurrency, track success/failure for each, and produce a summary.
# Used in ETL pipelines where each job is independent but you can't
# run all at once due to resource limits.
#
# Bash features exercised:
#   functions, arrays, associative arrays, while loop with counter,
#   arithmetic expressions, for loop, case statement, parameter expansion,
#   printf formatting, string operations, [[ ]] conditionals

# Simulated job definitions: name|duration_class|expected_result
JOBS=$(cat <<'JOBEOF'
import-users|fast|success
import-orders|slow|success
import-products|fast|success
import-reviews|fast|failure
import-inventory|medium|success
import-categories|fast|success
import-suppliers|medium|success
import-shipments|slow|failure
import-payments|medium|success
import-analytics|fast|success
JOBEOF
)

MAX_CONCURRENT="${MAX_JOBS:-3}"
declare -A JOB_STATUS    # job -> pending|running|done|failed
declare -A JOB_DURATION  # job -> simulated time
declare -a JOB_ORDER     # all job names in order
declare -a COMPLETED
declare -a FAILED

# Parse jobs
while IFS='|' read -r name speed result; do
    [[ -z "$name" ]] && continue
    JOB_ORDER+=("$name")
    JOB_STATUS[$name]="pending"

    case "$speed" in
        fast)   JOB_DURATION[$name]=1 ;;
        medium) JOB_DURATION[$name]=3 ;;
        slow)   JOB_DURATION[$name]=5 ;;
    esac

    # Store expected result for simulation
    if [[ "$result" == "failure" ]]; then
        JOB_STATUS[$name]="will_fail"
    fi
done <<< "$JOBS"

TOTAL=${#JOB_ORDER[@]}
echo "=== Parallel Job Runner ==="
echo "Jobs: ${TOTAL}, Max concurrent: ${MAX_CONCURRENT}"
echo ""

# Simulate batch execution
BATCH=0
INDEX=0

while [[ $INDEX -lt $TOTAL ]]; do
    BATCH=$((BATCH + 1))
    BATCH_SIZE=0
    BATCH_NAMES=""

    # Fill a batch up to MAX_CONCURRENT
    BATCH_START=$INDEX
    while [[ $BATCH_SIZE -lt $MAX_CONCURRENT ]] && [[ $INDEX -lt $TOTAL ]]; do
        name="${JOB_ORDER[$INDEX]}"
        BATCH_SIZE=$((BATCH_SIZE + 1))
        if [[ -n "$BATCH_NAMES" ]]; then
            BATCH_NAMES="${BATCH_NAMES}, ${name}"
        else
            BATCH_NAMES="$name"
        fi
        INDEX=$((INDEX + 1))
    done

    echo "--- Batch ${BATCH} (${BATCH_SIZE} jobs) ---"
    echo "  Running: ${BATCH_NAMES}"

    # Process batch
    i=$BATCH_START
    while [[ $i -lt $INDEX ]]; do
        name="${JOB_ORDER[$i]}"
        duration="${JOB_DURATION[$name]}"

        if [[ "${JOB_STATUS[$name]}" == "will_fail" ]]; then
            JOB_STATUS[$name]="failed"
            FAILED+=("$name")
            printf "  %-25s [FAIL]  (%ss)\n" "$name" "$duration"
        else
            JOB_STATUS[$name]="done"
            COMPLETED+=("$name")
            printf "  %-25s [OK]    (%ss)\n" "$name" "$duration"
        fi
        i=$((i + 1))
    done
    echo ""
done

# Summary
PASS_COUNT=${#COMPLETED[@]}
FAIL_COUNT=${#FAILED[@]}
SUCCESS_RATE=0
if [[ $TOTAL -gt 0 ]]; then
    SUCCESS_RATE=$(( (PASS_COUNT * 100) / TOTAL ))
fi

echo "=== Summary ==="
echo "  Total: ${TOTAL}"
echo "  Passed: ${PASS_COUNT}"
echo "  Failed: ${FAIL_COUNT}"
echo "  Success rate: ${SUCCESS_RATE}%"
echo "  Batches: ${BATCH}"

if [[ $FAIL_COUNT -gt 0 ]]; then
    echo ""
    echo "  Failed jobs:"
    for name in "${FAILED[@]}"; do
        echo "    - ${name}"
    done
fi
