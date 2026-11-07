#!/usr/bin/env python3
"""
pg_instance - Snowflake Postgres instance lifecycle for the mirror HOL

Wraps the Snowflake CLI (like snowclisp), so it reuses the auth of your
CLI_CONNECTION_NAME connection.

Credentials returned by CREATE POSTGRES INSTANCE and RESET ACCESS are parsed
in memory and written ONLY to your libpq password file (~/.pgpass, mode 600).
They are never printed, logged, or written anywhere else.

Connection files use the standard libpq layout (the same one Cortex Code's
Postgres skill uses), so `psql "service=<PG_SERVICE_NAME>"` works everywhere:
  ~/.pg_service.conf                          connection profile (no secrets)
  ~/.pgpass                                   password (mode 600)
  ~/.snowflake/postgres/certs/<service>.pem   instance CA cert (sslmode=verify-ca)
PGSERVICEFILE and PGPASSFILE are honored if set.

Commands:
  create        create mode: create (or reuse) the instance, wait for READY, save the connection
  attach        existing mode: check ownership, resume if suspended, save the service entry + cert
  wait-ready    wait until the instance is READY
  info          show safe instance fields
  reset-access  rotate the PG_USER password and save it to ~/.pgpass (requires --yes)
  drop          create mode: drop the instance and wait until it is gone (requires --yes)
  forget        remove the local service entry, password line(s), and CA cert

Configuration is read from the environment (.env/mirror.env, loaded by Task).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PG_PORT = 5432
# Compute families offered on AWS only (BURST_* is refused separately).
# See https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-instance-sizes
AWS_ONLY_FAMILIES = {"STANDARD_M"}
READY_STATES = {"READY", "READY_ENABLING_HA"}
FAILED_STATES = {"FAILED"}
POLL_SECONDS = 15
PROBE_TIMEOUT_SECONDS = 20
# Only these SHOW POSTGRES INSTANCES columns are ever printed.
SAFE_FIELDS = ("name", "state", "owner", "compute_family", "storage_size_gb",
               "postgres_version", "high_availability", "host", "created_on")


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


def service_file() -> Path:
    return Path(os.environ.get("PGSERVICEFILE") or Path.home() / ".pg_service.conf")


def pgpass_file() -> Path:
    return Path(os.environ.get("PGPASSFILE") or Path.home() / ".pgpass")


def cert_path(service_name: str) -> Path:
    return Path.home() / ".snowflake" / "postgres" / "certs" / f"{service_name}.pem"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def require_mode(expected: str) -> None:
    mode = os.environ.get("POSTGRES_INSTANCE_MODE", "create")
    if mode != expected:
        raise LabError(f"This command only runs when POSTGRES_INSTANCE_MODE={expected} "
                       f"(current: {mode}).")


# ---------------------------------------------------------------------------
# Snowflake access (via snow CLI)
# ---------------------------------------------------------------------------

_SECRET_PATTERN = re.compile(
    r'(?i)("?(?:password|access_roles)"?\s*[:=]\s*)("(?:[^"\\]|\\.)*"|\{[^}]*\}|\[[^\]]*\]|\S+)')


def _redact(text: str) -> str:
    return _SECRET_PATTERN.sub(r'\1"***"', text or "")


def _parse_json_rows(stdout: str) -> List[Dict[str, Any]]:
    """Parse `snow sql --format JSON` output, tolerating leading non-JSON lines."""
    starts = [i for i in (stdout.find("["), stdout.find("{")) if i >= 0]
    if not starts:
        return []
    data, _ = json.JSONDecoder().raw_decode(stdout[min(starts):])
    if isinstance(data, dict):
        data = [data]
    rows = []
    for item in data:
        if isinstance(item, dict):
            rows.append(item)
        elif isinstance(item, list):  # multi-statement output: list of result sets
            rows.extend(r for r in item if isinstance(r, dict))
    return rows


def run_snow_sql(query: str) -> List[Dict[str, Any]]:
    """Run ONE statement and return its rows. Output is captured, never echoed."""
    cmd = [
        "snow", "sql",
        "--connection", env("CLI_CONNECTION_NAME"),
        "--role", env("MIRROR_ADMIN_ROLE_NAME"),
        "--format", "JSON",
        "--enable-templating", "NONE",
        "-q", query,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise LabError("snow CLI not found. Install it: "
                       "https://docs.snowflake.com/en/developer-guide/snowflake-cli/installation/installation")
    if result.returncode != 0:
        raise LabError("Snowflake command failed:\n" + _redact(result.stderr.strip() or result.stdout.strip()))
    return _parse_json_rows(result.stdout)


def _lower_keys(row: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k).lower(): v for k, v in row.items()}


def show_instance(name: str) -> Optional[Dict[str, Any]]:
    pattern = name.replace("'", "''")
    for row in run_snow_sql(f"SHOW POSTGRES INSTANCES LIKE '{pattern}'"):
        row = _lower_keys(row)
        if row.get("name") == name:
            return row
    return None


def describe_instance(name: str) -> Dict[str, Any]:
    """Return DESCRIBE output as a property map. Contains secrets: never print it."""
    props: Dict[str, Any] = {}
    for row in run_snow_sql(f"DESCRIBE POSTGRES INSTANCE {quote_ident(name)}"):
        row = _lower_keys(row)
        if "property" in row and "value" in row:
            props[str(row["property"]).lower()] = row["value"]
        else:
            props.update(row)
    return props


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str) and value.strip()[:1] in ("{", "["):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def find_password(obj: Any, user: str) -> Optional[str]:
    """Find the password for `user` in a CREATE / RESET ACCESS response.

    Handles access_roles as a dict ({"snowflake_admin": "..."}), a list
    ([{"name": "snowflake_admin", "password": "..."}]), or a JSON string of
    either, plus a single-role {"password": "..."} row.
    """
    obj = _maybe_json(obj)
    if isinstance(obj, list):
        for item in obj:
            found = find_password(item, user)
            if found:
                return found
        return None
    if not isinstance(obj, dict):
        return None
    lowered = {str(k).lower(): v for k, v in obj.items()}
    if isinstance(lowered.get(user), str) and lowered[user]:
        return lowered[user]
    if str(lowered.get("name", "")).lower() == user and isinstance(lowered.get("password"), str):
        return lowered["password"]
    if "access_roles" in lowered:
        found = find_password(lowered["access_roles"], user)
        if found:
            return found
    if isinstance(lowered.get("password"), str) and lowered["password"] and "name" not in lowered:
        return lowered["password"]
    for value in lowered.values():
        if isinstance(value, (dict, list)) or (isinstance(value, str) and value.strip()[:1] in ("{", "[")):
            found = find_password(value, user)
            if found:
                return found
    return None


def find_host(rows: List[Dict[str, Any]]) -> Optional[str]:
    for row in rows:
        row = _lower_keys(row)
        if isinstance(row.get("host"), str) and row["host"]:
            return row["host"]
        if str(row.get("property", "")).lower() == "host" and row.get("value"):
            return str(row["value"])
    return None


# ---------------------------------------------------------------------------
# Local connection files
# ---------------------------------------------------------------------------

def _validate_field(value: str, field: str) -> str:
    value = str(value)
    if not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise LabError(f"Refusing to save an empty value or control characters in {field}")
    return value


def _atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _read_lines(path: Path) -> List[str]:
    return path.read_text().splitlines() if path.exists() else []


def _pgpass_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def _pgpass_split(line: str) -> List[str]:
    fields, current, i = [], [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            current.append(line[i + 1])
            i += 2
        elif line[i] == ":":
            fields.append("".join(current))
            current = []
            i += 1
        else:
            current.append(line[i])
            i += 1
    fields.append("".join(current))
    return fields


def _is_entry(line: str) -> bool:
    return bool(line.strip()) and not line.lstrip().startswith("#")


def find_pgpass_entry(host: str, port: int, database: str, user: str) -> bool:
    """libpq semantics: any line matching (with '*' wildcards) supplies the password."""
    wanted = [host, str(port), database, user]
    for line in _read_lines(pgpass_file()):
        if not _is_entry(line):
            continue
        fields = _pgpass_split(line)
        if len(fields) == 5 and all(f == "*" or f == w for f, w in zip(fields[:4], wanted)):
            return True
    return False


def upsert_pgpass_entry(host: str, port: int, database: str, user: str, password: str) -> None:
    for value, field in ((host, "host"), (database, "database"), (user, "user"), (password, "password")):
        _validate_field(value, field)
    wanted = [host, str(port), database, user]
    kept = [line for line in _read_lines(pgpass_file())
            if not (_is_entry(line) and _pgpass_split(line)[:4] == wanted)]
    new_line = ":".join(_pgpass_escape(v) for v in (host, str(port), database, user, password))
    # libpq uses the FIRST matching line, so put this exact entry ahead of any
    # wildcard entries (after a leading comment block, if any).
    insert_at = 0
    while insert_at < len(kept) and not _is_entry(kept[insert_at]):
        insert_at += 1
    kept.insert(insert_at, new_line)
    _atomic_write(pgpass_file(), "\n".join(kept) + "\n", 0o600)


def remove_pgpass_entries(host: str, port: int = PG_PORT) -> int:
    lines = _read_lines(pgpass_file())
    kept = [line for line in lines
            if not (_is_entry(line) and _pgpass_split(line)[:2] == [host, str(port)])]
    removed = len(lines) - len(kept)
    if removed:
        _atomic_write(pgpass_file(), "\n".join(kept) + ("\n" if kept else ""), 0o600)
    return removed


def _split_service_sections(lines: List[str], name: str):
    """Return (lines outside section `name`, lines inside it)."""
    outside, inside, in_section = [], [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip() == name
            if in_section:
                continue
        (inside if in_section else outside).append(line)
    return outside, inside


def read_service_entry(name: str) -> Optional[Dict[str, str]]:
    path = service_file()
    lines = _read_lines(path)
    if not any(line.strip() == f"[{name}]" for line in lines):
        return None
    _, inside = _split_service_sections(lines, name)
    entry = {}
    for line in inside:
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            entry[key.strip()] = value.strip()
    return entry


def save_service_entry(name: str, values: Dict[str, str]) -> None:
    path = service_file()
    outside, _ = _split_service_sections(_read_lines(path), name)
    while outside and not outside[-1].strip():
        outside.pop()
    block = [f"[{name}]"] + [f"{k}={_validate_field(v, k)}" for k, v in values.items()]
    text = "\n".join(outside + ([""] if outside else []) + block) + "\n"
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    _atomic_write(path, text, mode)


def remove_service_entry(name: str) -> bool:
    path = service_file()
    lines = _read_lines(path)
    outside, _ = _split_service_sections(lines, name)
    if len(outside) == len(lines):
        return False
    while outside and not outside[-1].strip():
        outside.pop()
    _atomic_write(path, "\n".join(outside) + ("\n" if outside else ""), path.stat().st_mode & 0o777)
    return True


def save_cert(service_name: str, props: Dict[str, Any]) -> Optional[Path]:
    pem = str(props.get("certificate") or "").strip()
    if not pem.startswith("-----BEGIN CERTIFICATE-----"):
        return None
    path = cert_path(service_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    _atomic_write(path, pem + "\n", 0o600)
    return path


def write_connection(service_name: str, host: str, cert: Optional[Path]) -> None:
    values = {
        "host": host,
        "port": str(PG_PORT),
        "dbname": env("PG_DATABASE_NAME"),
        "user": env("PG_USER", "snowflake_admin"),
    }
    if cert:
        values["sslmode"] = "verify-ca"
        values["sslrootcert"] = str(cert)
    else:
        values["sslmode"] = "require"
    save_service_entry(service_name, values)


# ---------------------------------------------------------------------------
# Instance helpers
# ---------------------------------------------------------------------------

def print_safe(instance: Dict[str, Any]) -> None:
    for field in SAFE_FIELDS:
        if instance.get(field) not in (None, ""):
            print(f"  {field:<18} {instance[field]}")


def check_feature() -> None:
    try:
        run_snow_sql("SHOW POSTGRES INSTANCES")
    except LabError as exc:
        raise LabError(f"{exc}\n\nSnowflake Postgres may not be enabled for this account or region, "
                       "or the role lacks access. Confirm availability with your account admin.")


def check_family_available(family: str) -> None:
    """Fail before CREATE when the compute family is not offered in this account's cloud."""
    if family.upper() not in AWS_ONLY_FAMILIES:
        return
    rows = run_snow_sql("SELECT CURRENT_REGION() AS region")
    region = str(_lower_keys(rows[0]).get("region", "")) if rows else ""
    if "AZURE" in region.upper():
        raise LabError(f"PG_COMPUTE_FAMILY={family} is not available on Azure (region {region}). "
                       "Set PG_COMPUTE_FAMILY=STANDARD_L in .env/mirror.env, the smallest family "
                       "on Azure that supports mirroring.")


