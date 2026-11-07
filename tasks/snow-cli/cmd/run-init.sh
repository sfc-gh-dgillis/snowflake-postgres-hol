#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 SQL_DIR"
    echo "Example: $0 sql/init"
    exit 1
fi

SQL_DIR="$1"
SQL_FILE="$SQL_DIR/init.sql"

if [ ! -f "$SQL_FILE" ]; then
    echo "Error: SQL file not found at $SQL_FILE"
    exit 1
fi

# Check if required environment variables are set (loaded from .env/mirror.env).
REQUIRED_VARS=(
    "CLI_CONNECTION_NAME"
    "MIRROR_ADMIN_ROLE_NAME"
    "DEMO_WAREHOUSE_NAME"
    "DEMO_DATABASE_NAME"
    "DEMO_DATABASE_DDL_COMMENT"
    "DEMO_SCHEMA_NAME"
    "DEMO_INTERNAL_NAMED_STAGE"
    "DEMO_INTERNAL_NAMED_STAGE_COMMENT"
    "DEMO_ANALYST_ROLE_NAME"
)

MISSING_VARS=()
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR:-}" ]; then
        MISSING_VARS+=("$VAR")
    fi
done

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "Error: Missing required environment variables:"
    for VAR in "${MISSING_VARS[@]}"; do
        echo "  - $VAR"
    done
    exit 1
fi

# Resolve the authenticated Snowflake user dynamically
DEMO_SETUP_USER=$(snow sql --connection "$CLI_CONNECTION_NAME" -q "SELECT CURRENT_USER()" --format JSON 2>/dev/null \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['CURRENT_USER()'])")

if [ -z "$DEMO_SETUP_USER" ]; then
    echo "Error: Could not resolve current Snowflake user"
    exit 1
fi
export DEMO_SETUP_USER

echo "Running Snowflake initialization..."
echo "  Connection:    $CLI_CONNECTION_NAME"
echo "  Admin Role:    $MIRROR_ADMIN_ROLE_NAME"
echo "  Warehouse:     $DEMO_WAREHOUSE_NAME"
echo "  Lab Database:  $DEMO_DATABASE_NAME.$DEMO_SCHEMA_NAME"
echo "  Stage:         $DEMO_INTERNAL_NAMED_STAGE"
echo "  Analyst Role:  $DEMO_ANALYST_ROLE_NAME"
echo "  Setup User:    $DEMO_SETUP_USER (auto-detected)"
echo ""

echo "==> Running: $SQL_FILE"
snow sql --connection "$CLI_CONNECTION_NAME" -f "$SQL_FILE"

echo ""
echo "Initialization completed successfully"
