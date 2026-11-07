#!/usr/bin/env bash

# Validate Python 3.9+ (helper scripts use only the standard library; no venv needed)
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ python3 is not installed. Install Python 3.9+ from https://www.python.org/"
  exit 1
fi

if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "✓ Python is installed: $(python3 --version 2>&1)"
else
  echo "✗ $(python3 --version 2>&1) found, but Python 3.9+ is required."
  exit 1
fi
