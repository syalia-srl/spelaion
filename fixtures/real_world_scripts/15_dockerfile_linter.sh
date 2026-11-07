#!/bin/bash
# Real-world problem: Lint Dockerfiles for common security and best-practice
# violations -- running as root, using :latest tags, missing health checks,
# too many layers. CI pipelines run this before building images.
#
# Bash features exercised:
#   here-document, while-read loop with line numbers, [[ =~ ]] regex,
#   case statement, arrays, arithmetic, parameter expansion (##, %%),
#   string matching with glob patterns, functions, printf

DOCKERFILE=$(cat <<'DOCKEOF'
FROM ubuntu:latest
MAINTAINER dev@example.com
RUN apt-get update
RUN apt-get install -y python3 curl wget
RUN pip install flask gunicorn
COPY . /app
WORKDIR /app
RUN chmod 777 /app
EXPOSE 8080
ENV SECRET_KEY=hardcoded-secret-123
CMD python3 app.py
DOCKEOF
)

# Use string accumulators instead of arrays (to avoid pipe-subshell issues)
ERRORS=
WARNINGS=
INFOS=
ERROR_COUNT=0
WARNING_COUNT=0
INFO_COUNT=0

LINENUM=0
HAS_HEALTHCHECK=0
HAS_USER=0
RUN_COUNT=0
FROM_COUNT=0
LAYER_COUNT=0

echo "=== Dockerfile Lint Report ==="
echo ""

echo "$DOCKERFILE" | while IFS= read -r line; do
    LINENUM=$((LINENUM + 1))

    # Skip empty lines and comments
    [[ -z "$line" ]] && continue
    [[ "$line" == \#* ]] && continue

    # Extract instruction
    instruction="${line%% *}"
    instruction="${instruction^^}"
    args="${line#* }"

    case "$instruction" in
        FROM)
            FROM_COUNT=$((FROM_COUNT + 1))
            LAYER_COUNT=$((LAYER_COUNT + 1))
            if [[ "$args" == *':latest'* ]] || [[ "$args" != *':'* ]]; then
                ERRORS="${ERRORS}L${LINENUM}: FROM uses :latest or untagged image '${args}';"
                ERROR_COUNT=$((ERROR_COUNT + 1))
            fi
            ;;
        RUN)
            RUN_COUNT=$((RUN_COUNT + 1))
            LAYER_COUNT=$((LAYER_COUNT + 1))
            if [[ "$args" == *'apt-get update'* ]] && [[ "$args" != *'apt-get install'* ]]; then
                WARNINGS="${WARNINGS}L${LINENUM}: apt-get update in separate RUN (combine with install);"
                WARNING_COUNT=$((WARNING_COUNT + 1))
            fi
            if [[ "$args" == *'chmod 777'* ]]; then
                ERRORS="${ERRORS}L${LINENUM}: chmod 777 is a security risk;"
                ERROR_COUNT=$((ERROR_COUNT + 1))
            fi
            if [[ "$args" == *'pip install'* ]] && [[ "$args" != *'--no-cache-dir'* ]]; then
                WARNINGS="${WARNINGS}L${LINENUM}: pip install without --no-cache-dir;"
                WARNING_COUNT=$((WARNING_COUNT + 1))
            fi
            ;;
        MAINTAINER)
            WARNINGS="${WARNINGS}L${LINENUM}: MAINTAINER is deprecated, use LABEL maintainer=;"
            WARNING_COUNT=$((WARNING_COUNT + 1))
            ;;
        COPY|ADD)
            LAYER_COUNT=$((LAYER_COUNT + 1))
            if [[ "$instruction" == "ADD" ]] && [[ "$args" != *'.tar'* ]] && [[ "$args" != *'http'* ]]; then
                WARNINGS="${WARNINGS}L${LINENUM}: Use COPY instead of ADD for simple file copies;"
                WARNING_COUNT=$((WARNING_COUNT + 1))
            fi
            ;;
        ENV)
            if [[ "$args" == *SECRET*=* ]] || [[ "$args" == *PASSWORD*=* ]] || [[ "$args" == *TOKEN*=* ]] || [[ "$args" == *KEY*=* ]]; then
                ERRORS="${ERRORS}L${LINENUM}: Sensitive value in ENV -- use build args or secrets;"
                ERROR_COUNT=$((ERROR_COUNT + 1))
            fi
            ;;
        EXPOSE)
            INFOS="${INFOS}L${LINENUM}: Exposes port ${args};"
            INFO_COUNT=$((INFO_COUNT + 1))
            ;;
        HEALTHCHECK)
            HAS_HEALTHCHECK=1
            ;;
        USER)
            HAS_USER=1
            ;;
        CMD|ENTRYPOINT)
            # Check for shell form vs exec form
            if [[ "$args" != '['* ]]; then
                WARNINGS="${WARNINGS}L${LINENUM}: ${instruction} uses shell form, prefer exec form;"
                WARNING_COUNT=$((WARNING_COUNT + 1))
            fi
            ;;
    esac
done

# Post-analysis checks
if [[ $HAS_HEALTHCHECK -eq 0 ]]; then
    WARNINGS="${WARNINGS}No HEALTHCHECK instruction found;"
    WARNING_COUNT=$((WARNING_COUNT + 1))
fi
if [[ $HAS_USER -eq 0 ]]; then
    ERRORS="${ERRORS}No USER instruction -- container runs as root;"
    ERROR_COUNT=$((ERROR_COUNT + 1))
fi
if [[ $RUN_COUNT -gt 3 ]]; then
    WARNINGS="${WARNINGS}${RUN_COUNT} separate RUN instructions -- consider combining to reduce layers;"
    WARNING_COUNT=$((WARNING_COUNT + 1))
fi

# Output results
if [[ $ERROR_COUNT -gt 0 ]]; then
    echo "ERRORS (${ERROR_COUNT}):"
    echo "$ERRORS" | tr ';' '\n' | while IFS= read -r e; do
        [[ -z "$e" ]] && continue
        echo "  [E] ${e}"
    done
    echo ""
fi

if [[ $WARNING_COUNT -gt 0 ]]; then
    echo "WARNINGS (${WARNING_COUNT}):"
    echo "$WARNINGS" | tr ';' '\n' | while IFS= read -r w; do
        [[ -z "$w" ]] && continue
        echo "  [W] ${w}"
    done
    echo ""
fi

if [[ $INFO_COUNT -gt 0 ]]; then
    echo "INFO (${INFO_COUNT}):"
    echo "$INFOS" | tr ';' '\n' | while IFS= read -r inf; do
        [[ -z "$inf" ]] && continue
        echo "  [I] ${inf}"
    done
    echo ""
fi

echo "--- Summary ---"
echo "  Lines: ${LINENUM}, Layers: ${LAYER_COUNT}, FROM stages: ${FROM_COUNT}"
echo "  Errors: ${ERROR_COUNT}, Warnings: ${WARNING_COUNT}, Info: ${INFO_COUNT}"

if [[ $ERROR_COUNT -gt 0 ]]; then
    echo "  RESULT: FAIL"
    exit 1
else
    echo "  RESULT: PASS (with ${WARNING_COUNT} warnings)"
fi
