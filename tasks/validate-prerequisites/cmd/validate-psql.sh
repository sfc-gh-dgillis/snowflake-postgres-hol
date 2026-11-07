#!/usr/bin/env bash

# Validate psql installation. Version 16+ is required for `\watch count=`,
# which the stream-readings load generator uses.
MIN_MAJOR=16

if ! command -v psql >/dev/null 2>&1; then
  echo "✗ psql is not installed (or not on your PATH)."
  if [ -x /opt/homebrew/opt/libpq/bin/psql ] || [ -x /usr/local/opt/libpq/bin/psql ]; then
    echo "  Homebrew libpq is installed but keg-only. Put it on your PATH with:"
    echo "    brew link --force libpq"
  else
    echo "  macOS:          brew install libpq && brew link --force libpq"
    echo "  Debian/Ubuntu:  sudo apt-get install postgresql-client"
  fi
  exit 1
fi

VERSION_LINE="$(psql --version 2>/dev/null | head -1)"
MAJOR="$(echo "$VERSION_LINE" | sed -E 's/[^0-9]*([0-9]+).*/\1/')"

if [ -z "$MAJOR" ] || [ "$MAJOR" -lt "$MIN_MAJOR" ]; then
  echo "✗ $VERSION_LINE found, but psql $MIN_MAJOR+ is required."
  echo "  macOS: brew upgrade libpq"
  exit 1
fi

echo "✓ psql is installed: $VERSION_LINE"
