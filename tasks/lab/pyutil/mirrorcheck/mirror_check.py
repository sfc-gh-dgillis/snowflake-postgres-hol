#!/usr/bin/env python3
"""
mirror_check - cross-system checks for the Snowflake Postgres mirror HOL

Each lab step changes data in Postgres, then uses this script to wait until
Snowflake has caught up, printing a timeline so you can watch the mirror
work: $live views catch up within ~30 seconds, while the target tables move
on every refresh interval.

Postgres is queried with psql (service PG_SERVICE_NAME from
~/.pg_service.conf); Snowflake with the snow CLI (CLI_CONNECTION_NAME).
Configuration is read from the environment (.env/mirror.env, loaded by Task).

Commands:
  grant-mirror-admin  grant postgres_mirror_admin to MIRROR_ADMIN_ROLE_NAME (as ACCOUNTADMIN) if needed
  preflight         check the instance and target database before CREATE_MIRROR
  create-mirror     run the CREATE_MIRROR SQL file unless the mirror already exists
  wait-replicating  wait until every mirrored table reports REPLICATING
  compare           compare Postgres, Snowflake target, and $live row counts
  wait-count        wait until a target table's row count matches Postgres
  wait-live         wait until a table's $live view matches Postgres
  wait-columns      wait until a schema change shows up in a target table
  observe           print Postgres / target / $live counts for a while (no assertion)
  refresh           apply pending changes now (REFRESH_MIRROR)
  status            mirror health: status, lag, errors, table states, apply runs
  drop-mirror       drop the mirror and its target database (requires --yes)
  setup-status      readiness checklist after setup: PASS / FAIL / INFO with a fix for each item
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_TABLES = ["devices", "sensors", "readings"]
TABLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")


class LabError(Exception):
    """An expected failure with a user-facing message."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise LabError(f"{name} is not set (see .env/mirror.env)")
    return value


def env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def mirror_name() -> str:
    return env("MIRROR_NAME").lower()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def target_table(table: str, suffix: str = "") -> str:
    """Fully qualified Snowflake target table for a Postgres table (identifiers fold to uppercase)."""
    return (f"{env('MIRROR_TARGET_DATABASE_NAME')}.{env('PG_SCHEMA_NAME').upper()}."
            f"{table.upper()}{suffix}")


def parse_tables(value: Optional[str]) -> List[str]:
    tables = [t.strip().lower() for t in value.split(",")] if value else list(DEFAULT_TABLES)
    for table in tables:
        if not TABLE_NAME.match(table):
            raise LabError(f"Invalid table name: {table}")
    return tables


# ---------------------------------------------------------------------------
# Snowflake (snow CLI) and Postgres (psql) access
# ---------------------------------------------------------------------------

def _parse_json_rows(stdout: str) -> List[Dict[str, Any]]:
    starts = [i for i in (stdout.find("["), stdout.find("{")) if i >= 0]
    if not starts:
        return []
    data, _ = json.JSONDecoder().raw_decode(stdout[min(starts):])
    if isinstance(data, dict):
        data = [data]
    rows = []
    for item in data:
        if isinstance(item, dict):
            rows.append({str(k).lower(): v for k, v in item.items()})
        elif isinstance(item, list):
            rows.extend({str(k).lower(): v for k, v in r.items()} for r in item if isinstance(r, dict))
    return rows


