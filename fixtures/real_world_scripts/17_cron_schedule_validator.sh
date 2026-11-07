#!/bin/bash
# Real-world problem: Parse and validate cron schedules, detect overlapping
# jobs, and identify risk windows where too many heavy jobs run at once.
# Ops teams use this to audit crontabs before deploying.
#
# Bash features exercised:
#   IFS-based field splitting, arrays (indexed + associative), nested for
#   loops, arithmetic (modulo, division, comparison), [[ =~ ]] regex,
#   case statement, functions, here-document, printf, string manipulation

CRONTAB=$(cat <<'CRONEOF'
# minute hour dom month dow command
0 * * * * health-check --all
*/5 * * * * metrics-collector
0 2 * * * db-backup --full
30 2 * * * db-vacuum
0 3 * * 0 weekly-report-gen
*/15 * * * * log-rotator
0 2 * * * cache-rebuild --force
0 4 * * 1-5 etl-pipeline --daily
CRONEOF
)

declare -A HOUR_LOAD     # hour -> number of jobs that can run
declare -a JOB_NAMES
declare -a JOB_SCHEDULES
declare -a PARSE_ERRORS

parse_cron_field() {
    local field="$1"
    local max="$2"
    local result=""

    if [[ "$field" == "*" ]]; then
        # Every value
        echo "every"
        return
    elif [[ "$field" =~ ^\*/([0-9]+)$ ]]; then
        # Step syntax */N
        local step="${BASH_REMATCH[1]}"
        if [[ $step -le 0 ]] || [[ $step -gt $max ]]; then
            echo "error"
            return
        fi
        echo "every-${step}"
        return
    elif [[ "$field" =~ ^([0-9]+)-([0-9]+)$ ]]; then
        # Range N-M
        echo "range-${BASH_REMATCH[1]}-${BASH_REMATCH[2]}"
        return
    elif [[ "$field" =~ ^[0-9]+$ ]]; then
        # Specific value
        echo "at-${field}"
        return
    else
        echo "error"
        return
    fi
}

echo "=== Crontab Audit Report ==="
echo ""

# Initialize hour load
for h in $(seq 0 23); do
    HOUR_LOAD[$h]=0
done

# Parse each cron entry
echo "--- Schedule Analysis ---"
ENTRY_NUM=0
while IFS= read -r line; do
    # Skip comments and empty lines
    [[ "$line" == \#* ]] && continue
    [[ -z "$line" ]] && continue

    ENTRY_NUM=$((ENTRY_NUM + 1))

    # Split fields
    read -r minute hour dom month dow command <<< "$line"

    JOB_NAMES+=("$command")
    JOB_SCHEDULES+=("$minute $hour $dom $month $dow")

    # Parse hour field to compute load
    hour_parsed=$(parse_cron_field "$hour" 23)
    minute_parsed=$(parse_cron_field "$minute" 59)

    # Frequency description
    case "$hour_parsed" in
        every)
            freq="every hour"
            for h in $(seq 0 23); do
                HOUR_LOAD[$h]=$((${HOUR_LOAD[$h]} + 1))
            done
            ;;
        at-*)
            specific_hour="${hour_parsed#at-}"
            freq="daily at ${specific_hour}:xx"
            HOUR_LOAD[$specific_hour]=$((${HOUR_LOAD[$specific_hour]} + 1))
            ;;
        *)
            freq="complex schedule"
            ;;
    esac

    case "$minute_parsed" in
        every-*)
            step="${minute_parsed#every-}"
            runs_per_hour=$((60 / step))
            freq="${freq} (${runs_per_hour}x/hr)"
            ;;
        at-*)
            specific_min="${minute_parsed#at-}"
            freq="${freq} at :${specific_min}"
            ;;
    esac

    printf "  %-25s %-20s %s\n" "$command" "$minute $hour $dom $month $dow" "$freq"

done <<< "$CRONTAB"

echo ""
echo "  Total jobs: ${ENTRY_NUM}"

# Find peak hours
echo ""
echo "--- Hourly Load Distribution ---"
MAX_LOAD=0
PEAK_HOURS=""

for h in $(seq 0 23); do
    load=${HOUR_LOAD[$h]}
    if [[ $load -gt $MAX_LOAD ]]; then
        MAX_LOAD=$load
    fi
done

for h in $(seq 0 23); do
    load=${HOUR_LOAD[$h]}
    bar=""
    i=0
    while [[ $i -lt $load ]]; do
        bar="${bar}#"
        i=$((i + 1))
    done
    printf "  %02d:00  %-15s (%d jobs)\n" "$h" "$bar" "$load"

    if [[ $load -eq $MAX_LOAD ]] && [[ $load -gt 0 ]]; then
        if [[ -n "$PEAK_HOURS" ]]; then
            PEAK_HOURS="${PEAK_HOURS}, ${h}:00"
        else
            PEAK_HOURS="${h}:00"
        fi
    fi
done

echo ""
echo "--- Conflict Detection ---"

# Check for jobs at the exact same time
CONFLICTS=0
i=0
while [[ $i -lt ${#JOB_SCHEDULES[@]} ]]; do
    j=$((i + 1))
    while [[ $j -lt ${#JOB_SCHEDULES[@]} ]]; do
        if [[ "${JOB_SCHEDULES[$i]}" == "${JOB_SCHEDULES[$j]}" ]]; then
            echo "  CONFLICT: '${JOB_NAMES[$i]}' and '${JOB_NAMES[$j]}' run at same time"
            echo "    Schedule: ${JOB_SCHEDULES[$i]}"
            CONFLICTS=$((CONFLICTS + 1))
        fi
        j=$((j + 1))
    done
    i=$((i + 1))
done

if [[ $CONFLICTS -eq 0 ]]; then
    echo "  No exact schedule conflicts found"
fi

echo ""
echo "--- Summary ---"
echo "  Peak load: ${MAX_LOAD} concurrent jobs at ${PEAK_HOURS}"
echo "  Schedule conflicts: ${CONFLICTS}"
