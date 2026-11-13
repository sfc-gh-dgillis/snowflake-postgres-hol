#!/usr/bin/env python3
"""
dcm - runs the lab's DCM (Database Change Management) projects with the snow CLI

Two projects, one folder each under tasks/snow-cli/dcm/:
  iot_mirror_lab        setup: lab database / schema / stage, warehouse, analyst role,
                        and (create mode) the Postgres ingress network rule and policy
  iot_mirror_analytics  lab-7: dynamic table and semantic view on the mirrored tables;
                        deployed after iot_mirror_lab and purged before it

.env/mirror.env is the single source of truth. Every command passes the project
identifier built from DCM_PROJECT_DATABASE.DCM_PROJECT_SCHEMA.<project name>, and
analyze / plan / deploy pass every templating variable with -D, so manifest.yml carries
only documentation defaults. Values are passed as argument lists (no shell), and a value
containing a single quote is refused because it would break -D "name='value'".

Every command runs as MIRROR_ADMIN_ROLE_NAME: DCM makes the executing role the owner of
every object it creates.

Commands:
  create     register the project object (no-op if it exists)
  analyze    validate the definitions; fail only on issues above INFO
  plan       show what deploy would create, alter, or drop (writes out/plan_result.json)
  deploy     reconcile Snowflake with the definitions (requires --alias)
  purge      drop every object the project manages (requires --yes; skipped if the
             project does not exist)
  drop       remove the project registration only (managed objects are left alone)
  exists     exit 0 if the project object exists, 1 if not, 2 if it cannot tell
  variables  print the -D variables a plan would use (no secrets: names and your IP)

Usage: dcm.py COMMAND PROJECT [--alias TEXT] [--yes]   (run from tasks/snow-cli)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DCM_ROOT = Path(__file__).resolve().parents[2] / "dcm"
TARGET = "DEV"
CIDR = re.compile(r"^(\d{1,3}\.){3}\d{1,3}/(\d|[12]\d|3[0-2])$")
MIN_PREFIX = 8


class LabError(Exception):
    """An expected failure with a user-facing message."""


def env(name: str, default: Optional[str] = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise LabError(f"{name} is not set (see .env/mirror.env)")
    return value


# ---------------------------------------------------------------------------
# Snowflake session values
# ---------------------------------------------------------------------------

def session_values() -> Dict[str, str]:
    """CURRENT_USER() and CURRENT_IP_ADDRESS() for the lab's connection and role."""
    cmd = ["snow", "sql", "--connection", env("CLI_CONNECTION_NAME"),
           "--role", env("MIRROR_ADMIN_ROLE_NAME"), "--format", "JSON",
           "--enable-templating", "NONE",
           "-q", "SELECT CURRENT_USER() AS USER_NAME, CURRENT_IP_ADDRESS() AS IP"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise LabError("Could not read CURRENT_USER() / CURRENT_IP_ADDRESS(): "
                       + (result.stderr or result.stdout).strip())
    start = min(i for i in (result.stdout.find("["), result.stdout.find("{")) if i >= 0)
    data, _ = json.JSONDecoder().raw_decode(result.stdout[start:])
    row = data[0] if isinstance(data, list) else data
    row = {str(k).lower(): v for k, v in row.items()}
    return {"user": str(row.get("user_name") or ""), "ip": str(row.get("ip") or "")}


def allowed_cidr(ip: str) -> str:
    """PG_ALLOWED_CIDR, or AUTO = the IP Snowflake sees /32; never wider than /8."""
    cidr = os.environ.get("PG_ALLOWED_CIDR", "AUTO")
    if cidr == "AUTO":
        if ":" in ip or not ip:
            raise LabError(f"CURRENT_IP_ADDRESS() is not IPv4 ({ip or 'empty'}). Set PG_ALLOWED_CIDR "
                           "in .env/mirror.env to your public IPv4 address with /32.")
        cidr = f"{ip}/32"
    if not CIDR.match(cidr):
        raise LabError(f"PG_ALLOWED_CIDR={cidr} must be AUTO or an IPv4 CIDR such as 203.0.113.7/32")
    if int(cidr.split("/")[1]) < MIN_PREFIX:
        raise LabError(f"Refusing to open Postgres to {cidr}, a range wider than /{MIN_PREFIX}. "
                       "Set PG_ALLOWED_CIDR to your own IP/32.")
    return cidr


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

def setup_variables() -> Dict[str, str]:
    mode = os.environ.get("POSTGRES_INSTANCE_MODE", "create")
    session = session_values()
    if not session["user"]:
        raise LabError("Could not resolve the current Snowflake user")
    managed = env("DEMO_WAREHOUSE_MANAGED").lower()
    if managed not in ("true", "false"):
        raise LabError(f"DEMO_WAREHOUSE_MANAGED={managed} must be true or false")
    values = {
        "lab_database": env("DEMO_DATABASE_NAME"),
        "lab_database_comment": env("DEMO_DATABASE_DDL_COMMENT"),
        "lab_schema": env("DEMO_SCHEMA_NAME"),
        "lab_stage": env("DEMO_INTERNAL_NAMED_STAGE"),
        "lab_stage_comment": env("DEMO_INTERNAL_NAMED_STAGE_COMMENT"),
        "warehouse": env("DEMO_WAREHOUSE_NAME"),
        "warehouse_managed": managed,
        "analyst_role": env("DEMO_ANALYST_ROLE_NAME"),
        "setup_user": session["user"],
        "instance_mode": mode,
        "pg_network_rule": "",
        "pg_network_policy": "",
        "pg_allowed_cidr": "",
    }
    if mode == "create":
        values["pg_network_rule"] = env("PG_NETWORK_RULE_NAME")
        values["pg_network_policy"] = env("PG_NETWORK_POLICY_NAME")
        values["pg_allowed_cidr"] = allowed_cidr(session["ip"])
    return values


def analytics_variables() -> Dict[str, str]:
    return {
        "lab_database": env("DEMO_DATABASE_NAME"),
        "lab_schema": env("DEMO_SCHEMA_NAME"),
        "warehouse": env("DEMO_WAREHOUSE_NAME"),
        "analyst_role": env("DEMO_ANALYST_ROLE_NAME"),
        "mirror_database": env("MIRROR_TARGET_DATABASE_NAME"),
        "mirror_schema": env("PG_SCHEMA_NAME"),
        "dynamic_table": env("DEMO_DYNAMIC_TABLE_NAME"),
        "semantic_view": env("DEMO_SEMANTIC_VIEW_NAME"),
    }


PROJECTS = {
    "iot_mirror_lab": ("DCM_SETUP_PROJECT_NAME", setup_variables),
    "iot_mirror_analytics": ("DCM_ANALYTICS_PROJECT_NAME", analytics_variables),
}


def identifier(project: str) -> str:
    name_var = PROJECTS[project][0]
    return f"{env('DCM_PROJECT_DATABASE')}.{env('DCM_PROJECT_SCHEMA')}.{env(name_var)}"


def variable_flags(project: str) -> List[str]:
    flags: List[str] = []
    for name, value in PROJECTS[project][1]().items():
        if "'" in value or any(ord(ch) < 32 for ch in value):
            raise LabError(f"The value for {name} ({value!r}) contains a quote or control character; "
                           "remove it in .env/mirror.env")
        flags += ["-D", f"{name}='{value}'"]
    return flags


def snow_dcm(command: str, project: str, extra: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    cmd = ["snow", "dcm", command, identifier(project),
           "--connection", env("CLI_CONNECTION_NAME"),
           "--role", env("MIRROR_ADMIN_ROLE_NAME"),
           "--from", ".", "--target", TARGET] + extra
    try:
        return subprocess.run(cmd, cwd=DCM_ROOT / project, text=True, capture_output=capture)
    except FileNotFoundError:
        raise LabError("snow CLI not found; run `task validate-prerequisites`")


def project_exists(project: str) -> bool:
    """DESCRIBE takes the identifier as-is; only 'does not exist' means missing."""
    ident = identifier(project)
    result = subprocess.run(
        ["snow", "sql", "--connection", env("CLI_CONNECTION_NAME"), "--role", env("MIRROR_ADMIN_ROLE_NAME"),
         "--enable-templating", "NONE", "-q", f"DESCRIBE DCM PROJECT {ident}"],
        capture_output=True, text=True)
    if result.returncode == 0:
        return True
    output = result.stderr + result.stdout
    # Snowflake reports a missing object as "does not exist or not authorized"; anything
    # else (expired token, network) must not be mistaken for a project that is gone.
    if re.search(r"does not exist", output, re.I):
        return False
    raise LabError(f"Could not check DCM project {ident}:\n{output.strip()}")


def check(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        raise LabError(f"snow dcm {what} failed for {result.args[3]} (exit {result.returncode})")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> None:
    print(f"Registering DCM project {identifier(args.project)} (if not exists)...", flush=True)
    check(snow_dcm("create", args.project, ["--if-not-exists"]), "create")


def cmd_analyze(args: argparse.Namespace) -> None:
    """raw-analyze exits 1 on any issue, INFO included: decide from its JSON instead."""
    result = snow_dcm("raw-analyze", args.project, variable_flags(args.project), capture=True)
    line = next((ln for ln in result.stdout.splitlines() if ln.startswith("{")), "")
    try:
        analysis = json.loads(line)
    except ValueError:
        raise LabError(f"snow dcm raw-analyze returned no analysis (exit {result.returncode}):\n"
                       + (result.stderr or result.stdout).strip())

    issues = [("project", i) for i in analysis.get("issues") or []]
    definitions = 0
    for file in analysis.get("files") or []:
        issues += [(file.get("source_path", "?"), i) for i in file.get("issues") or []]
        for definition in file.get("definitions") or []:
            definitions += 1
            ident = definition.get("id") or {}
            where = ".".join(str(ident[k]).replace('"', "") for k in ("database", "schema", "name") if ident.get(k))
            issues += [(where, i) for i in definition.get("issues") or []]

    print(f"{args.project}: {definitions} definitions analyzed.")
    for where, issue in issues:
        print(f"  {issue.get('severity', 'UNKNOWN')}\t{where}\t{issue.get('message', '')}")
    if any(issue.get("severity") != "INFO" for _, issue in issues):
        raise LabError("issues above INFO severity")
    print("No issues." if not issues else "INFO only.")


def cmd_plan(args: argparse.Namespace) -> None:
    check(snow_dcm("plan", args.project, ["--save-output"] + variable_flags(args.project)), "plan")
    print(f"\nPlan saved to {DCM_ROOT / args.project / 'out'}")


def cmd_deploy(args: argparse.Namespace) -> None:
    if not args.alias:
        raise LabError("deploy requires --alias")
    alias = f"{args.alias} {datetime.now():%Y%m%d_%H%M%S}"
    check(snow_dcm("deploy", args.project, ["--alias", alias] + variable_flags(args.project)), "deploy")


def cmd_purge(args: argparse.Namespace) -> None:
    if not args.yes:
        raise LabError("purge drops every object the project manages; re-run with --yes")
    # purge has no --if-exists: skip (rather than fail) once the project is gone
    if not project_exists(args.project):
        print(f"DCM project {identifier(args.project)} not found; nothing to purge.")
        return
    check(snow_dcm("purge", args.project, ["--force"]), "purge")


def cmd_drop(args: argparse.Namespace) -> None:
    # Checked first as well: --if-exists does not cover a missing parent schema
    if not project_exists(args.project):
        print(f"DCM project {identifier(args.project)} not found; nothing to drop.")
        return
    check(snow_dcm("drop", args.project, ["--if-exists"]), "drop")


def cmd_exists(args: argparse.Namespace) -> None:
    sys.exit(0 if project_exists(args.project) else 1)


def cmd_variables(args: argparse.Namespace) -> None:
    flags = variable_flags(args.project)
    print(f"{identifier(args.project)}")
    for value in flags[1::2]:
        print(f"  -D {value}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Runs the lab's DCM projects with the snow CLI")
    parser.add_argument("command", choices=["create", "analyze", "plan", "deploy", "purge", "drop",
                                            "exists", "variables"])
    parser.add_argument("project", choices=sorted(PROJECTS))
    parser.add_argument("--alias", help="deploy: deployment alias (a timestamp is appended)")
    parser.add_argument("--yes", action="store_true", help="purge: confirm dropping every managed object")
    args = parser.parse_args()

    commands = {"create": cmd_create, "analyze": cmd_analyze, "plan": cmd_plan, "deploy": cmd_deploy,
                "purge": cmd_purge, "drop": cmd_drop, "exists": cmd_exists, "variables": cmd_variables}
    try:
        commands[args.command](args)
    except LabError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2 if args.command == "exists" else 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