def wait_ready(name: str, timeout: int, resume: bool) -> Dict[str, Any]:
    start = time.time()
    last_state = None
    resumed = False
    print(f"Waiting for {name} to be READY (timeout {timeout}s)...")
    while True:
        instance = show_instance(name)
        if instance is None:
            raise LabError(f"Instance {name} not found")
        state = str(instance.get("state", "UNKNOWN")).upper()
        elapsed = int(time.time() - start)
        if state != last_state:
            print(f"  [{elapsed:>4}s] {state}")
            last_state = state
        if state in READY_STATES:
            return instance
        if state in FAILED_STATES:
            raise LabError(f"Instance {name} is {state}. Check Snowsight > Postgres for details.")
        if state == "SUSPENDED":
            if not resume:
                raise LabError(f"Instance {name} is SUSPENDED. Resume it with: "
                               f"ALTER POSTGRES INSTANCE {quote_ident(name)} RESUME;")
            if not resumed:
                print("  Resuming suspended instance (typically 3-5 minutes)...")
                run_snow_sql(f"ALTER POSTGRES INSTANCE {quote_ident(name)} RESUME")
                resumed = True
        if elapsed > timeout:
            raise LabError(f"Timed out after {elapsed}s waiting for READY (last state: {state})")
        time.sleep(POLL_SECONDS)


