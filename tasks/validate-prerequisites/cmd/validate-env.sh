#!/usr/bin/env bash
set -uo pipefail

# Validates the lab env file: it must exist, every required variable must be
# set, and values that get interpolated into SQL must be well-formed.
# Usage: ./validate-env.sh ENV_FILE

ENV_FILE="${1:-.env/mirror.env}"
ERRORS=()
WARNINGS=()

if [ ! -f "$ENV_FILE" ]; then
  echo "✗ Env file not found: $ENV_FILE"
  echo "  Create it from the template and fill in your values:"
  echo "    cp .env/mirror.env.template .env/mirror.env"
  exit 1
fi

MODE="${POSTGRES_INSTANCE_MODE:-create}"

REQUIRED_VARS=(
  "CLI_CONNECTION_NAME"
  "MIRROR_ADMIN_ROLE_NAME"
  "DEMO_WAREHOUSE_NAME"
  "DEMO_DATABASE_NAME"
  "DEMO_DATABASE_DDL_COMMENT"
  "DEMO_SCHEMA_NAME"
  "DEMO_INTERNAL_NAMED_STAGE"
  "DEMO_INTERNAL_NAMED_STAGE_COMMENT"
  "DEMO_NOTEBOOK_NAME"
  "DEMO_ANALYST_ROLE_NAME"
  "PG_INSTANCE_NAME"
  "PG_DATABASE_NAME"
  "PG_SCHEMA_NAME"
  "PG_SERVICE_NAME"
  "MIRROR_NAME"
  "MIRROR_TARGET_DATABASE_NAME"
  "MIRROR_REFRESH_INTERVAL"
  "MIRROR_FAST_REFRESH_INTERVAL"
  "DEMO_DYNAMIC_TABLE_NAME"
  "DEMO_SEMANTIC_VIEW_NAME"
  "DEMO_AGENT_NAME"
)

case "$MODE" in
  create)
    REQUIRED_VARS+=("PG_COMPUTE_FAMILY" "PG_STORAGE_SIZE_GB" "PG_NETWORK_RULE_NAME" "PG_NETWORK_POLICY_NAME")
    ;;
  existing)
    ;;
  *)
    ERRORS+=("POSTGRES_INSTANCE_MODE must be 'create' or 'existing' (got '$MODE')")
    ;;
esac

for VAR in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!VAR:-}" ]; then
    ERRORS+=("$VAR is not set")
  fi
done

# check_format VAR REGEX DESCRIPTION - only checks variables that are set
check_format() {
  local var="$1" regex="$2" description="$3"
  local value="${!var:-}"
  if [ -n "$value" ] && ! [[ "$value" =~ $regex ]]; then
    ERRORS+=("$var='$value' is invalid: $description")
  fi
}

SF_IDENTIFIER='^[A-Za-z_][A-Za-z0-9_$]*$'
for VAR in MIRROR_ADMIN_ROLE_NAME DEMO_WAREHOUSE_NAME DEMO_DATABASE_NAME DEMO_SCHEMA_NAME \
           DEMO_INTERNAL_NAMED_STAGE DEMO_NOTEBOOK_NAME DEMO_ANALYST_ROLE_NAME \
           MIRROR_TARGET_DATABASE_NAME DEMO_DYNAMIC_TABLE_NAME DEMO_SEMANTIC_VIEW_NAME \
           DEMO_AGENT_NAME PG_NETWORK_RULE_NAME PG_NETWORK_POLICY_NAME; do
  check_format "$VAR" "$SF_IDENTIFIER" "use an unquoted Snowflake identifier (letters, digits, _ and \$)"
done

if [ "$MODE" = "create" ]; then
  check_format PG_INSTANCE_NAME '^[A-Z][A-Z0-9_]*$' "create mode needs UPPERCASE letters, digits and underscores"
else
  check_format PG_INSTANCE_NAME '^[A-Za-z0-9_$-]+$' "use the instance name exactly as SHOW POSTGRES INSTANCES shows it"
fi

