#!/bin/bash
# Real-world problem: Compute percentile-based response time SLA metrics
# from raw timing data. Ops teams use this to verify p50/p95/p99 latency
# targets are being met and to generate SLA compliance reports.
#
# Bash features exercised:
#   arrays (indexed), arithmetic with complex expressions, while-read loop,
#   sort via pipeline, printf formatting, parameter expansion, for loops,
#   command substitution, functions with return-via-echo, [[ ]] comparisons

# Simulated response times in milliseconds (normally from log parsing)
RAW_TIMES=$(cat <<'TIMEOF'
12
145
23
67
890
34
1200
19
45
78
234
56
15
2100
42
67
31
89
156
44
38
71
3500
28
52
TIMEOF
)

# Sort the times numerically
SORTED_TIMES=$(echo "$SORTED_TIMES" | sort -n)
SORTED_TIMES=$(echo "$RAW_TIMES" | sort -n)

# Load into array
declare -a TIMES
while IFS= read -r t; do
    [[ -z "$t" ]] && continue
    TIMES+=("$t")
done <<< "$SORTED_TIMES"

COUNT=${#TIMES[@]}

# Compute statistics
compute_sum() {
    local sum=0
    for t in "${TIMES[@]}"; do
        sum=$((sum + t))
    done
    echo "$sum"
}

compute_percentile() {
    local pct=$1
    local idx=$(( (COUNT * pct) / 100 ))
    if [[ $idx -ge $COUNT ]]; then
        idx=$((COUNT - 1))
    fi
    echo "${TIMES[$idx]}"
}

SUM=$(compute_sum)
AVG=$((SUM / COUNT))
MIN="${TIMES[0]}"
MAX="${TIMES[$((COUNT - 1))]}"
P50=$(compute_percentile 50)
P90=$(compute_percentile 90)
P95=$(compute_percentile 95)
P99=$(compute_percentile 99)

# SLA thresholds
SLA_P50=${SLA_P50_TARGET:-100}
SLA_P95=${SLA_P95_TARGET:-500}
SLA_P99=${SLA_P99_TARGET:-2000}

echo "=== API Response Time SLA Report ==="
echo "  Sample size: ${COUNT} requests"
echo ""

echo "--- Latency Distribution ---"
printf "  %-12s %8s\n" "Metric" "Value"
printf "  %-12s %8s\n" "------" "-----"
printf "  %-12s %7dms\n" "Min" "$MIN"
printf "  %-12s %7dms\n" "Max" "$MAX"
printf "  %-12s %7dms\n" "Average" "$AVG"
printf "  %-12s %7dms\n" "p50" "$P50"
printf "  %-12s %7dms\n" "p90" "$P90"
printf "  %-12s %7dms\n" "p95" "$P95"
printf "  %-12s %7dms\n" "p99" "$P99"
echo ""

# Histogram buckets
declare -A BUCKETS
BUCKETS[0_50]=0
BUCKETS[50_100]=0
BUCKETS[100_500]=0
BUCKETS[500_1000]=0
BUCKETS[1000_plus]=0

for t in "${TIMES[@]}"; do
    if [[ $t -lt 50 ]]; then
        BUCKETS[0_50]=$((${BUCKETS[0_50]} + 1))
    elif [[ $t -lt 100 ]]; then
        BUCKETS[50_100]=$((${BUCKETS[50_100]} + 1))
    elif [[ $t -lt 500 ]]; then
        BUCKETS[100_500]=$((${BUCKETS[100_500]} + 1))
    elif [[ $t -lt 1000 ]]; then
        BUCKETS[500_1000]=$((${BUCKETS[500_1000]} + 1))
    else
        BUCKETS[1000_plus]=$((${BUCKETS[1000_plus]} + 1))
    fi
done

echo "--- Histogram ---"
for bucket in 0_50 50_100 100_500 500_1000 1000_plus; do
    label="${bucket//_/-}"
    label="${label/plus/+}"
    count="${BUCKETS[$bucket]}"
    bar=""
    i=0
    while [[ $i -lt $count ]]; do
        bar="${bar}#"
        i=$((i + 1))
    done
    printf "  %10sms: %-20s (%d)\n" "$label" "$bar" "$count"
done
echo ""

# SLA compliance
echo "--- SLA Compliance ---"
VIOLATIONS=0

check_sla() {
    local metric="$1"
    local actual="$2"
    local target="$3"

    if [[ $actual -le $target ]]; then
        printf "  %-6s %7dms <= %7dms  [PASS]\n" "$metric" "$actual" "$target"
    else
        printf "  %-6s %7dms >  %7dms  [FAIL]\n" "$metric" "$actual" "$target"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
}

check_sla "p50" "$P50" "$SLA_P50"
check_sla "p95" "$P95" "$SLA_P95"
check_sla "p99" "$P99" "$SLA_P99"

echo ""
if [[ $VIOLATIONS -eq 0 ]]; then
    echo "SLA Status: COMPLIANT"
else
    echo "SLA Status: VIOLATED (${VIOLATIONS} breach(es))"
fi