def probe(host: str) -> None:
    try:
        with socket.create_connection((host, PG_PORT), timeout=PROBE_TIMEOUT_SECONDS):
            print(f"✓ Port {PG_PORT} reachable on {host}")
    except socket.timeout:
        print(f"⚠️  Port {PG_PORT} on {host} timed out. Your IP is probably not allowed by the "
              "instance's network policy. Create mode: run `task pg-allow-my-ip` "
              "(or set PG_ALLOWED_CIDR if Snowflake sees a different IP than Postgres will).")
    except ConnectionRefusedError:
        print(f"⏳ Port {PG_PORT} on {host} refused the connection; the instance may still be starting.")
    except socket.gaierror:
        print(f"⏳ {host} does not resolve yet; DNS can take 30-60s after creation.")
    except OSError as exc:
        print(f"⚠️  TCP probe failed: {exc}")


def instance_host(instance: Dict[str, Any], props: Dict[str, Any]) -> str:
    host = props.get("host") or instance.get("host")
    if not host:
        raise LabError("Could not determine the instance host from SHOW/DESCRIBE output")
    return str(host)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> None:
    require_mode("create")
    name = env("PG_INSTANCE_NAME")
    service_name = env("PG_SERVICE_NAME")
    database = env("PG_DATABASE_NAME")
    user = env("PG_USER", "snowflake_admin")
    family = env("PG_COMPUTE_FAMILY")
    if family.upper().startswith("BURST"):
        raise LabError("BURSTABLE compute families are not supported for mirroring")
    storage = int(env("PG_STORAGE_SIZE_GB"))
    policy = env("PG_NETWORK_POLICY_NAME")

    check_feature()
    instance = show_instance(name)
    if instance:
        print(f"Instance {name} already exists (state {instance.get('state')}); reusing it.")
        instance = wait_ready(name, args.timeout, resume=True)
        props = describe_instance(name)
        host = instance_host(instance, props)
        if not find_pgpass_entry(host, PG_PORT, database, user):
            raise LabError(f"Instance {name} exists but no password for {user} is saved in "
                           f"{pgpass_file()}. Run `task pg-reset-access` to rotate and save one, "
                           "or `task demo-teardown` to start over.")
    else:
        check_family_available(family)
        print(f"Creating Snowflake Postgres instance {name} "
              f"({family}, {storage} GB, network policy {policy})...")
        rows = run_snow_sql(
            f"CREATE POSTGRES INSTANCE {quote_ident(name)}\n"
            f"  COMPUTE_FAMILY = '{family}'\n"
            f"  STORAGE_SIZE_GB = {storage}\n"
            f"  AUTHENTICATION_AUTHORITY = POSTGRES\n"
            f"  NETWORK_POLICY = '{policy}'\n"
            f"  COMMENT = 'Snowflake Postgres mirror HOL source instance'"
        )
        host = find_host(rows)
        password = find_password(rows, user)
        if not host or not password:
            shape = sorted({str(k) for row in rows for k in row.keys()})
            raise LabError(f"Instance {name} was created, but the response could not be parsed "
                           f"(columns: {shape}). Run `task pg-reset-access` to rotate and save "
                           "a password.")
        upsert_pgpass_entry(host, PG_PORT, database, user, password)
        del password, rows
        print(f"✓ {user} password saved to {pgpass_file()} (mode 600); it is never displayed")
        instance = wait_ready(name, args.timeout, resume=True)
        props = describe_instance(name)
        host = instance_host(instance, props)

    cert = save_cert(service_name, props)
    write_connection(service_name, host, cert)
    print(f"✓ Service entry [{service_name}] saved to {service_file()}"
          + (f" (sslmode=verify-ca, CA cert {cert})" if cert else " (sslmode=require; no CA cert found)"))
    probe(host)
    print("")
    print_safe(instance)
    print(f'\nConnect any time with: psql "service={service_name}"')