check_format MIRROR_NAME '^[a-z_][a-z0-9_]*$' "use lowercase letters, digits and underscores (mirror names fold to lowercase)"
if [ ${#MIRROR_NAME} -gt 50 ]; then
  ERRORS+=("MIRROR_NAME must be 50 characters or fewer")
fi

check_format PG_DATABASE_NAME '^[a-z_][a-z0-9_]*$' "use a lowercase, unquoted Postgres identifier"
check_format PG_SCHEMA_NAME '^[a-z_][a-z0-9_]*$' "use a lowercase, unquoted Postgres identifier"
check_format PG_USER '^[a-z_][a-z0-9_]*$' "use a lowercase Postgres role name"
check_format PG_SERVICE_NAME '^[A-Za-z0-9_.-]+$' "use letters, digits, '.', '_' and '-'"
check_format CLI_CONNECTION_NAME '^[A-Za-z0-9_.-]+$' "use the connection name from 'snow connection list'"

# The only refresh_interval values CREATE_MIRROR / ALTER_MIRROR accept (mirror procedures reference)
INTERVAL_REGEX='^(30 seconds|1 minute|10 minutes|1 hour|1 day)$'
check_format MIRROR_REFRESH_INTERVAL "$INTERVAL_REGEX" "must be one of '30 seconds', '1 minute', '10 minutes', '1 hour', '1 day'"
check_format MIRROR_FAST_REFRESH_INTERVAL "$INTERVAL_REGEX" "must be one of '30 seconds', '1 minute', '10 minutes', '1 hour', '1 day'"

check_format MIRROR_TARGET_TABLE_TYPE '^(SNOWFLAKE|ICEBERG)$' "must be SNOWFLAKE or ICEBERG"

for VAR in LAB_SYNC_TIMEOUT_SECONDS LAB_POLL_INTERVAL_SECONDS STREAM_INTERVAL_SECONDS STREAM_BATCHES STREAM_BATCH_SIZE; do
  check_format "$VAR" '^[1-9][0-9]*$' "must be a positive integer"
done

if [ "$MODE" = "create" ]; then
  if [[ "${PG_COMPUTE_FAMILY:-}" == BURST_* ]]; then
    ERRORS+=("PG_COMPUTE_FAMILY=$PG_COMPUTE_FAMILY: the BURSTABLE tier is not supported for mirroring (use STANDARD_* or HIGHMEM_*)")
  else
    check_format PG_COMPUTE_FAMILY '^(STANDARD|HIGHMEM)_[0-9A-Z]+$' "use a STANDARD_* or HIGHMEM_* compute family"
  fi
  check_format PG_STORAGE_SIZE_GB '^[0-9]+$' "must be a whole number of GB"
  if [[ "${PG_STORAGE_SIZE_GB:-}" =~ ^[0-9]+$ ]] && { [ "$PG_STORAGE_SIZE_GB" -lt 10 ] || [ "$PG_STORAGE_SIZE_GB" -gt 65535 ]; }; then
    ERRORS+=("PG_STORAGE_SIZE_GB must be between 10 and 65535")
  fi

  CIDR="${PG_ALLOWED_CIDR:-AUTO}"
  if [ "$CIDR" != "AUTO" ]; then
    if ! [[ "$CIDR" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/([0-9]|[12][0-9]|3[0-2])$ ]]; then
      ERRORS+=("PG_ALLOWED_CIDR='$CIDR' must be AUTO or an IPv4 CIDR such as 203.0.113.7/32")
    else
      PREFIX="${CIDR##*/}"
      if [ "$PREFIX" -lt 8 ]; then
        ERRORS+=("PG_ALLOWED_CIDR='$CIDR' opens Postgres to a huge range of the internet; use your own IP/32")
      elif [ "$PREFIX" -lt 24 ]; then
        WARNINGS+=("PG_ALLOWED_CIDR='$CIDR' allows a large range; check with your security team")
      fi
    fi
  fi
fi

for WARNING in "${WARNINGS[@]:-}"; do
  [ -n "$WARNING" ] && echo "⚠️  $WARNING"
done

if [ ${#ERRORS[@]} -gt 0 ]; then
  echo "✗ $ENV_FILE has problems:"
  for ERROR in "${ERRORS[@]}"; do
    echo "  - $ERROR"
  done
  exit 1
fi

echo "✓ $ENV_FILE is valid (POSTGRES_INSTANCE_MODE=$MODE)"
