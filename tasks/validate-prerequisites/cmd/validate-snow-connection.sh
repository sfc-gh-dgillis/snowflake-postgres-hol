#!/usr/bin/env bash

# Validate that the snow CLI connection used by every task can reach Snowflake.
if [ -z "${CLI_CONNECTION_NAME:-}" ]; then
  echo "✗ CLI_CONNECTION_NAME is not set (see .env/mirror.env)."
  exit 1
fi

if snow connection test --connection "$CLI_CONNECTION_NAME" >/dev/null 2>&1; then
  echo "✓ snow CLI connection '$CLI_CONNECTION_NAME' works."
else
  echo "✗ snow CLI connection '$CLI_CONNECTION_NAME' failed. Details:"
  snow connection test --connection "$CLI_CONNECTION_NAME" 2>&1 | tail -20
  echo ""
  echo "  List connections: snow connection list"
  echo "  Add a connection: snow connection add"
  exit 1
fi