def cmd_attach(args: argparse.Namespace) -> None:
    require_mode("existing")
    name = env("PG_INSTANCE_NAME")
    service_name = env("PG_SERVICE_NAME")
    database = env("PG_DATABASE_NAME")
    user = env("PG_USER", "snowflake_admin")
    role = env("MIRROR_ADMIN_ROLE_NAME")

    check_feature()
    instance = show_instance(name)
    if instance is None:
        names = [_lower_keys(r).get("name") for r in run_snow_sql("SHOW POSTGRES INSTANCES")]
        raise LabError(f"Instance {name} not found. Instances visible to {role}: {names}. "
                       "PG_INSTANCE_NAME must match exactly (it is case-sensitive).")
    owner = str(instance.get("owner", ""))
    if owner.upper() != role.upper():
        raise LabError(f"Instance {name} is owned by {owner}, not {role}. Mirror procedures require "
                       "the caller to own the source instance: set MIRROR_ADMIN_ROLE_NAME to the "
                       "owning role.")
    instance = wait_ready(name, args.timeout, resume=True)
    props = describe_instance(name)
    host = instance_host(instance, props)

    existing = read_service_entry(service_name)
    if existing is None:
        cert = save_cert(service_name, props)
        write_connection(service_name, host, cert)
        print(f"✓ Service entry [{service_name}] saved to {service_file()}")
    elif existing.get("host") != host:
        raise LabError(f"Service entry [{service_name}] in {service_file()} points at "
                       f"{existing.get('host')}, not {host}. Set PG_SERVICE_NAME to a different "
                       "name or fix the entry.")
    else:
        print(f"✓ Using existing service entry [{service_name}] in {service_file()}")

    if not find_pgpass_entry(host, PG_PORT, database, user):
        raise LabError(
            f"No password for {user}@{host}/{database} in {pgpass_file()}.\n"
            f"  Add this line yourself (then chmod 600 {pgpass_file()}):\n"
            f"    {host}:{PG_PORT}:{database}:{user}:<password>\n"
            "  or run `task pg-reset-access` to rotate the password (other clients using the "
            "old password will stop working).")
    print(f"✓ Password for {user} found in {pgpass_file()}")
    probe(host)
    print("")
    print_safe(instance)


