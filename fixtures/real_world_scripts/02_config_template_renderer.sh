#!/bin/bash
# Real-world problem: Generate deployment config files (YAML/JSON) from
# environment variables and defaults. Used by CI/CD pipelines to produce
# environment-specific configs without templating engines like Jinja.
#
# Bash features exercised:
#   parameter expansion (default, substitution, length), here-document with
#   variable interpolation, here-document with quoting suppression, case
#   statement, conditional [[ ]], string manipulation ${var,,}

APP_NAME="${APP_NAME:-myservice}"
APP_ENV="${APP_ENV:-staging}"
APP_PORT="${APP_PORT:-8080}"
APP_REPLICAS="${APP_REPLICAS:-2}"
DB_HOST="${DB_HOST:-db.internal}"
DB_NAME="${DB_NAME:-${APP_NAME}_${APP_ENV}}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# Normalize env to lowercase
APP_ENV="${APP_ENV,,}"

# Determine resource limits based on environment
case "$APP_ENV" in
    production)
        CPU_LIMIT="2000m"
        MEM_LIMIT="4Gi"
        ;;
    staging)
        CPU_LIMIT="500m"
        MEM_LIMIT="1Gi"
        ;;
    *)
        CPU_LIMIT="250m"
        MEM_LIMIT="512Mi"
        ;;
esac

# Compute labels
DEPLOY_HASH=$(echo "${APP_NAME}-${APP_ENV}-${APP_REPLICAS}" | cksum | awk '{print $1}')
SHORT_HASH="${DEPLOY_HASH:0:8}"

# Validate required fields
ERRORS=0
for var in APP_NAME APP_ENV APP_PORT; do
    eval val=\$$var
    if [[ -z "$val" ]]; then
        echo "ERROR: $var is required but empty" >&2
        ERRORS=$((ERRORS + 1))
    fi
done

if [[ $ERRORS -gt 0 ]]; then
    echo "Aborting: $ERRORS validation errors" >&2
    exit 1
fi

echo "# Generated config for ${APP_NAME} (${APP_ENV})"
echo "# Deploy hash: ${SHORT_HASH}"

cat <<EOF
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ${APP_NAME}
  labels:
    app: ${APP_NAME}
    env: ${APP_ENV}
    deploy-hash: "${SHORT_HASH}"
spec:
  replicas: ${APP_REPLICAS}
  template:
    spec:
      containers:
        - name: ${APP_NAME}
          port: ${APP_PORT}
          resources:
            limits:
              cpu: ${CPU_LIMIT}
              memory: ${MEM_LIMIT}
          env:
            - name: DATABASE_URL
              value: "postgresql://${DB_HOST}:5432/${DB_NAME}"
            - name: LOG_LEVEL
              value: "${LOG_LEVEL}"
            - name: APP_ENV
              value: "${APP_ENV}"
EOF

# Summary line for CI logs
FIELD_COUNT=0
for f in APP_NAME APP_ENV APP_PORT APP_REPLICAS DB_HOST DB_NAME LOG_LEVEL; do
    FIELD_COUNT=$((FIELD_COUNT + 1))
done
echo "# Rendered ${FIELD_COUNT} variables, name length: ${#APP_NAME}"
