#!/usr/bin/env bash

# Validate Snowflake CLI installation. The lab's Snowflake objects are DCM
# projects, and teardown uses `snow dcm purge`, which needs 3.17 or later.
MIN_VERSION="3.17"

if ! command -v snow >/dev/null 2>&1; then
  echo "✗ Snowflake CLI (snow) is not installed."
  echo "To install Snowflake CLI, follow the instructions at:"
  echo "https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation"
  exit 1
fi

VERSION="$(snow --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)"
if [ -z "$VERSION" ]; then
  echo "✗ Could not read the Snowflake CLI version from 'snow --version'."
  exit 1
fi

if [ "$(printf '%s\n%s\n' "$MIN_VERSION" "$VERSION" | sort -V | head -1)" != "$MIN_VERSION" ]; then
  echo "✗ Snowflake CLI $VERSION is too old: the lab's DCM projects need $MIN_VERSION or later (snow dcm purge)."
  echo "  A direct install upgrades with: snow upgrade"
  echo "  Otherwise reinstall from: https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation"
  exit 1
fi

echo "✓ Snowflake CLI (snow) $VERSION is installed (DCM needs $MIN_VERSION or later)."