def cmd_wait_ready(args: argparse.Namespace) -> None:
    instance = wait_ready(env("PG_INSTANCE_NAME"), args.timeout, resume=args.resume)
    print_safe(instance)


def cmd_info(_args: argparse.Namespace) -> None:
    instance = show_instance(env("PG_INSTANCE_NAME"))
    if instance is None:
        raise LabError(f"Instance {env('PG_INSTANCE_NAME')} not found")
    print_safe(instance)


def cmd_reset_access(args: argparse.Namespace) -> None:
    if not args.yes:
        raise LabError("reset-access rotates the password; re-run with --yes to confirm")
    name = env("PG_INSTANCE_NAME")
    user = env("PG_USER", "snowflake_admin")
    if user not in ("snowflake_admin", "application"):
        raise LabError("RESET ACCESS supports only the snowflake_admin and application roles")
    instance = show_instance(name)
    if instance is None:
        raise LabError(f"Instance {name} not found")
    host = instance_host(instance, describe_instance(name))
    rows = run_snow_sql(f"ALTER POSTGRES INSTANCE {quote_ident(name)} RESET ACCESS FOR '{user}'")
    password = find_password(rows, user)
    if not password:
        shape = sorted({str(k) for row in rows for k in row.keys()})
        raise LabError(f"RESET ACCESS ran but no password was found in the response (columns: {shape})")
    upsert_pgpass_entry(host, PG_PORT, env("PG_DATABASE_NAME"), user, password)
    del password, rows
    print(f"✓ New {user} password saved to {pgpass_file()} (mode 600); it is never displayed")


