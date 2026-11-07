#!/bin/bash
# Real-world problem: Collect service health metrics, compute aggregate
# status, and produce a text-based dashboard. Ops runs this every 5 minutes
# via cron and pipes to a Slack webhook or email.
#
# Bash features exercised:
#   associative arrays (declare -A), for-in loop with "${!arr[@]}",
#   arithmetic comparison, case statement, string padding with printf,
#   command substitution nesting, here-document, conditional [[ ]]

declare -A SERVICE_STATUS
declare -A SERVICE_LATENCY
declare -A SERVICE_UPTIME

# Simulated health data (normally collected via curl to each service)
SERVICE_STATUS[api-gateway]="healthy"
SERVICE_STATUS[user-service]="healthy"
SERVICE_STATUS[order-service]="degraded"
SERVICE_STATUS[payment-service]="healthy"
SERVICE_STATUS[notification-service]="down"
SERVICE_STATUS[cache-redis]="healthy"

SERVICE_LATENCY[api-gateway]=12
SERVICE_LATENCY[user-service]=45
SERVICE_LATENCY[order-service]=1200
SERVICE_LATENCY[payment-service]=89
SERVICE_LATENCY[notification-service]=9999
SERVICE_LATENCY[cache-redis]=3

SERVICE_UPTIME[api-gateway]="99.99"
SERVICE_UPTIME[user-service]="99.95"
SERVICE_UPTIME[order-service]="98.50"
SERVICE_UPTIME[payment-service]="99.97"
SERVICE_UPTIME[notification-service]="94.20"
SERVICE_UPTIME[cache-redis]="99.99"

# Compute aggregate stats
TOTAL=0
HEALTHY=0
DEGRADED=0
DOWN=0

for svc in "${!SERVICE_STATUS[@]}"; do
    TOTAL=$((TOTAL + 1))
    case "${SERVICE_STATUS[$svc]}" in
        healthy)  HEALTHY=$((HEALTHY + 1)) ;;
        degraded) DEGRADED=$((DEGRADED + 1)) ;;
        down)     DOWN=$((DOWN + 1)) ;;
    esac
done

# Overall status determination
if [[ $DOWN -gt 0 ]]; then
    OVERALL="CRITICAL"
elif [[ $DEGRADED -gt 0 ]]; then
    OVERALL="WARNING"
else
    OVERALL="OK"
fi

# Dashboard output
TIMESTAMP="2024-03-15T10:30:00Z"
echo "========================================="
echo "  SERVICE HEALTH DASHBOARD"
echo "  ${TIMESTAMP}"
echo "  Overall: ${OVERALL}"
echo "========================================="
echo ""
printf "  %-25s %-10s %8s %8s\n" "SERVICE" "STATUS" "LATENCY" "UPTIME"
printf "  %-25s %-10s %8s %8s\n" "-------" "------" "-------" "------"

for svc in $(echo "${!SERVICE_STATUS[@]}" | tr ' ' '\n' | sort); do
    status="${SERVICE_STATUS[$svc]}"
    latency="${SERVICE_LATENCY[$svc]}"
    uptime="${SERVICE_UPTIME[$svc]}"

    # Status indicator
    case "$status" in
        healthy)  indicator="[OK]" ;;
        degraded) indicator="[!!]" ;;
        down)     indicator="[XX]" ;;
    esac

    # Latency with unit
    if [[ $latency -ge 1000 ]]; then
        latency_str="$(( latency / 1000 )).$(( latency % 1000 ))s"
    else
        latency_str="${latency}ms"
    fi

    printf "  %-25s %-4s %-5s %8s %7s%%\n" "$svc" "$indicator" "$status" "$latency_str" "$uptime"
done

echo ""
echo "-----------------------------------------"
echo "  Summary: ${HEALTHY} healthy, ${DEGRADED} degraded, ${DOWN} down (${TOTAL} total)"

# Alert generation
if [[ "$OVERALL" != "OK" ]]; then
    echo ""
    echo "  ALERTS:"
    for svc in "${!SERVICE_STATUS[@]}"; do
        if [[ "${SERVICE_STATUS[$svc]}" == "down" ]]; then
            echo "    - CRITICAL: ${svc} is DOWN (uptime: ${SERVICE_UPTIME[$svc]}%)"
        elif [[ "${SERVICE_STATUS[$svc]}" == "degraded" ]]; then
            echo "    - WARNING: ${svc} is DEGRADED (latency: ${SERVICE_LATENCY[$svc]}ms)"
        fi
    done
fi
echo "========================================="
