#!/bin/bash
# Real-world problem: Plan and validate database migration sequences --
# check that migrations are in order, detect gaps, identify reversible
# vs irreversible changes, and estimate downtime. DBAs use this before
# running migrations against production.
#
# Bash features exercised:
#   associative arrays, indexed arrays, while-read with IFS, arithmetic
#   (comparison, addition), case statement, string manipulation,
#   here-document, functions, printf, nested conditionals

# Simulated migration manifest: id|date|desc|status|reversible|speed
MIGRATIONS=$(cat <<'MIGEOF'
001|2024-01-15|create_users_table|applied|reversible|fast
002|2024-01-20|create_orders_table|applied|reversible|fast
003|2024-02-01|add_email_index_users|applied|reversible|fast
004|2024-02-15|populate_default_roles|applied|irreversible|slow
005|2024-03-01|add_payment_columns|applied|reversible|fast
006|2024-03-05|migrate_legacy_addresses|applied|irreversible|slow
008|2024-03-15|add_shipping_table|applied|reversible|fast
009|2024-03-20|drop_deprecated_columns|pending|irreversible|medium
010|2024-03-25|add_audit_timestamps|pending|reversible|fast
MIGEOF
)

echo "=== Database Migration Plan ==="
echo ""

# Check for gaps in sequence
echo "--- Sequence Validation ---"
PREV_ID=0
GAPS=0
# Extract just the IDs
echo "$MIGRATIONS" | while IFS='|' read -r id rest; do
    [[ -z "$id" ]] && continue
    num=$(echo "$id" | sed 's/^0*//')
    num=${num:-0}
    expected=$((PREV_ID + 1))
    if [[ $num -ne $expected ]]; then
        gap_id=$(printf '%03d' $expected)
        echo "  GAP: Missing migration ${gap_id} between ${PREV_ID} and ${num}"
        GAPS=$((GAPS + 1))
    fi
    PREV_ID=$num
done

if [[ $GAPS -eq 0 ]]; then
    echo "  Sequence OK (no gaps)"
fi

echo ""
echo "--- Migration Status ---"
printf "  %-5s %-12s %-30s %-10s %-12s %s\n" \
    "ID" "DATE" "DESCRIPTION" "STATUS" "REVERSIBLE" "SPEED"
printf "  %-5s %-12s %-30s %-10s %-12s %s\n" \
    "--" "----" "-----------" "------" "----------" "-----"

APPLIED_COUNT=0
PENDING_COUNT=0
IRREVERSIBLE_PENDING=0
PENDING_DATA=
TOTAL_MIGRATIONS=0

echo "$MIGRATIONS" | while IFS='|' read -r id date desc status reversible speed; do
    [[ -z "$id" ]] && continue
    TOTAL_MIGRATIONS=$((TOTAL_MIGRATIONS + 1))

    case "$status" in
        applied)
            marker="[OK]"
            APPLIED_COUNT=$((APPLIED_COUNT + 1))
            ;;
        pending)
            marker="[--]"
            PENDING_COUNT=$((PENDING_COUNT + 1))
            PENDING_DATA="${PENDING_DATA}${id}|${desc}|${reversible}|${speed};"
            if [[ "$reversible" == "irreversible" ]]; then
                IRREVERSIBLE_PENDING=$((IRREVERSIBLE_PENDING + 1))
            fi
            ;;
        *)
            marker="[??]"
            ;;
    esac

    printf "  %-5s %-12s %-30s %-4s %-5s %-12s %s\n" \
        "$id" "$date" "$desc" "$marker" "$status" "$reversible" "$speed"
done

# Estimate downtime for pending migrations
echo ""
echo "--- Pending Migration Plan ---"
TOTAL_ESTIMATE=0

if [[ -n "$PENDING_DATA" ]]; then
    # Parse each pending entry from the semicolon-separated string
    remaining="$PENDING_DATA"
    while [[ -n "$remaining" ]]; do
        # Get first entry (before ;)
        entry="${remaining%%;*}"
        # Remove it from remaining
        if [[ "$remaining" == *";"* ]]; then
            remaining="${remaining#*;}"
        else
            remaining=
        fi
        [[ -z "$entry" ]] && continue

        # Parse id|desc|reversible|speed
        IFS='|' read -r id desc reversible speed <<< "$entry"
        [[ -z "$id" ]] && continue
        case "$speed" in
            fast)   est=1 ;;
            medium) est=5 ;;
            slow)   est=15 ;;
            *)      est=10 ;;
        esac
        TOTAL_ESTIMATE=$((TOTAL_ESTIMATE + est))
        echo "  ${id}: ${desc} (~${est} min, ${reversible})"
    done
else
    echo "  No pending migrations"
fi

echo ""
echo "--- Risk Assessment ---"
RISK="LOW"
if [[ $IRREVERSIBLE_PENDING -gt 0 ]]; then
    echo "  WARNING: ${IRREVERSIBLE_PENDING} pending migration(s) are irreversible"
    RISK="MEDIUM"
fi
if [[ $GAPS -gt 0 ]]; then
    echo "  WARNING: ${GAPS} gap(s) in migration sequence"
    RISK="HIGH"
fi

echo ""
echo "--- Summary ---"
echo "  Total migrations: ${TOTAL_MIGRATIONS}"
echo "  Applied: ${APPLIED_COUNT}"
echo "  Pending: ${PENDING_COUNT}"
echo "  Sequence gaps: ${GAPS}"
echo "  Estimated downtime: ~${TOTAL_ESTIMATE} minutes"
echo "  Risk level: ${RISK}"