def cmd_drop(args: argparse.Namespace) -> None:
    require_mode("create")  # never drop a bring-your-own instance
    if not args.yes:
        raise LabError("drop deletes the instance and all of its data; re-run with --yes to confirm")
    name = env("PG_INSTANCE_NAME")
    if show_instance(name) is None:
        print(f"Instance {name} not found; nothing to drop.")
        return
    print(f"Dropping Snowflake Postgres instance {name}...")
    run_snow_sql(f"DROP POSTGRES INSTANCE {quote_ident(name)}")
    start = time.time()
    while True:
        instance = show_instance(name)
        if instance is None:
            print(f"✓ Instance {name} dropped")
            return
        elapsed = int(time.time() - start)
        if elapsed > args.timeout:
            raise LabError(f"Instance {name} still present after {elapsed}s "
                           f"(state {instance.get('state')})")
        print(f"  [{elapsed:>4}s] {instance.get('state')}")
        time.sleep(POLL_SECONDS)


def cmd_forget(_args: argparse.Namespace) -> None:
    service_name = env("PG_SERVICE_NAME")
    entry = read_service_entry(service_name)
    if entry and entry.get("host"):
        removed = remove_pgpass_entries(entry["host"])
        print(f"✓ Removed {removed} password line(s) for {entry['host']} from {pgpass_file()}")
    if remove_service_entry(service_name):
        print(f"✓ Removed service entry [{service_name}] from {service_file()}")
    else:
        print(f"Service entry [{service_name}] not found in {service_file()}")
    cert = cert_path(service_name)
    if cert.exists():
        cert.unlink()
        print(f"✓ Removed CA cert {cert}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Snowflake Postgres instance lifecycle for the mirror HOL")
    sub = parser.add_subparsers(dest="command", required=True)

    for command, func, help_text in (
        ("create", cmd_create, "create mode: create or reuse the instance and save the connection"),
        ("attach", cmd_attach, "existing mode: verify the instance and save the service entry"),
        ("wait-ready", cmd_wait_ready, "wait until the instance is READY"),
    ):
        p = sub.add_parser(command, help=help_text)
        p.add_argument("--timeout", type=int, default=900, help="seconds to wait for READY (default: 900)")
        if command == "wait-ready":
            p.add_argument("--resume", action="store_true", help="resume the instance if it is suspended")
        p.set_defaults(func=func)

    sub.add_parser("info", help="show safe instance fields").set_defaults(func=cmd_info)

    p = sub.add_parser("reset-access", help="rotate the PG_USER password into ~/.pgpass")
    p.add_argument("--yes", action="store_true", help="confirm the password rotation")
    p.set_defaults(func=cmd_reset_access)

    p = sub.add_parser("drop", help="create mode: drop the instance and wait until it is gone")
    p.add_argument("--yes", action="store_true", help="confirm the drop")
    p.add_argument("--timeout", type=int, default=900, help="seconds to wait (default: 900)")
    p.set_defaults(func=cmd_drop)

    sub.add_parser("forget", help="remove the local service entry, password, and CA cert").set_defaults(func=cmd_forget)

    args = parser.parse_args()
    try:
        args.func(args)
    except LabError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
