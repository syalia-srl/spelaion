#!/bin/bash
# Real-world problem: Compare environment variable sets across deployment
# targets (staging vs production) to catch config drift -- missing vars,
# value mismatches, orphaned entries. Ops teams run this before deploys.
#
# Bash features exercised:
#   multiple associative arrays, for loops over keys, nested conditionals,
#   string comparison, arithmetic, parameter expansion, printf formatting,
#   [[ -z ]] / [[ -n ]], case statement, functions

# Populate staging environment
declare -A STAGING
STAGING[APP_NAME]="myservice"
STAGING[APP_PORT]="8080"
STAGING[DB_HOST]="staging-db.internal"
STAGING[DB_NAME]="myservice_staging"
STAGING[DB_POOL_SIZE]="5"
STAGING[CACHE_TTL]="60"
STAGING[LOG_LEVEL]="debug"
STAGING[FEATURE_FLAG_NEW_UI]="true"
STAGING[SENTRY_DSN]="https://staging@sentry.io/123"
STAGING[SECRET_KEY]="staging-secret-key-abc"

# Populate production environment
declare -A PRODUCTION
PRODUCTION[APP_NAME]="myservice"
PRODUCTION[APP_PORT]="8080"
PRODUCTION[DB_HOST]="prod-db.internal"
PRODUCTION[DB_NAME]="myservice_prod"
PRODUCTION[DB_POOL_SIZE]="20"
PRODUCTION[CACHE_TTL]="300"
PRODUCTION[LOG_LEVEL]="warn"
PRODUCTION[SENTRY_DSN]="https://prod@sentry.io/456"
PRODUCTION[SECRET_KEY]="prod-secret-key-xyz"
PRODUCTION[WORKER_COUNT]="8"

echo "=== Environment Diff: staging vs production ==="
echo ""

ONLY_STAGING=0
ONLY_PROD=0
DIFFERENT=0
IDENTICAL=0
SENSITIVE_DIFFS=0

# Sensitive key patterns
is_sensitive() {
    local key
    key="$1"
    case "$key" in
        *SECRET*|*KEY*|*PASSWORD*|*TOKEN*|*DSN*)
            return 0 ;;
        *)
            return 1 ;;
    esac
}

printf "%-30s %-25s %-25s %s\n" "VARIABLE" "STAGING" "PRODUCTION" "STATUS"
printf "%-30s %-25s %-25s %s\n" "--------" "-------" "----------" "------"

# All unique keys (union of staging and production keys)
ALL_KEYS="APP_NAME APP_PORT CACHE_TTL DB_HOST DB_NAME DB_POOL_SIZE FEATURE_FLAG_NEW_UI LOG_LEVEL SECRET_KEY SENTRY_DSN WORKER_COUNT"

for key in $ALL_KEYS; do
    stg_val="${STAGING[$key]}"
    prd_val="${PRODUCTION[$key]}"

    # Mask sensitive values for display
    stg_display="$stg_val"
    prd_display="$prd_val"
    is_sensitive "$key"
    sens=$?
    if [[ $sens -eq 0 ]]; then
        if [[ -n "$stg_val" ]]; then
            stg_display="***${stg_val: -4}"
        fi
        if [[ -n "$prd_val" ]]; then
            prd_display="***${prd_val: -4}"
        fi
    fi

    if [[ -z "$stg_val" ]] && [[ -n "$prd_val" ]]; then
        printf "%-30s %-25s %-25s %s\n" "$key" "(missing)" "$prd_display" "PROD ONLY"
        ONLY_PROD=$((ONLY_PROD + 1))
    elif [[ -n "$stg_val" ]] && [[ -z "$prd_val" ]]; then
        printf "%-30s %-25s %-25s %s\n" "$key" "$stg_display" "(missing)" "STAGING ONLY"
        ONLY_STAGING=$((ONLY_STAGING + 1))
    elif [[ "$stg_val" != "$prd_val" ]]; then
        printf "%-30s %-25s %-25s %s\n" "$key" "$stg_display" "$prd_display" "DIFFERS"
        DIFFERENT=$((DIFFERENT + 1))
        if [[ $sens -eq 0 ]]; then
            SENSITIVE_DIFFS=$((SENSITIVE_DIFFS + 1))
        fi
    else
        printf "%-30s %-25s %-25s %s\n" "$key" "$stg_display" "$prd_display" "OK"
        IDENTICAL=$((IDENTICAL + 1))
    fi
done

TOTAL_KEYS=11
echo ""
echo "--- Audit Summary ---"
echo "  Total unique keys: ${TOTAL_KEYS}"
echo "  Identical: ${IDENTICAL}"
echo "  Different values: ${DIFFERENT}"
echo "  Staging only: ${ONLY_STAGING}"
echo "  Production only: ${ONLY_PROD}"
if [[ $SENSITIVE_DIFFS -gt 0 ]]; then
    echo "  Sensitive diffs: ${SENSITIVE_DIFFS} (review required)"
fi
