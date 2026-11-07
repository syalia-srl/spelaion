#!/bin/bash
# Real-world problem: Analyze web server access logs to find top endpoints,
# error rates, and slow requests. Ops teams run this hourly to spot issues.
#
# Bash features exercised:
#   here-document, command substitution, pipeline (grep|awk|sort|uniq|head),
#   process substitution, while-read loop, arithmetic expansion, variable
#   expansion with defaults, printf formatting, arrays

# Simulated access log (normally: tail -10000 /var/log/nginx/access.log)
LOG_DATA=$(cat <<'LOGEOF'
2024-03-15T10:00:01 GET /api/users 200 0.023
2024-03-15T10:00:02 POST /api/users 201 0.145
2024-03-15T10:00:02 GET /api/users/42 200 0.018
2024-03-15T10:00:03 GET /api/orders 200 0.089
2024-03-15T10:00:03 GET /api/users 200 0.021
2024-03-15T10:00:04 POST /api/orders 500 2.301
2024-03-15T10:00:04 GET /api/health 200 0.002
2024-03-15T10:00:05 GET /api/users 200 0.025
2024-03-15T10:00:05 DELETE /api/users/7 404 0.010
2024-03-15T10:00:06 GET /api/orders 200 0.095
2024-03-15T10:00:06 POST /api/orders 500 3.044
2024-03-15T10:00:07 GET /api/health 200 0.001
2024-03-15T10:00:07 GET /api/users 200 0.019
2024-03-15T10:00:08 PUT /api/users/42 200 0.133
2024-03-15T10:00:08 GET /api/orders 200 0.091
LOGEOF
)

THRESHOLD=${SLOW_THRESHOLD:-1.000}
REPORT_TITLE="${REPORT_NAME:-Access Log Summary}"

echo "=== ${REPORT_TITLE} ==="
echo "Analyzed: $(echo "$LOG_DATA" | wc -l | tr -d ' ') requests"
echo ""

# Top endpoints by request count
echo "--- Top Endpoints ---"
echo "$LOG_DATA" | awk '{print $2, $3}' | sort | uniq -c | sort -rn | head -5 | \
while read count method path; do
    printf "  %-6s %-7s %s\n" "[$count]" "$method" "$path"
done

echo ""

# Error rate computation
TOTAL=$(echo "$LOG_DATA" | wc -l | tr -d ' ')
ERRORS=$(echo "$LOG_DATA" | awk '$4 >= 400' | wc -l | tr -d ' ')
ERROR_PCT=$(( (ERRORS * 100) / TOTAL ))
echo "--- Error Rate ---"
echo "  ${ERRORS}/${TOTAL} requests failed (${ERROR_PCT}%)"

# Breakdown by status code
echo ""
echo "--- Status Codes ---"
echo "$LOG_DATA" | awk '{print $4}' | sort | uniq -c | sort -rn | \
while read count code; do
    bar=""
    i=0
    while [ $i -lt "$count" ]; do
        bar="${bar}#"
        i=$((i + 1))
    done
    printf "  %s %s %s\n" "$code" "$bar" "($count)"
done

echo ""

# Slow requests (above threshold)
echo "--- Slow Requests (>${THRESHOLD}s) ---"
SLOW_COUNT=0
echo "$LOG_DATA" | awk -v thresh="$THRESHOLD" '$5+0 > thresh+0 {print $0}' | \
while IFS= read -r line; do
    echo "  SLOW: $line"
done
SLOW_FOUND=$(echo "$LOG_DATA" | awk -v thresh="$THRESHOLD" '$5+0 > thresh+0' | wc -l | tr -d ' ')
if [ "$SLOW_FOUND" -eq 0 ]; then
    echo "  (none)"
fi
echo "  Total slow: ${SLOW_FOUND}"
