#!/bin/bash
# Real-world problem: Correlate errors across multiple service logs by
# request ID to trace failures through a microservice chain. SREs use
# this during incident response when the tracing system is down.
#
# Bash features exercised:
#   associative arrays with compound keys, multiple here-documents,
#   while-read with IFS, nested loops, [[ =~ ]] regex, printf,
#   arrays as values, string manipulation, arithmetic

# Simulated logs from three services
API_LOG=$(cat <<'LOG1'
2024-03-15T10:00:01 req-abc-123 INFO  Received POST /api/orders
2024-03-15T10:00:01 req-abc-123 INFO  Forwarding to order-service
2024-03-15T10:00:02 req-abc-123 ERROR Timeout waiting for order-service
2024-03-15T10:00:03 req-def-456 INFO  Received GET /api/users/42
2024-03-15T10:00:03 req-def-456 INFO  Response 200 in 45ms
2024-03-15T10:00:04 req-ghi-789 INFO  Received POST /api/payments
2024-03-15T10:00:04 req-ghi-789 ERROR 503 from payment-service
LOG1
)

ORDER_LOG=$(cat <<'LOG2'
2024-03-15T10:00:01 req-abc-123 INFO  Processing order creation
2024-03-15T10:00:02 req-abc-123 ERROR Database connection pool exhausted
2024-03-15T10:00:02 req-abc-123 ERROR Failed to create order: pool_timeout
LOG2
)

PAYMENT_LOG=$(cat <<'LOG3'
2024-03-15T10:00:04 req-ghi-789 INFO  Processing payment
2024-03-15T10:00:04 req-ghi-789 WARN  Stripe API rate limited
2024-03-15T10:00:04 req-ghi-789 ERROR Payment failed: rate_limit_exceeded
LOG3
)

# Collect all errors by request ID
declare -A ERROR_MSGS      # reqid -> concatenated error messages
declare -A ERROR_SERVICES  # reqid -> services that had errors
declare -A REQ_FIRST_SEEN  # reqid -> first timestamp

echo "=== Error Correlation Report ==="
echo ""

process_log() {
    local service="$1"
    local log_data="$2"

    while IFS=' ' read -r timestamp reqid level rest; do
        [[ -z "$timestamp" ]] && continue

        # Track first seen timestamp per request
        if [[ -z "${REQ_FIRST_SEEN[$reqid]}" ]]; then
            REQ_FIRST_SEEN[$reqid]="$timestamp"
        fi

        # Collect errors
        if [[ "$level" == "ERROR" ]]; then
            if [[ -n "${ERROR_MSGS[$reqid]}" ]]; then
                ERROR_MSGS[$reqid]="${ERROR_MSGS[$reqid]}|${service}: ${rest}"
            else
                ERROR_MSGS[$reqid]="${service}: ${rest}"
            fi

            # Track which services had errors for this request
            if [[ "${ERROR_SERVICES[$reqid]}" != *"$service"* ]]; then
                if [[ -n "${ERROR_SERVICES[$reqid]}" ]]; then
                    ERROR_SERVICES[$reqid]="${ERROR_SERVICES[$reqid]}, ${service}"
                else
                    ERROR_SERVICES[$reqid]="$service"
                fi
            fi
        fi
    done <<< "$log_data"
}

process_log "api-gateway" "$API_LOG"
process_log "order-service" "$ORDER_LOG"
process_log "payment-service" "$PAYMENT_LOG"

# Report correlated errors
ERROR_COUNT=0
MULTI_SERVICE=0

for reqid in $(echo "${!ERROR_MSGS[@]}" | tr ' ' '\n' | sort); do
    ERROR_COUNT=$((ERROR_COUNT + 1))
    services="${ERROR_SERVICES[$reqid]}"
    first_ts="${REQ_FIRST_SEEN[$reqid]}"

    # Count services involved
    svc_count=1
    remaining="$services"
    while [[ "$remaining" == *", "* ]]; do
        svc_count=$((svc_count + 1))
        remaining="${remaining#*, }"
    done

    if [[ $svc_count -gt 1 ]]; then
        MULTI_SERVICE=$((MULTI_SERVICE + 1))
        echo "CORRELATED ERROR [${reqid}] (${svc_count} services)"
    else
        echo "ERROR [${reqid}] (1 service)"
    fi
    echo "  First seen: ${first_ts}"
    echo "  Services: ${services}"

    # Print individual error messages
    IFS='|' read -ra msgs <<< "${ERROR_MSGS[$reqid]}"
    for msg in "${msgs[@]}"; do
        echo "    -> ${msg}"
    done
    echo ""
done

echo "--- Summary ---"
echo "  Failed requests: ${ERROR_COUNT}"
echo "  Multi-service failures: ${MULTI_SERVICE}"
echo "  Single-service failures: $((ERROR_COUNT - MULTI_SERVICE))"
