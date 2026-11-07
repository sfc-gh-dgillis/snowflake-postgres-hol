#!/usr/bin/env python3
"""
pgclisp - psql sort and process (sql files) utility
SQL File Executor for psql (the Postgres twin of snowclisp)

Runs one SQL file, or every NNN-*.sql file in a directory in numeric order,
against a libpq service from ~/.pg_service.conf (the password comes from
~/.pgpass). Output streams straight to your terminal, so psql meta-commands
such as \\watch work.

psql variables are filled from the environment (.env/mirror.env, loaded by
Task), so SQL files can use :"pg_schema", :'mirror_name', and so on:

  psql variable       environment variable        default
  pg_schema           PG_SCHEMA_NAME              (required)
  pg_database         PG_DATABASE_NAME            (required)
  mirror_name         MIRROR_NAME                 (required)
  stream_interval     STREAM_INTERVAL_SECONDS     5
  stream_batches      STREAM_BATCHES              60
  stream_batch_size   STREAM_BATCH_SIZE           20

Use --var NAME=VALUE to add or override variables.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

PSQL_VARIABLES = {
    "pg_schema": ("PG_SCHEMA_NAME", None),
    "pg_database": ("PG_DATABASE_NAME", None),
    "mirror_name": ("MIRROR_NAME", None),
    "stream_interval": ("STREAM_INTERVAL_SECONDS", "5"),
    "stream_batches": ("STREAM_BATCHES", "60"),
    "stream_batch_size": ("STREAM_BATCH_SIZE", "20"),
}

# psql exit status 2 = connection failure (non-interactive)
PSQL_CONNECTION_FAILED = 2


def extract_numeric_prefix(filename: str) -> int:
    """Extract numeric prefix from filename (e.g., '001-create.sql' -> 1), or -1 if none."""
    match = re.match(r'^(\d+)-', filename)
    if match:
        return int(match.group(1))
    return -1


def get_sorted_sql_files(directory: str, pattern: str = r'^\d+-.*\.sql$') -> Tuple[List[Path], List[Path]]:
    """Return (NNN-*.sql files sorted by prefix, other .sql files)."""
    dir_path = Path(directory)

    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    if not dir_path.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {directory}")

    matching_files: List[Tuple[int, Path]] = []
    non_matching_files: List[Path] = []
    pattern_re = re.compile(pattern)

    for file_path in dir_path.iterdir():
        if file_path.is_file() and file_path.suffix.lower() == '.sql':
            if pattern_re.match(file_path.name):
                matching_files.append((extract_numeric_prefix(file_path.name), file_path))
            else:
                non_matching_files.append(file_path)

    matching_files.sort(key=lambda x: x[0])
    return [path for _, path in matching_files], non_matching_files


def resolve_variables(overrides: List[str]) -> Dict[str, str]:
    """Build psql variables from the environment, then apply --var overrides."""
    variables: Dict[str, str] = {}
    missing = []
    for psql_name, (env_name, default) in PSQL_VARIABLES.items():
        value = os.environ.get(env_name) or default
        if value is None:
            missing.append(env_name)
        else:
            variables[psql_name] = value

    for override in overrides:
        if "=" not in override:
            raise ValueError(f"--var must look like NAME=VALUE (got '{override}')")
        name, value = override.split("=", 1)
        variables[name.strip()] = value

    if missing:
        raise ValueError("Missing environment variables: " + ", ".join(missing))
    return variables


def print_connection_help(service_name: str) -> None:
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"Could not connect to Postgres using service '{service_name}'.", file=sys.stderr)
    print("  • Timeout: your IP is not allowed by the instance network policy.", file=sys.stderr)
    print("    Create mode: run `task pg-allow-my-ip` (or set PG_ALLOWED_CIDR).", file=sys.stderr)
    print("  • Connection refused: the instance is suspended or still starting.", file=sys.stderr)
    print("    Check it with `task pg-instance-info`.", file=sys.stderr)
    print("  • Password authentication failed: run `task pg-reset-access`.", file=sys.stderr)
    print("  • Certificate errors: re-run `task demo-up` to refresh the CA cert.", file=sys.stderr)
    print("=" * 60, file=sys.stderr)


def execute_sql_files_with_psql(
    service_name: str,
    sql_files: List[Path],
    variables: Dict[str, str],
    echo: bool = True,
) -> bool:
    """Execute SQL files in order in a single psql session (stops on the first error)."""
    if not sql_files:
        print("No SQL files to execute.")
        return True

    cmd = [
        'psql', f'service={service_name} connect_timeout=10',
        '--no-psqlrc',
        '--set', 'ON_ERROR_STOP=1',
        '--pset', 'pager=off',
    ]
    if echo:
        cmd.append('--echo-queries')
    for name, value in variables.items():
        cmd.extend(['--set', f'{name}={value}'])
    for sql_file in sql_files:
        cmd.extend(['-f', str(sql_file)])

    print(f"\n{'='*60}")
    print(f"Executing {len(sql_files)} SQL file(s) against Postgres service '{service_name}':")
    for i, sql_file in enumerate(sql_files, 1):
        print(f"  {i}. {sql_file}")
    print(f"{'='*60}\n", flush=True)

    try:
        result = subprocess.run(cmd)
    except FileNotFoundError:
        print("\nERROR: 'psql' command not found. Run `task validate-prerequisites` for install help.",
              file=sys.stderr)
        return False

    if result.returncode == 0:
        print(f"\n{'='*60}")
        print(f"✓ Successfully executed all {len(sql_files)} SQL file(s)")
        print(f"{'='*60}")
        return True

    if result.returncode == PSQL_CONNECTION_FAILED:
        print_connection_help(service_name)
    else:
        print(f"\n✗ psql exited with status {result.returncode}", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Run a SQL file, or every NNN-*.sql file in a directory in numeric order, with psql"
    )
    parser.add_argument("path", help="SQL file, or directory containing NNN-*.sql files")
    parser.add_argument("service_name", help="libpq service name from ~/.pg_service.conf")
    parser.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                        help="extra psql variable (repeatable)")
    parser.add_argument("--no-echo", action="store_true", help="do not echo SQL statements")
    args = parser.parse_args()

    try:
        variables = resolve_variables(args.var)
        path = Path(args.path)
        if path.is_file():
            sql_files = [path]
        else:
            print(f"Scanning directory: {path}")
            sql_files, non_matching_files = get_sorted_sql_files(str(path))
            if non_matching_files:
                print(f"\n⚠️  WARNING: Found {len(non_matching_files)} SQL file(s) that don't match "
                      "naming convention (NNN-*.sql):")
                for file_path in non_matching_files:
                    print(f"     - {file_path.name} (not processed)")
            if not sql_files:
                print(f"\nNo SQL files with numeric prefix (NNN-*.sql) found in: {path}")
                sys.exit(0)

        success = execute_sql_files_with_psql(args.service_name, sql_files, variables, echo=not args.no_echo)
        sys.exit(0 if success else 1)

    except (ValueError, OSError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