def snow_rows(query: str, role: Optional[str] = None) -> List[Dict[str, Any]]:
    """Run ONE Snowflake statement and return its rows (keys lowercased)."""
    cmd = [
        "snow", "sql",
        "--connection", env("CLI_CONNECTION_NAME"),
        "--role", role or env("MIRROR_ADMIN_ROLE_NAME"),
        "--warehouse", env("DEMO_WAREHOUSE_NAME"),
        "--format", "JSON",
        "--enable-templating", "NONE",
        "-q", query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise LabError("snow CLI not found; run `task validate-prerequisites`")
    if result.returncode != 0:
        raise LabError((result.stderr or result.stdout).strip())
    return _parse_json_rows(result.stdout)


def psql_rows(query: str) -> List[Dict[str, str]]:
    """Run ONE Postgres query and return its rows."""
    cmd = [
        "psql", f"service={env('PG_SERVICE_NAME')} connect_timeout=10",
        "--no-psqlrc", "--quiet", "--csv",
        "--set", "ON_ERROR_STOP=1",
        "-c", query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise LabError("psql not found; run `task validate-prerequisites`")
    if result.returncode != 0:
        raise LabError("Postgres query failed: " + (result.stderr or result.stdout).strip()
                       + "\n  (Connection timeouts usually mean your IP changed: `task pg-allow-my-ip`)")
    return list(csv.DictReader(io.StringIO(result.stdout)))


def pick(row: Dict[str, Any], *names: str) -> Any:
    """First present key among `names` (rows have lowercased keys)."""
    for name in names:
        if row.get(name) not in (None, ""):
            return row[name]
    return None


def first_line(text: str) -> str:
    lines = [line.strip(" │╭╰─") for line in str(text).splitlines()]
    lines = [line for line in lines if line and not set(line) <= set("─╮╯ ")]
    return " ".join(lines[:3]) if lines else str(text)


# ---------------------------------------------------------------------------
# Mirror lookups
# ---------------------------------------------------------------------------

def list_mirrors() -> List[Dict[str, Any]]:
    return snow_rows("SELECT * FROM TABLE(SNOWFLAKE.POSTGRES.LIST_MIRRORS())")


def holds_mirror_admin() -> bool:
    """True when MIRROR_ADMIN_ROLE_NAME can call the mirror procedures (granted or inherited)."""
    try:
        list_mirrors()
        return True
    except LabError:
        return False


def find_mirror() -> Optional[Dict[str, Any]]:
    for row in list_mirrors():
        if str(pick(row, "mirror_name", "name") or "").lower() == mirror_name():
            return row
    return None


def mirror_target(row: Dict[str, Any]) -> str:
    value = pick(row, "target_database", "target_database_name", "target_db")
    if value is None:
        for key, val in row.items():
            if "target" in key and "database" in key and val:
                value = val
                break
    return str(value or "")


def describe_mirror() -> Dict[str, Any]:
    rows = snow_rows(f"SELECT * FROM TABLE(SNOWFLAKE.POSTGRES.DESCRIBE_MIRROR({sql_literal(mirror_name())}))")
    if not rows:
        raise LabError(f"Mirror {mirror_name()} not found")
    return rows[0]


def mirrored_tables() -> List[Dict[str, Any]]:
    return snow_rows(f"CALL SNOWFLAKE.POSTGRES.LIST_MIRRORED_TABLES({sql_literal(mirror_name())})")


def show_instance(name: str) -> Optional[Dict[str, Any]]:
    for row in snow_rows(f"SHOW POSTGRES INSTANCES LIKE {sql_literal(name)}"):
        if row.get("name") == name:
            return row
    return None


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def pg_count(table: str) -> int:
    rows = psql_rows(f"SELECT COUNT(*) AS n FROM {env('PG_SCHEMA_NAME')}.{table}")
    return int(rows[0]["n"])


def sf_counts(table: str) -> Tuple[Optional[int], Optional[int]]:
    """(target table count, $live count). $live is None while it is unavailable (e.g. re-snapshot)."""
    base, live = target_table(table), target_table(table, "$LIVE")
    try:
        rows = snow_rows(f"SELECT (SELECT COUNT(*) FROM {base}) AS base_count, "
                         f"(SELECT COUNT(*) FROM {live}) AS live_count")
        return int(rows[0]["base_count"]), int(rows[0]["live_count"])
    except LabError:
        try:
            rows = snow_rows(f"SELECT COUNT(*) AS base_count FROM {base}")
            return int(rows[0]["base_count"]), None
        except LabError:
            return None, None


def fmt(value: Optional[int]) -> str:
    return "n/a" if value is None else str(value)


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

class Poller:
    def __init__(self, timeout: Optional[int] = None):
        self.timeout = timeout or env_int("LAB_SYNC_TIMEOUT_SECONDS", 300)
        self.interval = env_int("LAB_POLL_INTERVAL_SECONDS", 10)
        self.start = time.time()

    @property
    def elapsed(self) -> int:
        return int(time.time() - self.start)

    def stamp(self) -> str:
        return f"[{self.elapsed:>4}s]"

    def sleep_or_timeout(self, what: str) -> None:
        if self.elapsed >= self.timeout:
            raise LabError(f"Timed out after {self.elapsed}s waiting for {what}.\n"
                           "  Check mirror health with `task mirror-status`; apply pending changes now "
                           "with `task mirror-refresh`; or raise LAB_SYNC_TIMEOUT_SECONDS.")
        time.sleep(self.interval)


def maybe_refresh(args: argparse.Namespace) -> None:
    if getattr(args, "refresh", False) or os.environ.get("LAB_FORCE_REFRESH", "").lower() == "true":
        print("Applying pending changes now (REFRESH_MIRROR)...")
        snow_rows(f"CALL SNOWFLAKE.POSTGRES.REFRESH_MIRROR({sql_literal(mirror_name())})")


def count_header() -> None:
    print(f"  {'elapsed':<8} {'postgres':>9} {'snowflake':>10} {'$live':>8}")


def count_line(poller: Poller, pg: int, base: Optional[int], live: Optional[int]) -> None:
    note = ""
    if base == pg:
        note = "✓ target table matches Postgres"
    elif live == pg:
        note = "← $live already has the change; the target table catches up on the next apply"
    print(f"  {poller.stamp():<8} {pg:>9} {fmt(base):>10} {fmt(live):>8}   {note}", flush=True)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_grant_mirror_admin(_args: argparse.Namespace) -> None:
    """Give MIRROR_ADMIN_ROLE_NAME the postgres_mirror_admin application role.

    Runs during setup (demo-up / infrastructure-up), not in step 1: on a new
    account the snowflake application can take up to an hour to appear, and
    that is better found before the session than in the middle of it.

    ACCOUNTADMIN grants it (per the docs), so a non-ACCOUNTADMIN role that owns
    the instance can't grant it to itself. Skip when the role can already call
    the mirror procedures (granted directly or inherited).
    """
    role = env("MIRROR_ADMIN_ROLE_NAME")
    if holds_mirror_admin():
        print(f"✓ {role} already holds snowflake.postgres_mirror_admin")
        return

    grant = f"GRANT APPLICATION ROLE SNOWFLAKE.POSTGRES_MIRROR_ADMIN TO ROLE {role}"
    print(f"Granting the mirror admin application role (as ACCOUNTADMIN):\n    {grant};", flush=True)
    try:
        snow_rows(grant, role="ACCOUNTADMIN")
    except LabError as exc:
        hint = ""
        if "does not exist" in str(exc).lower() and "postgres_mirror_admin" in str(exc).lower():
            hint = ("\n  On a newly created account the snowflake application can take up to an hour "
                    "to provision; wait and retry.")
        raise LabError(f"Could not grant postgres_mirror_admin to {role}: {first_line(exc)}\n"
                       f"  Ask an account admin to run, then re-run `task infrastructure-up`:\n"
                       f"    {grant};{hint}")
    print(f"✓ {role} now holds snowflake.postgres_mirror_admin")


def cmd_preflight(_args: argparse.Namespace) -> None:
    target = env("MIRROR_TARGET_DATABASE_NAME")
    instance_name = env("PG_INSTANCE_NAME")
    role = env("MIRROR_ADMIN_ROLE_NAME")

    if not holds_mirror_admin():
        raise LabError(f"{role} cannot call the mirror procedures: it does not hold "
                       "snowflake.postgres_mirror_admin. Run `task infrastructure-up` (it grants the "
                       "role as ACCOUNTADMIN), or have an account admin run:\n"
                       f"    GRANT APPLICATION ROLE SNOWFLAKE.POSTGRES_MIRROR_ADMIN TO ROLE {role};")
    print(f"✓ {role} holds snowflake.postgres_mirror_admin")

    existing = find_mirror()
    if existing:
        existing_target = mirror_target(existing)
        if existing_target.upper() == target.upper():
            print(f"✓ Mirror {mirror_name()} already exists with target database {target}; "
                  "CREATE_MIRROR will be skipped")
            return
        raise LabError(f"Mirror {mirror_name()} already exists with target database "
                       f"{existing_target or '(unknown)'}. Use a different MIRROR_NAME or run "
                       "`task demo-teardown` first.")

    instance = show_instance(instance_name)
    if instance is None:
        raise LabError(f"Postgres instance {instance_name} not found. Run `task demo-up` first.")
    owner = str(instance.get("owner", ""))
    if owner.upper() != role.upper():
        raise LabError(f"Instance {instance_name} is owned by {owner}. Mirror procedures require the "
                       f"caller to own the source instance; set MIRROR_ADMIN_ROLE_NAME={owner}.")
    state = str(instance.get("state", "")).upper()
    if not state.startswith("READY"):
        raise LabError(f"Instance {instance_name} is {state}, not READY. Check `task pg-instance-info`.")
    print(f"✓ Instance {instance_name} is {state} and owned by {owner}")

    if any(str(r.get("name", "")).upper() == target.upper()
           for r in snow_rows(f"SHOW DATABASES LIKE {sql_literal(target)}")):
        raise LabError(f"Target database {target} already exists. CREATE_MIRROR creates the target "
                       "database itself, and a name can never be reused (even after a drop): bump "
                       "MIRROR_TARGET_DATABASE_NAME in .env/mirror.env, e.g. _01 -> _02.")
    print(f"✓ Target database {target} does not exist yet (CREATE_MIRROR will create it)")


def cmd_create_mirror(args: argparse.Namespace) -> None:
    target = env("MIRROR_TARGET_DATABASE_NAME")
    existing = find_mirror()
    if existing and mirror_target(existing).upper() == target.upper():
        print(f"✓ Mirror {mirror_name()} already exists with target database {target}; skipping CREATE_MIRROR")
        return

    print(f"Creating mirror {mirror_name()} with {args.sql_file}:\n")
    with open(args.sql_file) as handle:
        print("\n".join("    " + line for line in handle.read().strip().splitlines()))
    print("", flush=True)

    cmd = ["snow", "sql", "--connection", env("CLI_CONNECTION_NAME"),
           "--project", args.project, "-f", args.sql_file]
    result = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    if result.returncode == 0:
        print(f"\n✓ Mirror {mirror_name()} created; Snowflake is creating {target} and taking the "
              "initial snapshot")
        return

    error = (result.stderr or "") + (result.stdout or "")
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    lowered = error.lower()
    if "permission denied to create extension" in lowered or ("extension" in lowered and "permission" in lowered):
        raise LabError("The instance predates mirroring and needs a refresh. There is no SQL for this: open "
                       f"Snowsight > Postgres > {env('PG_INSTANCE_NAME')} > Manage, run the refresh/update "
                       "action, then re-run `task step-1-create-mirror`.")
    if "already exists" in lowered or "reuse" in lowered or "previously" in lowered:
        raise LabError("The target database name is taken or was used by an earlier mirror. Names can "
                       "never be reused: bump MIRROR_TARGET_DATABASE_NAME, then re-run the step.")
    if "max_replication_slots" in lowered:
        raise LabError("The instance is out of replication slots; drop unused mirrors or raise "
                       "max_replication_slots (see README troubleshooting).")
    raise LabError("CREATE_MIRROR failed (see the error above)")


def cmd_wait_replicating(args: argparse.Namespace) -> None:
    wanted = parse_tables(args.tables)
    poller = Poller(args.timeout)
    print(f"Waiting for {', '.join(wanted)} to reach REPLICATING "
          f"(timeout {poller.timeout}s; the initial snapshot copies every row first)...")
    last_line, seen_errors = None, set()
    while True:
        states = {}
        for row in mirrored_tables():
            table = str(pick(row, "source_table_name", "table_name") or "").lower()
            state = str(pick(row, "state") or "UNKNOWN").upper()
            pct = pick(row, "snapshot_percentage")
            if state == "SNAPSHOTTING" and pct is not None:
                state = f"SNAPSHOTTING {float(pct):.0f}%"
            states[table] = state
            error = pick(row, "last_snapshot_error")
            if error and error not in seen_errors:
                seen_errors.add(error)
                print(f"  ⚠️  {table}: last snapshot error: {error}")
        line = "  ".join(f"{t}={states.get(t, 'pending')}" for t in wanted)
        if line != last_line:
            print(f"  {poller.stamp()} {line}", flush=True)
            last_line = line
        if all(states.get(t) == "REPLICATING" for t in wanted):
            print(f"✓ All {len(wanted)} table(s) are REPLICATING")
            return
        poller.sleep_or_timeout("tables to reach REPLICATING")


def cmd_compare(args: argparse.Namespace) -> None:
    tables = parse_tables(args.tables)
    poller = Poller(args.timeout)
    while True:
        results = [(t, pg_count(t)) + sf_counts(t) for t in tables]
        matched = all(base == pg for _, pg, base, _ in results)
        if matched or not args.wait:
            break
        print(f"  {poller.stamp()} waiting for target tables to match Postgres...", flush=True)
        poller.sleep_or_timeout("target tables to match Postgres")

    print(f"\n  {'table':<20} {'postgres':>9} {'snowflake':>10} {'$live':>8}")
    for table, pg, base, live in results:
        mark = "✓" if base == pg else "✗"
        print(f"  {table:<20} {pg:>9} {fmt(base):>10} {fmt(live):>8}   {mark}")
    print("")
    if matched:
        print("✓ Snowflake target tables match Postgres")
    elif args.wait:
        raise LabError("Row counts differ between Postgres and Snowflake")
    else:
        print("Counts differ: changes are still being applied (or a writer is running).")


def cmd_wait_count(args: argparse.Namespace) -> None:
    table = parse_tables(args.table)[0]
    maybe_refresh(args)
    poller = Poller(args.timeout)
    print(f"Waiting for {target_table(table)} to match Postgres "
          f"(refresh interval {os.environ.get('MIRROR_REFRESH_INTERVAL', '?')}, timeout {poller.timeout}s)")
    count_header()
    while True:
        pg = pg_count(table)
        base, live = sf_counts(table)
        count_line(poller, pg, base, live)
        if base == pg:
            return
        poller.sleep_or_timeout(f"{target_table(table)} to match Postgres")


def cmd_wait_live(args: argparse.Namespace) -> None:
    table = parse_tables(args.table)[0]
    poller = Poller(args.timeout)
    print(f"Watching {target_table(table, '$live')} (~30s lag) versus {target_table(table)} "
          f"(updated every {os.environ.get('MIRROR_REFRESH_INTERVAL', '?')})")
    count_header()
    while True:
        pg = pg_count(table)
        base, live = sf_counts(table)
        count_line(poller, pg, base, live)
        if live == pg:
            print(f"✓ {table.upper()}$live shows the change"
                  + ("" if base == pg else f"; {table.upper()} will catch up on the next apply run"))
            return
        poller.sleep_or_timeout(f"{target_table(table, '$live')} to match Postgres")


def cmd_wait_columns(args: argparse.Namespace) -> None:
    table = parse_tables(args.table)[0]
    present = [c.strip().upper() for c in (args.present or "").split(",") if c.strip()]
    absent = [c.strip().upper() for c in (args.absent or "").split(",") if c.strip()]
    poller = Poller(args.timeout)
    fqn = target_table(table)
    print(f"Waiting for the schema change to reach {fqn} "
          f"(expect {', '.join(present) or '-'}; gone: {', '.join(absent) or '-'})")
    last = None
    while True:
        try:
            columns = [str(r.get("column_name", "")).upper() for r in snow_rows(f"SHOW COLUMNS IN TABLE {fqn}")]
        except LabError:
            columns = []
        if columns != last:
            print(f"  {poller.stamp()} columns: {', '.join(columns) or '(table unavailable)'}", flush=True)
            last = columns
        if columns and all(c in columns for c in present) and not any(c in columns for c in absent):
            print(f"✓ {fqn} has the new schema")
            return
        poller.sleep_or_timeout(f"the schema change on {fqn}")


def cmd_observe(args: argparse.Namespace) -> None:
    table = parse_tables(args.table)[0]
    poller = Poller(args.seconds)
    print(f"Observing {table} for {args.seconds}s")
    count_header()
    while True:
        pg = pg_count(table)
        base, live = sf_counts(table)
        count_line(poller, pg, base, live)
        if poller.elapsed + poller.interval > args.seconds:
            return
        time.sleep(poller.interval)


def cmd_refresh(_args: argparse.Namespace) -> None:
    snow_rows(f"CALL SNOWFLAKE.POSTGRES.REFRESH_MIRROR({sql_literal(mirror_name())})")
    print(f"✓ REFRESH_MIRROR queued an apply run for {mirror_name()}")


def cmd_status(args: argparse.Namespace) -> None:
    info = describe_mirror()
    print(f"Mirror {mirror_name()}")
    keys = ["status", "postgres_instance", "postgres_database", "target_database", "target_table_type",
            "refresh_interval", "warehouse", "apply_lag_seconds", "apply_lag_operations",
            "apply_lag_bytes", "last_applied_commit_time", "last_operation_time", "error_message"]
    for key in (sorted(info) if args.all else keys):
        if key in info and key not in ("recent_query_durations", "postgres_status"):
            print(f"  {key:<26} {'n/a' if info[key] is None else info[key]}")
    postgres_status = info.get("postgres_status")
    if isinstance(postgres_status, str):
        try:
            postgres_status = json.loads(postgres_status)
        except ValueError:
            pass
    if isinstance(postgres_status, dict):
        for key in ("cdc_flush_lag_seconds", "slot_lag_bytes"):
            if key in postgres_status:
                print(f"  {'postgres ' + key:<26} {postgres_status[key]}")

    print("\nMirrored tables")
    print(f"  {'table':<22} {'state':<14} {'snapshot':<14} {'reason'}")
    for row in mirrored_tables():
        table = f"{pick(row, 'source_schema_name') or ''}.{pick(row, 'source_table_name') or ''}"
        print(f"  {table:<22} {str(pick(row, 'state') or ''):<14} "
              f"{str(pick(row, 'snapshot_state') or ''):<14} {pick(row, 'snapshot_reason') or ''}")

    task_name = f"APPLY_MIRROR_{mirror_name()}".upper()
    try:
        runs = snow_rows(
            "SELECT name, state, scheduled_time, completed_time, error_message "
            "FROM TABLE(SNOWFLAKE.INFORMATION_SCHEMA.TASK_HISTORY("
            "SCHEDULED_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP()), RESULT_LIMIT => 10000)) "
            f"WHERE UPPER(name) = {sql_literal(task_name)} ORDER BY scheduled_time DESC LIMIT 8")
        print(f"\nRecent apply task runs ({task_name}, serverless)")
        for run in runs:
            print(f"  {str(run.get('scheduled_time'))[:19]}  {str(run.get('state')):<10} "
                  f"{run.get('error_message') or ''}")
        if not runs:
            print("  (none in the last hour)")
    except LabError as exc:
        print(f"\n(Apply task history unavailable: {first_line(exc)})")


def cmd_drop_mirror(args: argparse.Namespace) -> None:
    if not args.yes:
        raise LabError("drop-mirror deletes the mirror and its target database; re-run with --yes")
    try:
        existing = find_mirror()
    except LabError as exc:
        if re.search(r"not authorized|does not exist|insufficient privileges", str(exc), re.I):
            print(f"Could not list mirrors ({first_line(exc)}); assuming {mirror_name()} was never created.")
            return
        raise
    if not existing:
        print(f"Mirror {mirror_name()} not found; nothing to drop.")
        return
    target = mirror_target(existing) or env("MIRROR_TARGET_DATABASE_NAME")
    print(f"Dropping mirror {mirror_name()} and its target database {target}...")
    snow_rows(f"CALL SNOWFLAKE.POSTGRES.DROP_MIRROR({sql_literal(mirror_name())}, drop_target_database => TRUE)")
    print(f"✓ Mirror {mirror_name()} dropped (publication, replication slot, apply task, target database)")


def _show_one(query: str, name: str) -> Optional[Dict[str, Any]]:
    """The row named `name` (case-insensitive) from a SHOW ... LIKE query, if any."""
    for row in snow_rows(query):
        if str(row.get("name", "")).upper() == name.upper():
            return row
    return None


def _bare_name(value: Any) -> str:
    """Last part of a possibly qualified, possibly quoted identifier, uppercased."""
    return str(value or "").split(".")[-1].strip('"').upper()


def cmd_setup_status(_args: argparse.Namespace) -> None:
    """One readiness checklist for the lab setup: PASS / FAIL / INFO with a fix for each.

    Every check runs even if an earlier one fails, so one run shows everything
    that is missing. Never prints credentials.
    """
    mode = os.environ.get("POSTGRES_INSTANCE_MODE", "create")
    role = env("MIRROR_ADMIN_ROLE_NAME")
    warehouse = env("DEMO_WAREHOUSE_NAME")
    database, schema = env("DEMO_DATABASE_NAME"), env("DEMO_SCHEMA_NAME")
    stage = env("DEMO_INTERNAL_NAMED_STAGE")
    analyst = env("DEMO_ANALYST_ROLE_NAME")
    instance_name = env("PG_INSTANCE_NAME")
    service = env("PG_SERVICE_NAME")
    results: List[Tuple[str, str, str]] = []
    dcm_project = (f"{env('DCM_PROJECT_DATABASE')}.{env('DCM_PROJECT_SCHEMA')}."
                   f"{env('DCM_SETUP_PROJECT_NAME')}")

    def check(item: str, fix: str, test) -> None:
        try:
            outcome = test()
        except LabError as exc:
            results.append((item, "FAIL", f"{first_line(exc)}  ->  {fix}"))
            return
        if outcome is True:
            results.append((item, "PASS", ""))
        elif outcome is False:
            results.append((item, "FAIL", fix))
        else:
            # (status, detail) for anything other than a plain pass/fail
            results.append((item, outcome[0], outcome[1]))

    check(f"DCM project {dcm_project}", "Re-run `task infrastructure-up` (it registers and deploys it).",
          lambda: bool(snow_rows(f"DESCRIBE DCM PROJECT {dcm_project}")))
    check(f"Warehouse {warehouse}", "Re-run `task infrastructure-up`.",
          lambda: _show_one(f"SHOW WAREHOUSES LIKE {sql_literal(warehouse)}", warehouse) is not None)
    check(f"Lab schema {database}.{schema}", "Re-run `task infrastructure-up`.",
          lambda: _show_one(f"SHOW SCHEMAS LIKE {sql_literal(schema)} IN DATABASE {database}", schema)
          is not None)
    check(f"Stage {database}.{schema}.{stage}", "Re-run `task infrastructure-up`.",
          lambda: _show_one(f"SHOW STAGES LIKE {sql_literal(stage)} IN SCHEMA {database}.{schema}", stage)
          is not None)
    check(f"Analyst role {analyst}", "Re-run `task infrastructure-up`.",
          lambda: _show_one(f"SHOW ROLES LIKE {sql_literal(analyst)}", analyst) is not None)
    check(f"{role} holds snowflake.postgres_mirror_admin",
          "Re-run `task infrastructure-up`, or have an account admin run: GRANT APPLICATION ROLE "
          f"SNOWFLAKE.POSTGRES_MIRROR_ADMIN TO ROLE {role}; (new accounts: allow up to an hour)",
          holds_mirror_admin)

    instance: Dict[str, Any] = {}

    def instance_ready():
        found = show_instance(instance_name)
        if found is None:
            return ("FAIL", "Not found. Re-run `task infrastructure-up` (create mode), or check "
                            "PG_INSTANCE_NAME (it is case-sensitive).")
        instance.update(found)
        state = str(found.get("state", "")).upper()
        owner = str(found.get("owner", ""))
        if owner.upper() != role.upper():
            return ("FAIL", f"Owned by {owner}. Mirror procedures need the caller to own the instance: "
                            f"set MIRROR_ADMIN_ROLE_NAME={owner}.")
        if not state.startswith("READY"):
            return ("WAIT", f"State {state}. Still provisioning or resuming: run `task setup-status` "
                            "again in a minute.")
        return True

    check(f"Postgres instance {instance_name} READY and owned by {role}", "", instance_ready)

    if mode == "create":
        policy = env("PG_NETWORK_POLICY_NAME")
        rule = f"{database}.{schema}.{env('PG_NETWORK_RULE_NAME')}"

        def policy_attached():
            if _show_one(f"SHOW NETWORK POLICIES LIKE {sql_literal(policy)}", policy) is None:
                return ("FAIL", "Policy not found. Run `task pg-allow-my-ip`.")
            # DESCRIBE output holds secrets: read only the network_policy property, never print it
            attached = ""
            for row in snow_rows(f'DESCRIBE POSTGRES INSTANCE "{instance_name}"'):
                if str(row.get("property", "")).lower() == "network_policy":
                    attached = str(row.get("value") or "")
            if _bare_name(attached) != policy.upper():
                return ("FAIL", f"Instance uses {attached or 'no network policy'}. Attach it with: "
                                f'ALTER POSTGRES INSTANCE "{instance_name}" SET NETWORK_POLICY = \'{policy}\';')
            return True

        def ip_allowed():
            cidr = os.environ.get("PG_ALLOWED_CIDR", "AUTO")
            if cidr == "AUTO":
                cidr = str(snow_rows("SELECT CURRENT_IP_ADDRESS() AS ip")[0]["ip"]) + "/32"
            rows = snow_rows(f"DESCRIBE NETWORK RULE {rule}")
            values = " ".join(str(v) for row in rows for k, v in row.items() if "value" in k)
            if cidr not in values:
                return ("FAIL", f"Rule allows {values or 'nothing'}, not {cidr}. Your IP probably changed: "
                                "run `task pg-allow-my-ip`.")
            return True

        check(f"Network policy {policy} attached to the instance", "", policy_attached)
        check("Ingress rule allows your IP (or PG_ALLOWED_CIDR)", "", ip_allowed)
    else:
        results.append(("Postgres network policy", "INFO",
                        "Existing mode: managed by you; the lab does not change it."))

    def pg_connects():
        psql_rows("SELECT 1 AS ok")
        return True

    check(f'Postgres login (psql "service={service}")',
          "Timeouts: run `task pg-allow-my-ip`. Password errors: run `task pg-reset-access`.", pg_connects)

    if instance.get("host"):
        results.append(("Postgres hostname", "INFO", str(instance["host"])))
    results.append(("Postgres password", "INFO",
                    f"Saved for {os.environ.get('PG_USER', 'snowflake_admin')} in ~/.pgpass (mode 600); "
                    "never displayed. Rotate with `task pg-reset-access`."))

    width = max(len(item) for item, _, _ in results)
    print("Setup status")
    for item, status, detail in results:
        print(f"  {item:<{width}}  {status:<4}  {detail}".rstrip())

    not_ready = [item for item, status, _ in results if status in ("FAIL", "WAIT")]
    if not_ready:
        raise LabError(f"{len(not_ready)} check(s) not passing; fix them, then run `task setup-status` again.")
    print("\n✓ Setup is ready. Next: task step-1-create-mirror")


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-system checks for the Snowflake Postgres mirror HOL")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("grant-mirror-admin", help="grant postgres_mirror_admin to MIRROR_ADMIN_ROLE_NAME"
                   ).set_defaults(func=cmd_grant_mirror_admin)

    sub.add_parser("preflight", help="check the instance and target database").set_defaults(func=cmd_preflight)

    p = sub.add_parser("create-mirror", help="run the CREATE_MIRROR SQL file unless the mirror exists")
    p.add_argument("--sql-file", required=True, help="SQL file with the CREATE_MIRROR call")
    p.add_argument("--project", required=True, help="snow CLI project dir holding snowflake.yml")
    p.set_defaults(func=cmd_create_mirror)

    p = sub.add_parser("wait-replicating", help="wait until mirrored tables are REPLICATING")
    p.add_argument("--tables", help=f"comma-separated tables (default: {','.join(DEFAULT_TABLES)})")
    p.add_argument("--timeout", type=int, help="seconds (default: LAB_SYNC_TIMEOUT_SECONDS)")
    p.set_defaults(func=cmd_wait_replicating)

    p = sub.add_parser("compare", help="compare Postgres, Snowflake, and $live row counts")
    p.add_argument("--tables", help=f"comma-separated tables (default: {','.join(DEFAULT_TABLES)})")
    p.add_argument("--wait", action="store_true", help="wait until the target tables match, then assert")
    p.add_argument("--timeout", type=int, help="seconds (default: LAB_SYNC_TIMEOUT_SECONDS)")
    p.set_defaults(func=cmd_compare)

    for command, func, help_text in (
        ("wait-count", cmd_wait_count, "wait until the target table matches Postgres"),
        ("wait-live", cmd_wait_live, "wait until the $live view matches Postgres"),
    ):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("--table", required=True, help="Postgres table name")
        p.add_argument("--timeout", type=int, help="seconds (default: LAB_SYNC_TIMEOUT_SECONDS)")
        if command == "wait-count":
            p.add_argument("--refresh", action="store_true", help="call REFRESH_MIRROR first")
        p.set_defaults(func=func)

    p = sub.add_parser("wait-columns", help="wait until a schema change reaches the target table")
    p.add_argument("--table", required=True, help="Postgres table name")
    p.add_argument("--present", help="comma-separated columns that must exist")
    p.add_argument("--absent", help="comma-separated columns that must be gone")
    p.add_argument("--timeout", type=int, help="seconds (default: LAB_SYNC_TIMEOUT_SECONDS)")
    p.set_defaults(func=cmd_wait_columns)

    p = sub.add_parser("observe", help="print counts for a while without asserting")
    p.add_argument("--table", required=True, help="Postgres table name")
    p.add_argument("--seconds", type=int, default=90, help="how long to observe (default: 90)")
    p.set_defaults(func=cmd_observe)

    sub.add_parser("refresh", help="apply pending changes now").set_defaults(func=cmd_refresh)

    p = sub.add_parser("status", help="mirror health summary")
    p.add_argument("--all", action="store_true", help="print every DESCRIBE_MIRROR column")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("drop-mirror", help="drop the mirror and its target database")
    p.add_argument("--yes", action="store_true", help="confirm the drop")
    p.set_defaults(func=cmd_drop_mirror)

    sub.add_parser("setup-status", help="readiness checklist for the lab setup"
                   ).set_defaults(func=cmd_setup_status)

    args = parser.parse_args()
    try:
        args.func(args)
    except LabError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
